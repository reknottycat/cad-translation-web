"""Rebuildable SQLite summary index; task manifests remain authoritative.

Normal task mutations update this index. Directory changes trigger reconciliation;
startup also reconciles changed manifests written by older application versions.
List requests query only their page rather than opening every historical file.
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterator

from app.services.cad_task_types import is_valid_task_id
from app.utils.locking import file_lock

_STATUS_RANK = {"processing": 0, "queued": 1, "partial": 2, "error": 3, "cancelled": 4, "done": 5}


class CadTaskIndex:
    def __init__(self, root: Path, summarize: Callable[[dict[str, Any]], dict[str, Any]]):
        self.root = root
        self.path = root.parent / f"{root.name}.index.sqlite3"
        self.dirty = self.path.with_suffix(".dirty")
        self.summarize = summarize
        self._initialized = False
        self._init_lock = threading.Lock()

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=120)
        try:
            # The index is reconstructible; canonical JSON writes remain fsynced.
            connection.execute("PRAGMA synchronous=NORMAL")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def ensure_ready(self) -> None:
        with self._init_lock:
            if self._initialized and self.path.exists():
                return
            self.root.mkdir(parents=True, exist_ok=True)
            with file_lock(self.path.with_suffix(".init")), self._connect() as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.executescript("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        task_id TEXT PRIMARY KEY,
                        status_rank INTEGER NOT NULL,
                        activity REAL NOT NULL,
                        summary TEXT NOT NULL,
                        mtime_ns INTEGER NOT NULL,
                        size INTEGER NOT NULL,
                        inode TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS task_order ON tasks(status_rank, activity DESC, task_id);
                    CREATE INDEX IF NOT EXISTS task_activity ON tasks(activity);
                    CREATE TABLE IF NOT EXISTS index_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                """)
            self._initialized = True

    def _row(self, metadata: dict[str, Any], path: Path, stat_result=None):
        summary = self.summarize(metadata)
        stat_result = stat_result or path.stat()
        return (
            metadata["task_id"], _STATUS_RANK.get(summary["status"], 9),
            float(summary.get("last_activity_at") or summary.get("created_at") or 0),
            json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
            stat_result.st_mtime_ns, stat_result.st_size, str(stat_result.st_ino),
        )

    @staticmethod
    def _write(connection, row):
        connection.execute("INSERT OR REPLACE INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?)", row)

    def reconcile(self, force: bool = False) -> None:
        self.ensure_ready()
        root_stamp = str(self.root.stat().st_mtime_ns)
        with self._connect() as connection:
            stored = connection.execute("SELECT value FROM index_meta WHERE key='root_stamp'").fetchone()
            if not force and not self.dirty.exists() and stored and stored[0] == root_stamp:
                return
            # Begin before reading files: a concurrent writer publishes JSON,
            # then waits here and overwrites any older imported summary.
            connection.execute("BEGIN IMMEDIATE")
            known = {row[0]: tuple(row[1:]) for row in connection.execute(
                "SELECT task_id, mtime_ns, size, inode FROM tasks"
            )}
            seen = set()
            changed = []
            for path in self.root.glob("*/task.json"):
                task_id = path.parent.name
                if not is_valid_task_id(task_id):
                    continue
                try:
                    info = path.stat()
                    signature = (info.st_mtime_ns, info.st_size, str(info.st_ino))
                    seen.add(task_id)
                    if known.get(task_id) == signature:
                        continue
                    changed.append((path, info))
                except OSError:
                    connection.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))

            def read_changed(item):
                path, info = item
                task_id = path.parent.name
                try:
                    metadata = json.loads(path.read_text(encoding="utf-8"))
                    if metadata.get("task_id") != task_id:
                        raise ValueError("Task manifest ID does not match directory")
                    return task_id, self._row(metadata, path, info)
                except (OSError, ValueError, KeyError, TypeError):
                    return task_id, None

            # Import is I/O-bound on Windows. Bound both readers and pending
            # futures; SQLite writes remain on this transaction's owning thread.
            if changed:
                with ThreadPoolExecutor(max_workers=min(8, len(changed))) as readers:
                    for start in range(0, len(changed), 128):
                        for task_id, row in readers.map(read_changed, changed[start:start + 128]):
                            if row is None:
                                connection.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))
                            else:
                                self._write(connection, row)
            connection.executemany("DELETE FROM tasks WHERE task_id=?", ((key,) for key in known.keys() - seen))
            connection.execute("INSERT OR REPLACE INTO index_meta VALUES ('root_stamp', ?)", (root_stamp,))
        self.dirty.unlink(missing_ok=True)

    def upsert(self, metadata: dict[str, Any], path: Path) -> None:
        self.ensure_ready()
        with self._connect() as connection:
            self._write(connection, self._row(metadata, path))
            connection.execute("UPDATE index_meta SET value=? WHERE key='root_stamp'",
                               (str(self.root.stat().st_mtime_ns),))

    def discard(self, task_id: str) -> None:
        self.ensure_ready()
        with self._connect() as connection:
            connection.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))
            connection.execute("UPDATE index_meta SET value=? WHERE key='root_stamp'",
                               (str(self.root.stat().st_mtime_ns),))

    def active_ids(self):
        self.reconcile(force=True)
        with self._connect() as connection:
            return [row[0] for row in connection.execute("SELECT task_id FROM tasks WHERE status_rank <= 1")]

    def page(self, limit: int | None = 100, offset: int = 0, updated_after: float | None = None):
        self.reconcile()
        where = "WHERE activity > ?" if updated_after is not None else ""
        params = (updated_after,) if updated_after is not None else ()
        with self._connect() as connection:
            connection.execute("BEGIN")
            total = connection.execute(f"SELECT COUNT(*) FROM tasks {where}", params).fetchone()[0]
            rows = connection.execute(
                f"SELECT summary FROM tasks {where} ORDER BY status_rank, activity DESC, task_id LIMIT ? OFFSET ?",
                (*params, -1 if limit is None else limit, offset),
            ).fetchall()
        return {"data": [json.loads(row[0]) for row in rows], "total": total, "limit": limit, "offset": offset}
