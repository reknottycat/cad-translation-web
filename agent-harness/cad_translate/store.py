#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local project / task file store for the ``cad-translate`` CLI.

The CLI is a **local single-user tool** by design.  It keeps per-project and
per-task state in plain JSON files under the configured output root, always
reusing the backend's trusted primitives so the CLI and the Web share the same
path-safety, cross-process lock and atomic-write semantics:

* task ids are validated with ``app.services.cad_pipeline_service.validate_task_id``
  (8 lowercase hex chars) so no user-supplied id can ever escape the task tree;
* output file names are sanitised with ``app.utils.file_utils.get_safe_filename``;
* every read/write/delete on a task directory is serialised with the same
  per-task lifecycle lock (kept in a stable ``cad_task_lifecycle/`` sibling
  directory *outside* the task tree) used by the backend;
* metadata writes are atomic (temp file + ``os.replace``) via
  ``app.utils.locking.atomic_write_json`` so a concurrent reader never sees a
  half-written file;
* clear/delete run under a global creation/clear coordination lock so a task
  created concurrently with a ``clear`` cannot be swept or escape.

This keeps one coherent story: configuration and tasks are never shared with or
overwritten by the Web backend, because the CLI resolves the *same* settings
(and therefore the *same* output root) through ``app.config``.

Backend imports are intentionally **lazy**: ``app.*`` modules (and their heavy
transitive dependencies such as FastAPI, SQLAlchemy, Celery, ...) are only
pulled in the first time a store helper that actually needs them is called.
That keeps ``cad-translate --version`` / ``--help`` usable in a clean
environment where only the CLI's own lightweight dependencies are installed and
the backend has not been imported yet (see Issue #14 / review).
"""
from __future__ import annotations

import contextlib
import json
import shutil
import stat
import uuid
from pathlib import Path
from typing import Any, Iterator

from . import bridge

# Backend primitives are resolved lazily through the thin accessor functions
# below so importing this module never pulls in ``app.*`` at import time.
__all__ = [
    "output_root",
    "tasks_root",
    "lifecycle_root",
    "global_coord_lock_path",
    "new_task_id",
    "task_dir",
    "task_meta_path",
    "task_lifecycle_lock_path",
    "task_lifecycle_lock",
    "task_create_or_clear_lock",
    "prepare_task_dir",
    "load_task",
    "save_task",
    "summarize_task",
    "list_tasks",
    "delete_task",
    "clear_tasks",
    "write_project_file",
    "load_project_file",
    "validate_task_id",
    "is_valid_task_id",
    "get_safe_filename",
    "resolve_within_directory",
    "atomic_write_json",
    "atomic_write_text",
    "file_lock",
]


# ---------------------------------------------------------------------------
# Lazy backend primitive accessors (single source of truth = backend/app).
# ---------------------------------------------------------------------------
def validate_task_id(task_id: Any) -> None:
    bridge.ensure_backend_importable()
    from app.services.cad_pipeline_service import validate_task_id as _f

    _f(task_id)


def is_valid_task_id(task_id: Any) -> bool:
    bridge.ensure_backend_importable()
    from app.services.cad_pipeline_service import is_valid_task_id as _f

    return _f(task_id)


def get_safe_filename(filename: str) -> str:
    bridge.ensure_backend_importable()
    from app.utils.file_utils import get_safe_filename as _f

    return _f(filename)


def resolve_within_directory(base_dir: Path, relative_path: str | Path) -> Path:
    bridge.ensure_backend_importable()
    from app.utils.file_utils import resolve_within_directory as _f

    return _f(base_dir, relative_path)


@contextlib.contextmanager
def file_lock(
    path: Path,
    blocking: bool = True,
    create_parents: bool = True,
) -> Iterator[None]:
    bridge.ensure_backend_importable()
    from app.utils.locking import file_lock as _file_lock

    with _file_lock(path, blocking=blocking, create_parents=create_parents):
        yield


def atomic_write_json(
    path: Path,
    payload: Any,
    create_parents: bool = True,
) -> None:
    bridge.ensure_backend_importable()
    from app.utils.locking import atomic_write_json as _f

    _f(path, payload, create_parents=create_parents)


def atomic_write_text(
    path: Path,
    content: str,
    create_parents: bool = True,
) -> None:
    bridge.ensure_backend_importable()
    from app.utils.locking import atomic_write_text as _f

    _f(path, content, create_parents=create_parents)


def output_root() -> Path:
    return bridge.get_settings().get_output_path()


def tasks_root() -> Path:
    root = output_root() / "cad_tasks"
    root.mkdir(parents=True, exist_ok=True)
    return root


def lifecycle_root() -> Path:
    """Stable directory holding per-task lifecycle locks (outside task tree)."""
    root = output_root() / "cad_task_lifecycle"
    root.mkdir(parents=True, exist_ok=True)
    return root


def global_coord_lock_path() -> Path:
    path = output_root() / "cad_tasks.coord"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def new_task_id() -> str:
    return uuid.uuid4().hex[:8]


def task_dir(task_id: str) -> Path:
    validate_task_id(task_id)
    return tasks_root() / task_id


def task_meta_path(task_id: str) -> Path:
    validate_task_id(task_id)
    return task_dir(task_id) / "task.json"


def task_lifecycle_lock_path(task_id: str) -> Path:
    validate_task_id(task_id)
    return lifecycle_root() / f"{task_id}.lifecycle"


@contextlib.contextmanager
def task_lifecycle_lock(task_id: str) -> Iterator[None]:
    """Serialize writers and deleters on a task directory (same as backend)."""
    validate_task_id(task_id)
    lock_path = task_lifecycle_lock_path(task_id)
    with file_lock(lock_path):
        yield


@contextlib.contextmanager
def task_create_or_clear_lock() -> Iterator[None]:
    """Serialize task creation against ``clear`` (same as backend)."""
    with file_lock(global_coord_lock_path()):
        yield


def _handle_remove_readonly(func: Any, path: str, exc_info: Any) -> None:
    """Windows helper: allow deleting read-only files inside a task dir."""
    os_path = Path(path)
    try:
        os_path.chmod(stat.S_IWRITE)
    except OSError:
        pass
    func(path)


def _delete_tree(path: Path) -> None:
    if path.exists() and path.is_dir():
        shutil.rmtree(path, onerror=_handle_remove_readonly)


def prepare_task_dir(task_id: str, created_at: float | None = None) -> Path:
    """Create a new task directory under the create/clear coordination lock.

    Returns the task directory.  The caller must hold ``task_lifecycle_lock``
    for the whole write operation so a concurrent delete cannot interleave.
    """
    directory = task_dir(task_id)
    with file_lock(task_meta_path(task_id), create_parents=True):
        directory.mkdir(parents=True, exist_ok=False)
        meta = {
            "task_id": task_id,
            "created_at": created_at if created_at is not None else _now(),
            "last_activity_at": created_at if created_at is not None else _now(),
            "status": "created",
            "stage": "created",
        }
        _write_meta(directory, meta)
    return directory


def _now() -> float:
    import time

    return time.time()


def _write_meta(directory: Path, meta: dict[str, Any]) -> None:
    """Atomic metadata write that never recreates a deleted task dir."""
    atomic_write_json(directory / "task.json", meta, create_parents=False)


def load_task(task_id: str) -> dict[str, Any]:
    validate_task_id(task_id)
    with task_lifecycle_lock(task_id):
        path = task_meta_path(task_id)
        if not path.exists():
            raise FileNotFoundError(f"Task not found: {task_id}")
        return json.loads(path.read_text(encoding="utf-8"))


def save_task(task_id: str, meta: dict[str, Any]) -> None:
    validate_task_id(task_id)
    with task_lifecycle_lock(task_id):
        directory = task_dir(task_id)
        if not directory.exists():
            raise FileNotFoundError(f"Task not found: {task_id}")
        meta["task_id"] = task_id
        meta["last_activity_at"] = _now()
        _write_meta(directory, meta)


def summarize_task(meta: dict[str, Any]) -> dict[str, Any]:
    """Project a task's metadata into a stable list/show summary.

    ``created_at`` and ``last_activity_at`` are carried through so callers can
    sort the returned list deterministically (newest activity first) without
    reloading the raw metadata.
    """
    return {
        "task_id": meta.get("task_id"),
        "original_filename": meta.get("original_filename"),
        "text_count": meta.get("text_count", 0),
        "translation_count": meta.get("translation_count", 0),
        "excel_filename": meta.get("excel_filename"),
        "translated_cad_filename": meta.get("translated_cad_filename"),
        "status": meta.get("status"),
        "stage": meta.get("stage"),
        "created_at": meta.get("created_at"),
        "last_activity_at": meta.get("last_activity_at"),
        "output_dir": meta.get("output_dir"),
        "output_file": meta.get("output_file"),
    }


def list_tasks() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    root = tasks_root()
    if not root.exists():
        return items
    for directory in root.iterdir():
        if not directory.is_dir() or not is_valid_task_id(directory.name):
            continue
        meta_path = directory / "task.json"
        if not meta_path.exists():
            continue
        try:
            with task_lifecycle_lock(directory.name):
                if meta_path.exists():
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    items.append(summarize_task(meta))
        except (json.JSONDecodeError, OSError, FileNotFoundError):
            # Concurrent writer mid-update or a task deleted while iterating.
            continue
    items.sort(
        key=lambda item: -(item.get("last_activity_at") or item.get("created_at") or 0)
    )
    return items


def delete_task(task_id: str) -> None:
    validate_task_id(task_id)
    with task_create_or_clear_lock():
        with task_lifecycle_lock(task_id):
            directory = task_dir(task_id)
            if not directory.exists():
                raise FileNotFoundError(f"Task not found: {task_id}")
            _delete_tree(directory)


def clear_tasks() -> None:
    with task_create_or_clear_lock():
        root = tasks_root()
        if not root.exists():
            return
        # Delete every per-task directory while holding its lifecycle lock so a
        # concurrent writer cannot be mid-write when its dir is removed.
        for child in list(root.iterdir()):
            if child.is_dir() and is_valid_task_id(child.name):
                with task_lifecycle_lock(child.name):
                    if child.exists():
                        _delete_tree(child)
            elif child.is_dir():
                # Stable non-task children under the tasks root are reclaimed too.
                _delete_tree(child)


# ---------------------------------------------------------------------------
# Project file helpers (path-safe, atomic)
# ---------------------------------------------------------------------------
def write_project_file(data: dict[str, Any], output_path: str | Path) -> dict[str, Any]:
    """Write a project JSON file atomically, refusing paths outside cwd/output."""
    path = Path(output_path).expanduser()
    # Guard against accidental traversal outside a usable project directory.
    safe_dir = Path.cwd()
    try:
        resolved = resolve_within_directory(safe_dir, path)
    except ValueError:
        # An absolute path is acceptable for a project file, but still require
        # a sane extension and parent creation under an explicit directory.
        resolved = path.resolve()
    if resolved.suffix.lower() != ".json":
        resolved = resolved.with_suffix(".json")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(resolved, data)
    return {"success": True, "file": str(resolved), "project": data.get("name")}


def load_project_file(project_path: str | Path) -> dict[str, Any]:
    path = Path(project_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Project file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Project file is not valid JSON: {path}") from exc
