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

class CadTaskStorageMixin:
    def _task_index(self):
        from app.services.cad_task_index import CadTaskIndex
        root = self._tasks_root()
        with self._index_lock:
            if root not in self._task_indexes:
                self._task_indexes[root] = CadTaskIndex(root, self._build_task_summary)
            return self._task_indexes[root]

    def _index_task(self, payload, metadata_path):
        if "task_id" not in payload or "original_filename" not in payload:
            return
        try:
            self._task_index().upsert(payload, metadata_path)
        except Exception as exc:
            # Derived data must not invalidate an already durable task write.
            self._task_index().dirty.touch()
            logger.warning("task_index_write_failed", task_id=payload.get("task_id"), error=str(exc))

    def _tasks_root(self) -> Path:
        tasks_root = self.settings.get_output_path() / "cad_tasks"
        tasks_root.mkdir(parents=True, exist_ok=True)
        return tasks_root

    def _task_dir(self, task_id: str) -> Path:
        validate_task_id(task_id)  # reject path-like / non-system ids (defence in depth)
        return self._tasks_root() / task_id

    def _lifecycle_root(self) -> Path:
        """Stable directory for per-task lifecycle locks.

        Lives as a sibling of ``cad_tasks/`` under the output root so that
        ``delete_task`` / ``clear_all_tasks`` never remove it.  File locks
        held here provide a coordination point *outside* the task tree: both
        task write operations and task deletion acquire the same per-task
        lifecycle lock, preventing a delete from racing a writer's
        check-exists→lock→write sequence and closing the TOCTOU window.
        """
        root = self.settings.get_output_path() / "cad_task_lifecycle"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _lifecycle_lock_path(self, task_id: str) -> Path:
        """Return the per-task lifecycle lock file path (outside task tree)."""
        validate_task_id(task_id)  # reject path-like / non-system ids (defence in depth)
        return self._lifecycle_root() / f"{task_id}.lifecycle"

    @contextlib.contextmanager
    def _task_lifecycle_lock(self, task_id: str) -> Iterator[None]:
        """Acquire the per-task lifecycle lock.

        Both writers (``_save_task``/``_update_task``/``_append_log``/
        ``_save_checkpoint``) and deleters (``delete_task``/``clear_all_tasks``)
        hold this lock while operating on a task directory, so a delete cannot
        happen between a writer's ``exists()`` check and its file-level lock
        acquisition inside the task tree.
        """
        lock_path = self._lifecycle_lock_path(task_id)
        with file_lock(lock_path):
            yield

    def _cleanup_lifecycle_lock(self, task_id: str) -> None:
        """Intentionally NO-OP: per-task lifecycle lock files are retained.

        Deleting ``<task>.lifecycle`` / ``<task>.lifecycle.lock`` while another
        process may still hold or be waiting on them would destroy the lock's
        inode and let a later acquirer create a fresh lock object at the same
        path — splitting lock identity so two processes believe they hold the
        same "task lock" while actually guarding different inodes.  Keeping the
        stable lifecycle lock files guarantees exactly one lock object exists
        per task_id for its lifetime, which is what makes per-task lifecycle
        coordination safe against cross-process clear/delete races.

        The lifecycle files are empty coordination markers in the stable
        ``cad_task_lifecycle/`` sibling directory; they are never removed by
        task deletion or ``clear_all_tasks`` and impose negligible overhead.
        """
        # Deliberately do nothing: lifecycle lock files are retained so lock
        # identity stays stable.  Task directories and external cancel markers
        # are the only things removed by delete/clear.
        return

    def _global_coord_lock_path(self) -> Path:
        """Stable global coordination lock file (in lifecycle root)."""
        return self._lifecycle_root() / "_task_create_or_clear.coord"

    @contextlib.contextmanager
    def _task_create_or_clear_lock(self) -> Iterator[None]:
        """Hold the global task-creation/clear coordination lock.

        Mutual exclusion between the *registration* of a new task
        (``extract_upload`` critical region) and ``clear_all_tasks``.  This
        guarantees that:

          1. A task whose creation begins before a clear is fully registered
             (directory + task.json present) before the clear may proceed, so
             it can never escape a clear that started after it nor be deleted
             mid-creation;
          2. A clear that begins first completes (deletes every existing task
             and cleans every cancel marker) before any new task creation may
             start, so no upload writes into a directory being cleared and no
             newly created task's marker is swept by the clear's Phase 3.
        """
        lock_path = self._global_coord_lock_path()
        with file_lock(lock_path):
            yield

    def _cancel_marks_root(self) -> Path:
        """Stable directory for cross-process cancellation markers.

        This lives *outside* ``cad_tasks/`` so ``delete_task`` /
        ``clear_all_tasks`` never remove it.  A running worker that finishes
        after its task directory was deleted can therefore clean up its own
        marker here without recreating the task dir (which would happen if
        the marker lived inside the task directory and ``file_lock`` called
        ``sidecar.parent.mkdir`` on a deleted path).
        """
        root = self.settings.get_output_path() / "cad_cancel_marks"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _cancel_marker_path(self, task_id: str) -> Path:
        """Return the external cancellation marker for ``task_id``."""
        validate_task_id(task_id)  # reject path-like / non-system ids (defence in depth)
        return self._cancel_marks_root() / f"{task_id}.cancel"

    def _is_task_cancelled(self, task_id: str) -> bool:
        """Cross-process cancellation check.

        Returns True if:
        1. An external `.cancel` marker exists for this task, OR
        2. The task directory or task.json no longer exists (deleted by
           `delete_task` / `clear_all_tasks` while a worker was still running).

        Case (2) is critical: after a task is deleted, a running worker must
        treat it as cancelled rather than re-create orphaned files.
        """
        # External cancel marker (never deleted by task cleanup).
        marker = self._cancel_marker_path(task_id)
        if marker.exists():
            return True
        # Check whether the task itself still exists.  If the task directory
        # or task.json was removed, the task is considered cancelled.
        task_dir = self._tasks_root() / task_id
        meta_path = self._task_meta_path(task_id)
        if not task_dir.exists() or not meta_path.exists():
            return True
        return False

    def _mark_task_cancelled(self, task_id: str) -> None:
        """Write an external cancellation marker for ``task_id``.

        Never creates the task directory.  Uses the external cancel-marks
        directory (a sibling of ``cad_tasks/``) so a deleted task dir is not
        recreated by file_lock's parent.mkdir side effect.
        """
        if not task_id:
            return
        marker = self._cancel_marker_path(task_id)
        # file_lock creates the sidecar parent (the cancel_marks root), which
        # is a stable path never removed by task delete/clear.
        with file_lock(marker):
            marker.touch()

    def _clear_task_cancel(self, task_id: str) -> None:
        """Remove the external cancellation marker for ``task_id``.

        Never creates the task directory.  If the marker root does not exist
        or the marker is already gone, this is a no-op.
        """
        if not task_id:
            return
        marker = self._cancel_marker_path(task_id)
        if not marker.parent.exists():
            return
        with file_lock(marker):
            marker.unlink(missing_ok=True)

    def _task_excel_path(self, task_id: str, metadata: dict[str, Any] | None = None) -> Path:
        metadata = metadata or self._load_task(task_id)
        excel_filename = metadata.get("excel_filename")
        if not excel_filename:
            raise FileNotFoundError(f"Excel is missing for task {task_id}")
        return self._task_dir(task_id) / excel_filename

    def _write_translated_excel(self, task_id: str, translation_map: dict[str, str], record_translations=None) -> Path:
        if not translation_map and not record_translations:
            raise ValueError("No translations were provided for Excel backfill.")

        metadata = self._load_task(task_id)
        excel_path = self._task_excel_path(task_id, metadata)
        if not excel_path.exists():
            raise FileNotFoundError(f"Excel is missing for task {task_id}: {excel_path.name}")

        df = pd.read_excel(excel_path)
        if "原文" not in df.columns:
            raise ValueError(f"Excel for task {task_id} does not contain a 原文 column.")

        if "译文" not in df.columns:
            df["译文"] = ""

        def _translate_cell(value: Any) -> str:
            original = str(value or "").strip()
            if not original:
                return ""
            return translation_map.get(original, "")

        df["译文"] = [
            (record_translations or {}).get(f"{task_id}_{index}", _translate_cell(value))
            for index, value in enumerate(df["原文"].fillna(""))
        ]
        translated_excel_path = excel_path.with_name(f"translated_{excel_path.name}")
        df.to_excel(translated_excel_path, index=False, engine="openpyxl")
        self._update_task(
            task_id,
            translated_excel_filename=translated_excel_path.name,
            last_activity_at=time.time(),
        )
        return translated_excel_path

    def _task_meta_path(self, task_id: str) -> Path:
        return self._task_dir(task_id) / "task.json"

    def _task_log_path(self, task_id: str) -> Path:
        return self._task_dir(task_id) / "task.log"

    def _task_checkpoint_path(self, task_id: str) -> Path:
        return self._task_dir(task_id) / "translations_checkpoint.json"

    def _append_log(self, task_id: str, message: str) -> None:
        """Append a line to the task log.

        If the task directory no longer exists (e.g. it was deleted by a
        concurrent ``delete_task`` / ``clear_all_tasks``), writing is skipped
        so no orphan files are re-created.

        The task lifecycle lock (outside the task tree) is held for the whole
        exists→lock→append sequence so a concurrent delete cannot slip into
        the TOCTOU gap.  ``file_lock(..., create_parents=False)`` additionally
        guarantees the sidecar lock cannot recreate a deleted task directory.
        """
        if not task_id:
            return
        log_path = self._task_log_path(task_id)
        with self._task_lifecycle_lock(task_id):
            if not log_path.parent.exists():
                return
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            try:
                with file_lock(log_path, create_parents=False):
                    if not log_path.parent.exists():
                        return
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(f"[{timestamp}] {message}\n")
                        f.flush()
            except FileNotFoundError:
                return  # Task dir deleted concurrently.

    def _save_checkpoint(self, task_id: str, translations: list[dict[str, str]]) -> None:
        """Save translation checkpoint to disk.

        If the task directory no longer exists (deleted concurrently), writing
        is skipped so no orphan checkpoint file is created.

        The task lifecycle lock protects the full exists→lock→write sequence
        from a concurrent delete/clear; ``create_parents=False`` prevents the
        checkpoint sidecar from recreating a deleted task directory.
        """
        if not task_id:
            return
        checkpoint_path = self._task_checkpoint_path(task_id)
        with self._task_lifecycle_lock(task_id):
            if not checkpoint_path.parent.exists():
                return
            try:
                # Cross-process + in-process lock on the checkpoint file's sidecar.
                with file_lock(checkpoint_path, create_parents=False):
                    atomic_write_json(checkpoint_path, translations, create_parents=False)
            except FileNotFoundError:
                pass  # Task dir deleted concurrently.

    def _load_checkpoint(self, task_id: str) -> list[dict[str, str]]:
        checkpoint_path = self._task_checkpoint_path(task_id)
        if not checkpoint_path.exists():
            return []
        # Cross-process + in-process lock on the checkpoint file's sidecar.
        # create_parents=False: never recreate a deleted task dir.
        try:
            with file_lock(checkpoint_path, create_parents=False):
                with open(checkpoint_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except FileNotFoundError:
            return []  # Task dir deleted concurrently — no checkpoint.

    def _load_task(self, task_id: str) -> dict[str, Any]:
        metadata_path = self._task_meta_path(task_id)
        if not metadata_path.exists():
            raise FileNotFoundError(f"Task not found: {task_id}")
        # Use a cross-process file lock so concurrent readers see a consistent
        # snapshot even when a writer in another process is mid-update.
        # create_parents=False: if the dir vanished between the exists check
        # and the lock acquisition, the lock must NOT recreate it.
        with file_lock(metadata_path, create_parents=False):
            return json.loads(metadata_path.read_text(encoding="utf-8"))

    def _save_task(self, task_id: str, payload: dict[str, Any]) -> None:
        """Atomically persist task metadata.

        If the task directory no longer exists (deleted concurrently by
        ``delete_task`` / ``clear_all_tasks``), writing is skipped so no
        orphan task.json is created in a re-created directory.

        The task lifecycle lock (outside the task tree) coordinates the full
        exists→lock→write sequence with ``delete_task`` / ``clear_all_tasks``,
        closing the TOCTOU window. ``create_parents=False`` on both the sidecar
        file lock and the atomic write guarantees a deleted task dir is never
        re-created even if the delete races between the checks.
        """
        if not task_id:
            return
        metadata_path = self._task_meta_path(task_id)
        with self._task_lifecycle_lock(task_id):
            if not metadata_path.parent.exists():
                return
            try:
                # Atomic write prevents readers from seeing a truncated/partial JSON.
                # Cross-process file lock protects against concurrent multi-process writes.
                with file_lock(metadata_path, create_parents=False):
                    atomic_write_json(metadata_path, payload, create_parents=False)
                    self._index_task(payload, metadata_path)
            except FileNotFoundError:
                pass  # Task dir deleted concurrently — skip write.

    def _update_task(self, task_id: str, **patch: Any) -> dict[str, Any]:
        """Update task metadata via guarded read-modify-write.

        If the task directory no longer exists (e.g. deleted concurrently by
        ``delete_task`` / ``clear_all_tasks``), returns the empty dict and
        does NOT create any files — avoids re-creating orphan task dirs.

        The task lifecycle lock coordinates the full exists→lock→RMW→write
        sequence with ``delete_task`` / ``clear_all_tasks``, preventing a
        delete from landing in the TOCTOU gap between the ``exists()`` check
        and the file-level lock acquisition.
        """
        if not task_id:
            return {}
        metadata_path = self._task_meta_path(task_id)
        with self._task_lifecycle_lock(task_id):
            # Guard before acquiring file_lock: if the task dir is gone, do not
            # let file_lock's sidecar parent.mkdir recreate it.
            if not metadata_path.parent.exists():
                return {}
            try:
                # Serialize read-modify-write on the task metadata file so
                # concurrent updates (including from other processes) don't
                # clobber each other.  file_lock is re-entrant, so _load_task /
                # _save_task nested inside this block won't deadlock within
                # the same thread.
                with file_lock(metadata_path, create_parents=False):
                    metadata = self._load_task(task_id)
                    metadata.update(patch)
                    metadata["last_activity_at"] = time.time()
                    self._save_task(task_id, metadata)
                    return metadata
            except FileNotFoundError:
                return {}  # Task dir deleted concurrently — skip update.
