"""Bounded local execution and short durable task registration.

Task timestamps describe events already observed (no future state is inferred).
The existing task manifest is the canonical record for Web and CLI CAD jobs.
"""
from __future__ import annotations

import contextlib
import functools
import os
import shutil
import threading
import time
import uuid
import tempfile
import zipfile
import psutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterator

from fastapi import UploadFile

from app.utils.file_utils import get_safe_filename, resolve_within_directory
from app.utils.locking import file_lock


class TaskBusyError(RuntimeError):
    """The task already has an executor or the bounded queue is full."""


def task_execution(method):
    @functools.wraps(method)
    def execute(self, task_id, *args, **kwargs):
        with self._task_execution_claim(task_id):
            self._reject_live_queue(task_id)
            return method(self, task_id, *args, **kwargs)
    return execute


_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cad-job")
_capacity = threading.BoundedSemaphore(18)
_PROCESS_STARTED = psutil.Process().create_time()


class TaskJobsMixin:
    @staticmethod
    def _owner_alive(metadata):
        try:
            owner = psutil.Process(int(metadata.get("owner_pid") or 0))
            return owner.create_time() == metadata.get("owner_started") and owner.is_running()
        except (psutil.Error, ValueError):
            return False

    def recover_interrupted_jobs(self):
        """Mark abandoned work recoverable without automatically making new model calls."""
        try:
            candidates = self._task_index().active_ids()
        except Exception:
            candidates = [item["task_id"] for item in self._scan_task_summaries()
                          if item["status"] in {"queued", "processing"}]
        for task_id in candidates:
            try:
                with self._task_execution_claim(task_id):
                    metadata = self._load_task(task_id)
                    if metadata.get("status") not in {"processing", "queued"} and not metadata.get("resume_queued"):
                        continue
                    if self._owner_alive(metadata):
                        continue
                    self._update_task(task_id, job_queued=False, resume_queued=False, owner_pid=None,
                                      status="error", stage="interrupted",
                                      last_error="Worker stopped. Resume to continue from saved input and translations.")
            except (TaskBusyError, OSError, ValueError):
                continue

    def _reject_live_queue(self, task_id):
        try:
            metadata = self._load_task(task_id)
        except FileNotFoundError:
            return  # Preserve each operation's existing missing/deleted contract.
        if not (metadata.get("job_queued") or metadata.get("resume_queued")):
            return
        if self._owner_alive(metadata):
            raise TaskBusyError(f"Task {task_id} is already queued; follow its status.")
        self._update_task(task_id, job_queued=False, resume_queued=False, owner_pid=None,
                          status="error", stage="interrupted",
                          last_error="Worker stopped. Resume the task to continue from saved input.")

    @contextlib.contextmanager
    def _task_execution_claim(self, task_id: str) -> Iterator[None]:
        from app.services.cad_task_types import validate_task_id
        task_id = validate_task_id(task_id)
        lock = file_lock(self._lifecycle_root() / f"{task_id}.execution", blocking=False)
        try:
            lock.__enter__()
        except TimeoutError as exc:
            raise TaskBusyError(f"Task {task_id} is already running; follow its status.") from exc
        try:
            yield
        finally:
            lock.__exit__(None, None, None)

    def reserve_upload(self, uploaded_file: UploadFile, target_language="en", converter_backend=None):
        if not uploaded_file.filename:
            raise ValueError("CAD filename is required")
        name = get_safe_filename(uploaded_file.filename)
        if Path(name).suffix.lower() not in {".dwg", ".dxf"}:
            raise ValueError("Only DWG and DXF files are supported")
        # The global lock covers only registration. Heavy work uses the task lock.
        with self._task_create_or_clear_lock():
            while True:
                task_id = uuid.uuid4().hex[:8]
                # Never reuse a deleted task's identity while an old worker
                # may still hold its stable lifecycle lock.
                if (self._lifecycle_root() / f"{task_id}.lifecycle.lock").exists():
                    continue
                task_dir = self._task_dir(task_id)
                try:
                    task_dir.mkdir(exist_ok=False)
                    break
                except FileExistsError:
                    continue
            self._save_task(task_id, {
                "task_id": task_id, "original_filename": name,
                "target_language": target_language, "requested_backend": converter_backend or "auto",
                "status": "queued", "stage": "queued", "created_at": time.time(),
                "last_activity_at": time.time(), "config_snapshot": self._capture_config_snapshot(),
            })
        try:
            with self._task_lifecycle_lock(task_id):
                if not task_dir.exists():
                    raise FileNotFoundError(f"Task {task_id} was cleared before upload completed")
                with (task_dir / name).open("wb") as dest:
                    shutil.copyfileobj(uploaded_file.file, dest, length=1024 * 1024)
            return task_id
        except BaseException:
            self._abandon_partial_task(task_id)
            raise

    def _extract_reserved(self, task_id: str) -> dict[str, Any]:
        with self._task_lifecycle_lock(task_id):
            metadata = self._load_task(task_id)
            input_path = resolve_within_directory(self._task_dir(task_id), metadata["original_filename"])
            if self._is_task_cancelled(task_id):
                from app.services.cad_pipeline_service import TaskCancelledError
                raise TaskCancelledError("Task cancelled by user.")
            with input_path.open("rb") as source:
                return self._register_uploaded_task(
                    task_id=task_id, uploaded_file=UploadFile(filename=input_path.name, file=source),
                    suffix=input_path.suffix.lower(), target_language=metadata.get("target_language", "en"),
                    converter_backend=metadata.get("requested_backend"), safe_filename=input_path.name,
                    started_at=time.perf_counter(),
                )

    def submit_upload(self, uploaded_file: UploadFile, **options) -> dict[str, Any]:
        if not _capacity.acquire(blocking=False):
            raise TaskBusyError("CAD queue is full; wait for a task to finish and retry.")
        try:
            task_id = self.reserve_upload(uploaded_file, options.get("target_language", "en"), options.get("converter_backend"))
            self._update_task(task_id, job_options=options, job_queued=True, owner_pid=os.getpid(), owner_started=_PROCESS_STARTED)
            _executor.submit(self._run_background, task_id, options)
        except BaseException:
            _capacity.release()
            raise
        return {"task_id": task_id, "status": "queued", "stage": "queued"}

    def _run_background(self, task_id, options):
        try:
            with self._task_execution_claim(task_id):
                self._update_task(task_id, owner_pid=os.getpid(), owner_started=_PROCESS_STARTED, job_queued=False, resume_queued=False)
                self._process_registered(task_id, **options)
        except Exception as exc:
            if self._task_dir(task_id).exists():
                cancelled = self._is_task_cancelled(task_id) or "cancelled" in str(exc).lower()
                self._update_task(task_id, status="cancelled" if cancelled else "error",
                                  stage="cancelled" if cancelled else "failed", last_error=str(exc))
        finally:
            try:
                self._update_task(task_id, owner_pid=None, cancellation_requested=False)
            finally:
                _capacity.release()

    def submit_resume(self, task_id: str, **options):
        # Register the resume before accepting it; duplicate queued resumes fail.
        with self._task_execution_claim(task_id), self._task_lifecycle_lock(task_id):
            self._reject_live_queue(task_id)
            self._resume_options(task_id, **options)
            if not _capacity.acquire(blocking=False):
                raise TaskBusyError("CAD queue is full; retry after a task completes.")
            try:
                self._clear_task_cancel(task_id)
                self._update_task(task_id, resume_queued=True, owner_pid=os.getpid(), owner_started=_PROCESS_STARTED)
                _executor.submit(self._run_resume, task_id, options)
            except BaseException:
                try:
                    self._update_task(task_id, resume_queued=False, owner_pid=None)
                finally:
                    _capacity.release()
                raise
        return {"task_id": task_id, "status": "queued", "stage": "queued"}

    def _run_resume(self, task_id, options):
        try:
            with file_lock(self._lifecycle_root() / f"{task_id}.execution"):
                self._update_task(task_id, owner_pid=os.getpid(), owner_started=_PROCESS_STARTED, job_queued=False, resume_queued=False)
                self.resume_task(task_id, _preserve_cancel=True, **options)
        except Exception as exc:
            cancelled = self._is_task_cancelled(task_id) or "cancelled" in str(exc).lower()
            self._update_task(task_id, status="cancelled" if cancelled else "error",
                              stage="cancelled" if cancelled else "failed", last_error=str(exc))
        finally:
            try:
                self._update_task(task_id, resume_queued=False, owner_pid=None, cancellation_requested=False)
            finally:
                _capacity.release()

    def task_page(self, limit=100, offset=0, updated_after=None):
        try:
            return self._task_index().page(limit, offset, updated_after)
        except Exception:
            # list_tasks retains a manifest fallback if the derived index fails.
            pass
        tasks = self.list_tasks()
        if updated_after is not None:
            tasks = [t for t in tasks if float(t.get("last_activity_at") or 0) > updated_after]
        return {"data": tasks[offset:offset + limit], "total": len(tasks), "limit": limit, "offset": offset}

    def _prune_packages(self):
        cutoff = time.time() - 86400
        for artifact in self._packages_root().iterdir():
            try:
                if artifact.is_file() and artifact.stat().st_mtime < cutoff:
                    artifact.unlink()
            except OSError:
                pass

    def snapshot_download(self, task_id, file_type):
        self._prune_packages()
        with self._task_lifecycle_lock(task_id):
            source, media_type = self.resolve_download(task_id, file_type)
            fd, name = tempfile.mkstemp(prefix="download-", suffix=source.suffix, dir=self._packages_root())
            os.close(fd)
            target = Path(name)
            try:
                shutil.copyfile(source, target)
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            return target, media_type, source.name

    def build_download_package(self, task_ids):
        from app.services.cad_pipeline_service import validate_task_id
        if not isinstance(task_ids, list) or not task_ids or len(task_ids) > 1000:
            raise ValueError("Provide between 1 and 1000 task IDs")
        ids = list(dict.fromkeys(validate_task_id(t) for t in task_ids))
        self._prune_packages()
        snapshots = []
        with tempfile.TemporaryDirectory(prefix="cad-package-stage-") as temp:
            for task_id in ids:
                with self._task_lifecycle_lock(task_id):
                    meta = self._load_task(task_id)
                    folder = self._archive_name(f"{Path(get_safe_filename(meta.get('original_filename') or task_id)).stem}_{task_id}")
                    for kind, name in (("excel", meta.get("translated_excel_filename") or meta.get("excel_filename")),
                                       ("cad", meta.get("translated_cad_filename"))):
                        if not name:
                            continue
                        source = resolve_within_directory(self._task_dir(task_id), name)
                        if not source.is_file():
                            raise FileNotFoundError(f"Missing {kind} artifact for task {task_id}")
                        archive_name = f"{folder}/{kind}/{source.name}"
                        target = Path(temp) / task_id / kind / source.name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, target)
                        snapshots.append((target, archive_name))
            if not snapshots:
                raise FileNotFoundError("No downloadable CAD outputs were found")
            fd, name = tempfile.mkstemp(prefix="cad-package-", suffix=".zip", dir=self._packages_root())
            os.close(fd)
            target = Path(name)
            try:
                with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
                    for source, name in snapshots:
                        archive.write(source, name)
            except BaseException:
                target.unlink(missing_ok=True)
                raise
        return target, "application/zip"
