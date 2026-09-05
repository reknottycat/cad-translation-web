from __future__ import annotations

import contextlib
import json
import os
import re
import stat
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from tempfile import mkdtemp, mkstemp
from typing import Any, Callable, Iterator

import structlog
import pandas as pd
from fastapi import UploadFile

from app.config import get_settings
from app.services.cad_text_processor import cad_text_processor
from app.services.alibaba_ai_translation_service import alibaba_ai_translation_service
from app.services.docutranslate_adapter import CadTextRecord, DocuTranslateConfig, DocuTranslateJsonAdapter
from app.utils.file_utils import get_safe_filename, resolve_within_directory
from app.utils.locking import atomic_write_json, atomic_write_text, file_lock
from app.workflow.pipeline import CADPipeline, get_pipeline
from app.functions.dwg_converter import DWGConverter
from app.functions.text_extractor import TextExtractor
from app.functions.text_applier import TextApplier

logger = structlog.get_logger(__name__)
from app.services.cad_task_types import TaskCancelledError, validate_task_id, is_valid_task_id
from app.services.cad_task_jobs import task_execution

class CadTaskArtifactsMixin:
    def _packages_root(self) -> Path:
        packages_root = self.settings.get_output_path() / "cad_downloads"
        packages_root.mkdir(parents=True, exist_ok=True)
        return packages_root

    def _archive_name(self, value: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", ".", " "} else "_" for ch in value).strip()
        return cleaned or "task"

    def _handle_remove_readonly(self, func, path: str, exc_info) -> None:
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            raise exc_info[1]

    def _delete_tree(self, path: Path) -> None:
        last_error: OSError | None = None
        for attempt in range(5):
            try:
                shutil.rmtree(path, onerror=self._handle_remove_readonly)
                if is_valid_task_id(path.name) and path.parent == self._tasks_root():
                    try:
                        self._task_index().discard(path.name)
                    except Exception as exc:
                        self._task_index().dirty.touch()
                        logger.warning("task_index_delete_failed", task_id=path.name, error=str(exc))
                return
            except OSError as exc:
                last_error = exc
                time.sleep(0.5 * (attempt + 1))

        raise PermissionError(
            f"Task directory is still in use. Close related CAD/ODA windows and retry: {path}"
        ) from last_error

    def _build_task_summary(self, metadata: dict[str, Any]) -> dict[str, Any]:
        task_id = metadata["task_id"]
        inferred_status = str(metadata.get("status") or "").strip().lower()
        inferred_stage = str(metadata.get("stage") or "").strip().lower()
        last_error = str(metadata.get("last_error") or "").strip().lower()
        failed_count = int(metadata.get("failed_count") or 0)
        if "cancelled by user" in last_error or "stopped by user" in last_error:
            inferred_status = "cancelled"
            inferred_stage = "cancelled"
        if not inferred_status:
            if metadata.get("translated_cad_filename"):
                inferred_status = "done"
            elif metadata.get("excel_filename"):
                inferred_status = "processing"
            else:
                inferred_status = "queued"
        # Infer partial status from failed_count if not already set
        if failed_count > 0 and inferred_status == "done" and inferred_stage == "completed":
            inferred_status = "partial"
        if not inferred_stage:
            if inferred_status == "done":
                inferred_stage = "completed"
            elif inferred_status == "partial":
                inferred_stage = "completed"
            elif inferred_status == "processing":
                inferred_stage = "translating"
            elif inferred_status == "cancelled":
                inferred_stage = "cancelled"
            elif inferred_status == "error":
                inferred_stage = "failed"
            else:
                inferred_stage = "queued"
        if (metadata.get("resume_queued") or metadata.get("job_queued")) and inferred_status != "cancelled":
            inferred_status, inferred_stage = "queued", "queued"
        if metadata.get("cancellation_requested") and metadata.get("owner_pid"):
            inferred_stage = "stopping"
        return {
            "task_id": task_id,
            "project_id": metadata.get("project_id"),
            "original_filename": metadata["original_filename"],
            "target_language": metadata.get("target_language", "en"),
            "extract_only": metadata.get("extract_only", False),
            "status": inferred_status,
            "stage": inferred_stage,
            "processing_time": metadata.get("processing_time", "0.0s"),
            "text_count": metadata.get("text_count", 0),
            "translatable_count": metadata.get("translatable_count", metadata.get("translation_count", 0)),
            "translation_count": metadata.get("translation_count", 0),
            "translated_count": metadata.get("translated_count", metadata.get("translation_count", 0)),
            "failed_count": failed_count,
            "total_chunks": metadata.get("total_chunks", 0),
            "completed_chunks": metadata.get("completed_chunks", 0),
            "current_chunk": metadata.get("current_chunk", 0),
            "provider": metadata.get("provider", ""),
            "model": metadata.get("model", ""),
            "batch_size": metadata.get("batch_size", 0),
            "retry_count": metadata.get("retry_count", 0),
            "last_error": metadata.get("last_error", ""),
            "last_activity_at": metadata.get("last_activity_at"),
            "created_at": metadata.get("created_at"),
            "files": {
                "excel_file": f"/api/cad/download/{task_id}/excel" if metadata.get("excel_filename") else None,
                "translated_cad_file": (
                    f"/api/cad/download/{task_id}/translated_cad"
                    if metadata.get("translated_cad_filename")
                    else None
                ),
                "log_file": f"/api/cad/download/{task_id}/log",
            },
        }

    def get_task_logs(self, task_id: str) -> str:
        validate_task_id(task_id)
        log_path = self._task_log_path(task_id)
        if log_path.exists():
            # Acquire the same cross-process file lock used by _append_log
            # so we get a consistent snapshot even mid-write.  create_parents=False
            # ensures a deleted task dir is not re-created by the sidecar mkdir.
            try:
                with file_lock(log_path, create_parents=False):
                    if log_path.exists():
                        return log_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                pass  # Task dir deleted concurrently — fall through.
        # Fallback: return task metadata as pseudo-log for old tasks.
        # Uses _load_task which acquires the cross-process file lock.
        metadata = self._load_task(task_id)  # raises FileNotFoundError if absent
        lines = [f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(metadata.get('created_at', 0)))}] 任务创建"]
        lines.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(metadata.get('last_activity_at', 0)))}] 最后活动: stage={metadata.get('stage')}, status={metadata.get('status')}")
        if metadata.get("last_error"):
            lines.append(f"错误: {metadata['last_error']}")
        return "\n".join(lines)

    def list_tasks(self) -> list[dict[str, Any]]:
        try:
            return self._task_index().page(limit=None)["data"]
        except Exception as exc:
            logger.warning("task_index_read_failed_using_manifests", error=str(exc))
            return self._scan_task_summaries()

    def _scan_task_summaries(self) -> list[dict[str, Any]]:
        """Read changed manifests only; file signatures also detect other workers' writes."""
        tasks: list[dict[str, Any]] = []
        discovered = set()
        for metadata_path in self._tasks_root().glob("*/task.json"):
            task_id = metadata_path.parent.name
            if not is_valid_task_id(task_id):
                continue
            discovered.add(task_id)
            try:
                stat_result = metadata_path.stat()
                signature = (stat_result.st_mtime_ns, stat_result.st_size, stat_result.st_ino)
                with self._summary_cache_lock:
                    cached = self._summary_cache.get(task_id)
                if cached and cached[0] == signature:
                    summary = dict(cached[1])
                else:
                    # Writers publish with atomic replace. A list snapshot may
                    # see the old or new complete record; it needs no write lock.
                    # Avoid creating/acquiring thousands of sidecar locks on a
                    # cold list. The next poll detects any concurrent replacement.
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    if metadata.get("task_id") != task_id:
                        raise ValueError("Task manifest ID does not match its directory")
                    summary = self._build_task_summary(metadata)
                    with self._summary_cache_lock:
                        if len(self._summary_cache) >= 5000 and task_id not in self._summary_cache:
                            self._summary_cache.pop(next(iter(self._summary_cache)))
                        self._summary_cache[task_id] = (signature, summary)
                tasks.append(dict(summary))
            except (json.JSONDecodeError, OSError, ValueError, KeyError, TypeError) as exc:
                logger.warning("task_meta_read_skipped", task_id=task_id, error=str(exc))
        with self._summary_cache_lock:
            for task_id in self._summary_cache.keys() - discovered:
                self._summary_cache.pop(task_id, None)
        status_rank = {"processing": 0, "queued": 1, "partial": 2, "error": 3, "cancelled": 4, "done": 5}
        tasks.sort(key=lambda item: (status_rank.get(item["status"], 9),
                                    -(item.get("last_activity_at") or item.get("created_at") or 0)))
        return tasks

    def clear_all_tasks(self) -> None:
        """Clear all tasks by removing every task directory.

        Cross-process safe: we first mark each discovered task as cancelled by
        writing external ``.cancel`` markers (in the stable
        ``cad_cancel_marks/`` directory), then remove each task directory
        *while holding that task's per-task lifecycle lock*.  Writers
        (``_save_task`` / ``_update_task`` / ``_append_log`` /
        ``_save_checkpoint``) hold the same per-task lifecycle lock for their
        entire exists→lock→write sequence, so no writer can be mid-operation
        when its directory is removed — closing the previous TOCTOU where the
        lock was acquired momentarily (``with ...: pass``) and released before
        the whole tree was removed, letting a writer slip back in between.

        The per-task lifecycle lock files live in the stable sibling directory
        ``cad_task_lifecycle/`` (outside ``cad_tasks/``) and are intentionally
        **retained** after deletion so that exactly one lock object exists per
        task_id for its lifetime.  Unlinking them under another process's feet
        would split lock identity (two different lock objects protecting the
        same task), which is why no ``*.lifecycle`` / ``*.lifecycle.lock`` file
        is ever deleted here.

        The *entire* operation — Phase 1 cancel-marking, Phase 2
        enumeration/deletion, and Phase 3 marker cleanup — runs under the
        **global creation/clear coordination lock** shared with
        ``extract_upload``.  This closes the remaining concurrency gap where a
        task created concurrently with a clear could escape the clear's
        enumeration (its ``task_dir.mkdir()`` happened after Phase 2's snapshot)
        or an in-flight upload could keep writing into a directory the clear was
        deleting.  Because creation and clear are mutually exclusive:

          * if a task's upload already holds the coordination lock, this clear
            waits until that task is fully registered, then deletes it with the
            rest (no task escapes the clear);
          * if this clear already holds the lock, no new upload may start until
            every task directory is removed and every cancel marker is cleaned,
            so no upload writes into a cleared directory and no newly created
            task's marker is swept by Phase 3.

        Parallel processing of already-registered tasks (translation etc.) uses
        only per-task lifecycle locks and is *not* serialized by this clear.
        """
        with self._task_create_or_clear_lock():
            tasks_root = self._tasks_root()
            cancel_root = self._cancel_marks_root()

            # Phase 1: mark all currently-discoverable tasks as cancelled so any
            # running worker stops writing before we delete.
            if tasks_root.exists():
                for metadata_path in tasks_root.glob("*/task.json"):
                    task_id = metadata_path.parent.name
                    if not is_valid_task_id(task_id):
                        continue
                    try:
                        self._mark_task_cancelled(task_id)
                    except OSError:
                        pass  # Already deleted or locked by another process.

            # Phase 2: remove each task directory *while holding* its per-task
            # lifecycle lock.  Enumerate by directory name (not just `*/task.json`)
            # so partial / mid-creation task directories are also reclaimed under
            # their lock.  A writer in another process that holds (or is waiting
            # for) the same lifecycle lock is thereby serialized with the delete —
            # it either finishes writing before we delete, or acquires the lock
            # after the directory is already gone and skips (task_dir.exists()==False).
            if tasks_root.exists():
                # Only treat sub-directories whose name is a system-generated
                # task id as tasks to clear.  Skip stable non-task children
                # (e.g. ``_packages``) which are never per-task directories and
                # whose names would not pass the centralised ``validate_task_id``.
                task_ids = sorted(
                    child.name
                    for child in tasks_root.iterdir()
                    if child.is_dir() and is_valid_task_id(child.name)
                )
                for task_id in task_ids:
                    task_dir = self._tasks_root() / task_id
                    try:
                        with self._task_lifecycle_lock(task_id):
                            # Re-mark under the lock (covers partial tasks) so a
                            # mid-flight worker still sees cancellation even if it
                            # only grabs the lock after we release it.
                            try:
                                self._mark_task_cancelled(task_id)
                            except OSError:
                                pass
                            if task_dir.exists():
                                self._delete_tree(task_dir)
                    except (OSError, FileNotFoundError):
                        pass  # Task already gone or lifecycle dir unavailable.

            # Remove any leftover stray non-directory files (e.g. interrupted
            # atomic-write temp files) in the root; task directories were already
            # removed above under their lifecycle locks.
            if tasks_root.exists():
                for child in list(tasks_root.iterdir()):
                    try:
                        if not child.is_dir():
                            child.unlink(missing_ok=True)
                    except OSError:
                        pass
            # Recreate the root directory to ensure it exists for future tasks.
            tasks_root.mkdir(parents=True, exist_ok=True)

            # Phase 3: clean up all external cancellation markers now that all task
            # directories are gone and any worker has observed the deletion.  No
            # new task can be created concurrently (we hold the coordination lock),
            # so this never sweeps a freshly-created task's marker.
            if cancel_root.exists():
                for marker in cancel_root.glob("*.cancel"):
                    try:
                        marker.unlink(missing_ok=True)
                    except OSError:
                        pass

    def delete_task(self, task_id: str) -> None:
        validate_task_id(task_id)
        task_dir = self._task_dir(task_id)
        with self._task_lifecycle_lock(task_id):
            if not task_dir.exists():
                raise FileNotFoundError(f"Task not found: {task_id}")
            # Mark as cancelled first so any running worker in another process
            # stops writing before we delete the directory.
            try:
                metadata = self._load_task(task_id)
                status = str(metadata.get("status") or "").strip().lower()
                if status in {"processing", "queued"}:
                    self._mark_task_cancelled(task_id)
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                pass  # Task may already be gone; still attempt deletion.
            self._delete_tree(task_dir)
        # Clean up only the external cancellation marker after the directory is
        # gone (outside the lifecycle lock).  The per-task lifecycle lock file
        # is intentionally retained so its inode (and lock identity) stays
        # stable: a writer that acquires the same lifecycle lock right after we
        # release it must find the *same* lock object, not a re-created one.
        self._clear_task_cancel(task_id)

    def stop_all_tasks(self) -> dict[str, Any]:
        """Cancel every currently-active task (status in {processing, queued}).

        Lock-order invariant: this method (like every writer and like
        ``delete_task`` / ``clear_all_tasks``) acquires the **per-task
        lifecycle lock FIRST**, then takes the task.json file lock *nested*
        inside it via ``_load_task`` / ``_save_task``.  Historically this
        method held the task.json file lock and then called ``_save_task``
        (which acquires the lifecycle lock) — inverting the ordering to
        file → lifecycle.  That created a cross-process deadlock with
        ``delete_task`` / ``_update_task`` (which take lifecycle → file):
        two processes could wait on each other forever:

          * process A: holds file_lock(task.json), wants lifecycle lock
          * process B: holds lifecycle lock, wants file_lock(task.json)

        Holding the lifecycle lock first and performing the read-modify-write
        only through ``_load_task`` / ``_save_task`` (whose file_lock on
        task.json is re-entrant and strictly nested) restores the single
        lifecycle → file_lock ordering and preserves cross-process
        read-modify-write atomicity on task.json.  It also closes the window
        where a concurrent delete could remove the task dir mid-write.
        """
        cancelled_task_ids: list[str] = []
        tasks_root = self._tasks_root()
        if not tasks_root.exists():
            return {"cancelled_task_ids": cancelled_task_ids, "cancelled_count": 0}
        for metadata_path in tasks_root.glob("*/task.json"):
            task_id = metadata_path.parent.name
            if not is_valid_task_id(task_id):
                continue
            meta_path = self._task_meta_path(task_id)
            try:
                # Acquire the per-task lifecycle lock first; the task.json
                # file lock is taken re-entrantly by _load_task/_save_task
                # underneath it, matching the lifecycle → file ordering used
                # by delete_task / clear_all_tasks and every writer.
                with self._task_lifecycle_lock(task_id):
                    if not meta_path.parent.exists():
                        continue  # Task dir deleted concurrently.
                    metadata = self._load_task(task_id)  # nested file_lock
                    status = str(metadata.get("status") or "").strip().lower()
                    if status not in {"processing", "queued"} and not metadata.get("resume_queued"):
                        continue
                    # File-based cross-process cancellation marker.
                    self._mark_task_cancelled(task_id)
                    metadata["status"] = "cancelled"
                    metadata["stage"] = "cancelled"
                    metadata["last_error"] = "Task cancelled by user."
                    metadata["cancellation_requested"] = True
                    metadata["last_activity_at"] = time.time()
                    self._save_task(task_id, metadata)  # nested lifecycle+file_lock
                    cancelled_task_ids.append(task_id)
            except (json.JSONDecodeError, OSError, FileNotFoundError) as exc:
                logger.warning("stop_task_meta_skipped", task_id=task_id, error=str(exc))
                continue
        return {
            "cancelled_task_ids": cancelled_task_ids,
            "cancelled_count": len(cancelled_task_ids),
        }

    def resolve_download(self, task_id: str, file_type: str) -> tuple[Path, str]:
        validate_task_id(task_id)
        metadata = self._load_task(task_id)
        task_dir = self._task_dir(task_id)

        if file_type == "excel":
            filename = metadata.get("translated_excel_filename") or metadata.get("excel_filename")
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif file_type in {"cad", "translated_cad"}:
            filename = metadata.get("translated_cad_filename")
            media_type = "application/octet-stream"
        elif file_type == "log":
            # Prefer real task.log if exists, fallback to task.json for old tasks
            log_path = task_dir / "task.log"
            if log_path.exists():
                filename = "task.log"
                media_type = "text/plain; charset=utf-8"
            else:
                filename = "task.json"
                media_type = "application/json"
        else:
            raise ValueError(f"Unsupported file type: {file_type}")

        if not filename:
            raise FileNotFoundError(f"{file_type} is not available for task {task_id}")

        file_path = resolve_within_directory(task_dir, filename)
        if not file_path.exists():
            raise FileNotFoundError(f"Missing artifact for task {task_id}: {filename}")
        return file_path, media_type
