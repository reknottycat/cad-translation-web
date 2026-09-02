from __future__ import annotations

import json
import os
import stat
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from tempfile import mkstemp
from typing import Any, Callable

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


class TaskCancelledError(RuntimeError):
    pass


class CADPipelineService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.processor = cad_text_processor
        # 使用模块化工作流管道处理新任务
        self._pipeline = get_pipeline()
        # 注意：跨进程锁由 locking.file_lock 通过旁车 .lock 文件提供。
        # 该文件锁同时保护同进程内多线程访问（内部含 RLock）。

    def _tasks_root(self) -> Path:
        tasks_root = self.settings.get_output_path() / "cad_tasks"
        tasks_root.mkdir(parents=True, exist_ok=True)
        return tasks_root

    def _task_dir(self, task_id: str) -> Path:
        return self._tasks_root() / task_id

    # --- Cross-process cancellation markers (file-based) ---
    # Each task directory may contain a `.cancel` marker file. Any worker
    # process can request cancellation by creating this file. A worker running
    # a task checks for the marker's existence before/after each chunk.
    # Unlike the old in-memory `_cancelled_task_ids` set, the file marker is
    # visible across processes (multi-worker Celery / multi-process uvicorn).

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

    # --- Runtime config snapshot helpers ---
    def _capture_config_snapshot(self) -> dict[str, Any]:
        """Capture the effective LLM/CAD runtime config at a point in time.

        This is stored in task.json so that a task's subsequent behavior is
        deterministic even if the server-global config is updated mid-flight.
        API keys are redacted so task.json is safe to download/expose.
        """
        return {
            "llm_runtime": self._redact_api_keys(self._get_translation_runtime()),
            "raw_config_payload": self._redact_api_keys(self._load_runtime_config_payload()),
        }

    @staticmethod
    def _redact_api_keys(payload: dict[str, Any]) -> dict[str, Any]:
        """Recursively replace sensitive key fields with a redacted marker."""
        sensitive_keys = {
            "api_key", "apiKey", "secret", "secret_key", "secretKey",
            "token", "access_token", "api_secret", "apiSecret",
            "security_token", "session_token", "authorization",
        }

        def _walk(value: Any) -> Any:
            if isinstance(value, dict):
                out: dict[str, Any] = {}
                for k, v in value.items():
                    if isinstance(k, str) and k.strip().lower().replace("-", "_") in {
                        s.lower().replace("-", "_") for s in sensitive_keys
                    }:
                        out[k] = "***"
                    else:
                        out[k] = _walk(v)
                return out
            if isinstance(value, list):
                return [_walk(v) for v in value]
            return value

        return _walk(payload)

    def _get_task_config_snapshot(self, task_id: str) -> dict[str, Any]:
        metadata = self._load_task(task_id)
        snapshot = metadata.get("config_snapshot")
        if isinstance(snapshot, dict):
            return snapshot
        return {}

    def _snapshot_runtime_summary(self, task_id: str) -> dict[str, Any]:
        """Return the runtime summary from the task's config snapshot if present,
        else fall back to live config.

        The snapshot has API keys redacted (safe for task.json), but contains
        all non-sensitive parameters (batch_size, provider, model, parallel_count,
        retry_count, glossary settings, etc.) that determine task behaviour.
        The task-level parameters determine chunking and progress reporting
        AND the actual translation service config (via ``_get_frozen_llm_config``)
        so a mid-flight config change cannot silently alter a task's behaviour."""
        snapshot = self._get_task_config_snapshot(task_id)
        llm_runtime = snapshot.get("llm_runtime")
        if isinstance(llm_runtime, dict) and llm_runtime:
            return llm_runtime
        return self._get_translation_runtime()

    def _get_frozen_llm_config(self, task_id: str) -> dict[str, Any] | None:
        """Return the task's frozen ``llm`` config section from its snapshot.

        The snapshot's ``raw_config_payload`` is the full config file with API
        keys redacted to ``***``.  The translation service merges live keys at
        call time, so returning the raw ``llm`` section here is safe.
        Returns ``None`` when no snapshot exists (caller falls back to live).
        """
        snapshot = self._get_task_config_snapshot(task_id)
        raw_payload = snapshot.get("raw_config_payload")
        if not isinstance(raw_payload, dict):
            return None
        llm_section = raw_payload.get("llm")
        if not isinstance(llm_section, dict):
            return None
        return dict(llm_section)

    def _task_excel_path(self, task_id: str, metadata: dict[str, Any] | None = None) -> Path:
        metadata = metadata or self._load_task(task_id)
        excel_filename = metadata.get("excel_filename")
        if not excel_filename:
            raise FileNotFoundError(f"Excel is missing for task {task_id}")
        return self._task_dir(task_id) / excel_filename

    def _write_translated_excel(self, task_id: str, translation_map: dict[str, str]) -> Path:
        if not translation_map:
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

        df["译文"] = df["原文"].apply(_translate_cell)
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
        """
        if not task_id:
            return
        log_path = self._task_log_path(task_id)
        if not log_path.parent.exists():
            return
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with file_lock(log_path):
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {message}\n")
                f.flush()

    def _save_checkpoint(self, task_id: str, translations: list[dict[str, str]]) -> None:
        """Save translation checkpoint to disk.

        If the task directory no longer exists (deleted concurrently), writing
        is skipped so no orphan checkpoint file is created.
        """
        if not task_id:
            return
        checkpoint_path = self._task_checkpoint_path(task_id)
        if not checkpoint_path.parent.exists():
            return
        # Cross-process + in-process lock on the checkpoint file's sidecar.
        with file_lock(checkpoint_path):
            atomic_write_json(checkpoint_path, translations)

    def _load_checkpoint(self, task_id: str) -> list[dict[str, str]]:
        checkpoint_path = self._task_checkpoint_path(task_id)
        if not checkpoint_path.exists():
            return []
        # Cross-process + in-process lock on the checkpoint file's sidecar.
        with file_lock(checkpoint_path):
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                return json.load(f)

    def _get_translation_runtime(self) -> dict[str, Any]:
        runtime = dict(alibaba_ai_translation_service.get_runtime_summary())
        active_config_getter = getattr(alibaba_ai_translation_service, "_active_config", None)
        if callable(active_config_getter):
            try:
                active_config = active_config_getter()
            except Exception:
                active_config = {}
            if isinstance(active_config, dict):
                runtime.update(active_config)
        return runtime

    def _load_runtime_config_payload(self) -> dict[str, Any]:
        config_path = self.settings.get_runtime_config_path()
        if not config_path.exists():
            return {}
        with file_lock(config_path):
            try:
                payload = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _get_nested_value(payload: dict[str, Any], *path: str) -> Any:
        current: Any = payload
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    @staticmethod
    def _coerce_bool(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        normalized = str(value or "").strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return None

    @staticmethod
    def _normalize_executor(value: Any) -> str:
        return str(value or "").strip().lower().replace("-", "_")

    @staticmethod
    def _translation_identity(item: dict[str, Any]) -> str:
        record_id = str(item.get("record_id") or "").strip()
        if record_id:
            return f"record:{record_id}"
        return f"original:{str(item.get('original') or '').strip()}"

    def _is_docutranslate_enabled(self, runtime: dict[str, Any]) -> bool:
        env_executor = self._normalize_executor(os.environ.get("CAD_TRANSLATION_EXECUTOR"))
        if env_executor:
            return env_executor == "docutranslate"

        env_toggle = self._coerce_bool(os.environ.get("CAD_USE_DOCUTRANSLATE"))
        if env_toggle is not None:
            return env_toggle

        for key in ("translation_executor", "execution_path", "translation_backend", "translation_engine"):
            runtime_executor = self._normalize_executor(runtime.get(key))
            if runtime_executor:
                return runtime_executor == "docutranslate"

        if self._normalize_executor(runtime.get("provider")) == "docutranslate":
            return True

        config_payload = self._load_runtime_config_payload()
        for path in (("cad", "use_docutranslate"), ("docutranslate", "enabled")):
            toggle = self._coerce_bool(self._get_nested_value(config_payload, *path))
            if toggle is not None:
                return toggle

        for path in (
            ("cad", "translation_executor"),
            ("cad", "translation_backend"),
            ("cad", "translation_engine"),
            ("llm", "translation_executor"),
            ("translation_executor",),
        ):
            config_executor = self._normalize_executor(self._get_nested_value(config_payload, *path))
            if config_executor:
                return config_executor == "docutranslate"

        return False

    def _resolve_docutranslate_source_root(self, runtime: dict[str, Any]) -> Path:
        candidates: list[Path] = []

        env_source_root = str(os.environ.get("DOCUTRANSLATE_SOURCE_ROOT") or "").strip()
        if env_source_root:
            candidates.append(Path(env_source_root))

        for key in ("docutranslate_source_root", "docutranslate_root", "source_root"):
            raw_value = str(runtime.get(key) or "").strip()
            if raw_value:
                candidates.append(Path(raw_value))

        config_payload = self._load_runtime_config_payload()
        for path in (
            ("docutranslate", "source_root"),
            ("cad", "docutranslate_source_root"),
            ("cad", "docutranslate_root"),
            ("llm", "docutranslate_source_root"),
        ):
            raw_value = str(self._get_nested_value(config_payload, *path) or "").strip()
            if raw_value:
                candidates.append(Path(raw_value))

        for base in (self.settings.BASE_DIR, Path.cwd(), *self.settings.BASE_DIR.parents):
            candidates.append(base / "docutranslate-main")
            candidates.append(base / "A开源翻译软件" / "docutranslate-main")

        seen: set[str] = set()
        for candidate in candidates:
            resolved = candidate.expanduser()
            if not resolved.is_absolute():
                resolved = self.settings.resolve_path(resolved)
            resolved = resolved.resolve()
            marker = str(resolved)
            if marker in seen:
                continue
            seen.add(marker)
            if resolved.exists():
                return resolved

        raise FileNotFoundError(
            "DocuTranslate source root was not found. Set DOCUTRANSLATE_SOURCE_ROOT or add "
            "'docutranslate.source_root' to the runtime config."
        )

    def _build_docutranslate_adapter(
        self,
        runtime: dict[str, Any],
        target_language: str,
    ) -> DocuTranslateJsonAdapter:
        config = DocuTranslateConfig.from_runtime(
            runtime,
            source_root=self._resolve_docutranslate_source_root(runtime),
            to_lang=target_language,
        )
        return DocuTranslateJsonAdapter(config=config)

    def _build_text_entries(self, task_id: str, texts: list[dict[str, Any]]) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        for index, entry in enumerate(texts):
            original = str(entry.get("original_text") or "").strip()
            if not original:
                continue
            record_id = str(entry.get("id") or f"{task_id}_{index}").strip() or f"{task_id}_{index}"
            entries.append({"record_id": record_id, "original": original})
        return entries

    def _load_excel_text_entries(self, task_id: str, metadata: dict[str, Any]) -> list[dict[str, str]]:
        excel_path = self._task_excel_path(task_id, metadata)
        df = pd.read_excel(excel_path)

        values: list[str] = []
        # 使用真实表头名“原文”（曾误写成乱码“鍘熸枃”，导致永远匹配不到而回退到第 0 列）
        if "原文" in df.columns:
            values = df["原文"].fillna("").astype(str).tolist()
        elif len(df.columns) > 0:
            values = df.iloc[:, 0].fillna("").astype(str).tolist()

        entries: list[dict[str, str]] = []
        for index, value in enumerate(values):
            original = str(value).strip()
            if not original:
                continue
            entries.append({"record_id": f"{task_id}_{index}", "original": original})
        return entries

    def _packages_root(self) -> Path:
        packages_root = self._tasks_root() / "_packages"
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
                return
            except OSError as exc:
                last_error = exc
                time.sleep(0.5 * (attempt + 1))

        raise PermissionError(
            f"Task directory is still in use. Close related CAD/ODA windows and retry: {path}"
        ) from last_error

    def _load_task(self, task_id: str) -> dict[str, Any]:
        metadata_path = self._task_meta_path(task_id)
        if not metadata_path.exists():
            raise FileNotFoundError(f"Task not found: {task_id}")
        # Use a cross-process file lock so concurrent readers see a consistent
        # snapshot even when a writer in another process is mid-update.
        with file_lock(metadata_path):
            return json.loads(metadata_path.read_text(encoding="utf-8"))

    def _save_task(self, task_id: str, payload: dict[str, Any]) -> None:
        """Atomically persist task metadata.

        If the task directory no longer exists (deleted concurrently by
        ``delete_task`` / ``clear_all_tasks``), writing is skipped so no
        orphan task.json is created in a re-created directory.
        """
        if not task_id:
            return
        metadata_path = self._task_meta_path(task_id)
        if not metadata_path.parent.exists():
            return
        # Atomic write prevents readers from seeing a truncated/partial JSON.
        # Cross-process file lock protects against concurrent multi-process writes.
        with file_lock(metadata_path):
            atomic_write_json(metadata_path, payload)

    def _update_task(self, task_id: str, **patch: Any) -> dict[str, Any]:
        """Update task metadata via guarded read-modify-write.

        If the task directory no longer exists (e.g. deleted concurrently by
        ``delete_task`` / ``clear_all_tasks``), returns the empty dict and
        does NOT create any files — avoids re-creating orphan task dirs.
        """
        if not task_id:
            return {}
        metadata_path = self._task_meta_path(task_id)
        # Guard before acquiring file_lock: if the task dir is gone, do not
        # let file_lock's sidecar parent.mkdir recreate it.
        if not metadata_path.parent.exists():
            return {}
        # Serialize read-modify-write on the task metadata file so concurrent
        # updates (including from other processes) don't clobber each other.
        # file_lock is re-entrant, so _load_task / _save_task nested inside
        # this block won't deadlock within the same thread.
        with file_lock(metadata_path):
            metadata = self._load_task(task_id)
            metadata.update(patch)
            metadata["last_activity_at"] = time.time()
            self._save_task(task_id, metadata)
            return metadata

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
        return {
            "task_id": task_id,
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

    def _map_backend(self, backend: str | None) -> str:
        normalized = (backend or "").strip().lower()
        mapping = {
            "": "auto",
            "auto": "auto",
            "haochen_com": "haochen_com",
            "gstar_com": "haochen_com",
            "autocad_com": "autocad_com",
            "oda_cli": "oda",
            "oda": "oda",
            "com": "com",
            "dxf_native": "dxf_only",
        }
        if normalized in mapping:
            return mapping[normalized]
        return normalized

    def extract_upload(
        self,
        uploaded_file: UploadFile,
        target_language: str = "en",
        converter_backend: str | None = None,
    ) -> dict[str, Any]:
        if not uploaded_file.filename:
            raise ValueError("File name is required.")

        started_at = time.perf_counter()
        suffix = Path(uploaded_file.filename).suffix.lower()
        if suffix not in {".dwg", ".dxf"}:
            raise ValueError("Only DWG and DXF files are supported.")

        task_id = uuid.uuid4().hex[:8]
        task_dir = self._task_dir(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)

        safe_filename = get_safe_filename(uploaded_file.filename)
        input_path = task_dir / safe_filename
        with input_path.open("wb") as buffer:
            shutil.copyfileobj(uploaded_file.file, buffer)

        resolved_backend = self._map_backend(converter_backend)
        normalized_dxf_path = input_path
        if suffix == ".dwg":
            if resolved_backend == "dxf_only":
                raise ValueError("DWG upload requires a converter backend.")
            normalized_dxf_path = Path(
                self.processor._convert_dwg_to_dxf(
                    str(input_path),
                    task_dir,
                    backend_override=resolved_backend,
                )
            )

        extract_result = self.processor.extract_texts_to_excel(
            dxf_file_path=str(normalized_dxf_path),
            output_dir=str(task_dir),
        )

        texts = []
        for index, text_info in enumerate(extract_result.get("texts", [])):
            texts.append(
                {
                    "id": f"{task_id}_{index}",
                    "original_text": text_info.get("原文", ""),
                    "translated_text": "",
                    "entity_type": text_info.get("实体类型", ""),
                    "layer": text_info.get("图层", ""),
                    "position": f"({text_info.get('X坐标', 0)}, {text_info.get('Y坐标', 0)})",
                }
            )

        excel_filename = None
        if extract_result.get("output_file"):
            excel_filename = Path(str(extract_result["output_file"])).name

        translatable_count = alibaba_ai_translation_service.count_translatable_texts(
            [t.get("original_text", "") for t in texts]
        )
        metadata = {
            "task_id": task_id,
            "original_filename": safe_filename,
            "normalized_dxf_filename": normalized_dxf_path.name,
            "target_language": target_language,
            "requested_backend": converter_backend or "",
            "resolved_backend": resolved_backend,
            "config_snapshot": self._capture_config_snapshot(),
            "extract_only": False,
            "status": "processing",
            "stage": "extracting",
            "text_count": len(texts),
            "translatable_count": translatable_count,
            "translation_count": 0,
            "translated_count": 0,
            "excel_filename": excel_filename,
            "translated_cad_filename": None,
            "total_chunks": 0,
            "completed_chunks": 0,
            "current_chunk": 0,
            "provider": "",
            "model": "",
            "batch_size": 0,
            "retry_count": 0,
            "last_error": "",
            "created_at": time.time(),
            "last_activity_at": time.time(),
            "processing_time": f"{time.perf_counter() - started_at:.1f}s",
        }
        self._save_task(task_id, metadata)

        return {
            "task_id": task_id,
            "text_count": len(texts),
            "translatable_count": translatable_count,
            "excel_file_url": f"/api/cad/download/{task_id}/excel" if excel_filename else None,
            "texts": texts,
        }

    def _run_translation_with_logging(
        self,
        task_id: str,
        original_texts: list[str],
        target_language: str,
        runtime_summary: dict[str, Any],
        batch_size: int,
        total_chunks: int,
        ensure_not_cancelled: Callable[[], None],
        record_ids: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Run translation with progress logging and checkpoint saving."""
        if self._is_docutranslate_enabled(runtime_summary):
            # DocuTranslate adapter needs the full live config (including API key).
            # The sanitized snapshot lacks the API key, so merge the snapshot's
            # non-secret keys over the live config.
            full_runtime = self._get_translation_runtime()
            full_runtime.update({k: v for k, v in runtime_summary.items() if v != "***"})
            return self._run_docutranslate_translation_with_logging(
                task_id=task_id,
                original_texts=original_texts,
                target_language=target_language,
                runtime=full_runtime,
                batch_size=batch_size,
                total_chunks=total_chunks,
                ensure_not_cancelled=ensure_not_cancelled,
                record_ids=record_ids,
            )
        self._append_log(task_id, f"开始翻译: {len(original_texts)} 条文本, 批次大小={batch_size}, 并发数={runtime_summary.get('parallel_count', 1)}")

        # Accumulate translations for real-time checkpoint saving
        checkpoint_translations: list[dict[str, str]] = []

        def on_translation_progress(progress: dict[str, Any]) -> None:
            if not task_id:
                return
            ensure_not_cancelled()
            event = progress.get("event", "")
            chunk_index = progress.get("chunk_index", 0)
            completed = progress.get("completed_chunks", 0)
            total = progress.get("total_chunks", 0)
            translated = progress.get("translated_count", 0)
            parallel = progress.get("parallel_count", 1)
            last_error = str(progress.get("last_error") or "").strip()

            if event == "started":
                self._append_log(task_id, f"翻译启动: 共 {total} 个批次, 并发={parallel}")
            elif event == "chunk_started":
                self._append_log(task_id, f"批次 {chunk_index}/{total} 开始...")
            elif event == "chunk_completed":
                log_msg = f"批次 {chunk_index}/{total} 完成 (已翻译 {translated}/{len(original_texts)} 条)"
                if last_error:
                    log_msg += f" [回退: {last_error[:60]}]"
                self._append_log(task_id, log_msg)
                # Real-time checkpoint: save each chunk's translations immediately
                chunk_translations = progress.get("chunk_translations") or {}
                if chunk_translations:
                    for original, translated in chunk_translations.items():
                        if translated and translated.startswith("[translation_error]"):
                            # Preserve failed entries with empty translated so resume can retry them
                            checkpoint_translations.append({"original": original, "translated": ""})
                        elif translated and translated.strip():
                            checkpoint_translations.append({"original": original, "translated": translated})
                        else:
                            # Empty translation - also mark as pending
                            checkpoint_translations.append({"original": original, "translated": ""})
                    # Deduplicate by original text (keep last)
                    seen: dict[str, dict[str, str]] = {}
                    for item in checkpoint_translations:
                        seen[item["original"]] = item
                    checkpoint_translations.clear()
                    checkpoint_translations.extend(seen.values())
                    self._save_checkpoint(task_id, checkpoint_translations)
            elif event == "completed":
                self._append_log(task_id, f"翻译完成: 共翻译 {translated} 条文本")
                # Final checkpoint save
                if checkpoint_translations:
                    self._save_checkpoint(task_id, checkpoint_translations)

            patch: dict[str, Any] = {
                "status": "processing",
                "stage": "translating",
                "provider": progress.get("provider", runtime_summary.get("provider", "")),
                "model": progress.get("model", runtime_summary.get("model", "")),
                "batch_size": int(progress.get("batch_size") or batch_size),
                "retry_count": int(progress.get("retry_count") or runtime_summary.get("retry_count") or 0),
                "total_chunks": int(progress.get("total_chunks") or total_chunks),
                "completed_chunks": completed,
                "current_chunk": int(progress.get("chunk_index") or 0),
                "translated_count": translated,
            }
            if last_error:
                patch["last_error"] = last_error
            self._update_task(task_id, **patch)

        frozen_llm = self._get_frozen_llm_config(task_id)
        if frozen_llm:
            with alibaba_ai_translation_service.frozen_config(frozen_llm):
                translated_texts = alibaba_ai_translation_service.translate_batch(
                    texts=original_texts,
                    target_lang=target_language,
                    progress_callback=on_translation_progress,
                    should_cancel=lambda: bool(task_id and self._is_task_cancelled(task_id)),
                )
        else:
            translated_texts = alibaba_ai_translation_service.translate_batch(
                texts=original_texts,
                target_lang=target_language,
                progress_callback=on_translation_progress,
                should_cancel=lambda: bool(task_id and self._is_task_cancelled(task_id)),
            )
        ensure_not_cancelled()
        translations: list[dict[str, str]] = []
        failed_count = 0
        for index, (original, translated) in enumerate(zip(original_texts, translated_texts)):
            if not original or not original.strip():
                continue
            item: dict[str, str] = {"original": original}
            if record_ids and index < len(record_ids) and record_ids[index]:
                item["record_id"] = record_ids[index]
            if translated and translated.startswith("[translation_error]"):
                item["translated"] = ""
                translations.append(item)
                failed_count += 1
            elif translated and translated.strip():
                item["translated"] = translated
                translations.append(item)
            else:
                item["translated"] = ""
                translations.append(item)
                failed_count += 1
        if not record_ids:
            # Deduplicate by original text (keep last)
            seen: dict[str, dict[str, str]] = {}
            for item in translations:
                seen[item["original"]] = item
            translations = list(seen.values())
        # Final save (in case some translations were not captured via callback)
        self._save_checkpoint(task_id, translations)
        successful = len([t for t in translations if t.get("translated")])
        self._append_log(task_id, f"翻译结果已保存: {successful} 条成功, {failed_count} 条失败")
        return translations

    def _run_docutranslate_translation_with_logging(
        self,
        task_id: str,
        original_texts: list[str],
        target_language: str,
        runtime: dict[str, Any],
        batch_size: int,
        total_chunks: int,
        ensure_not_cancelled: Callable[[], None],
        record_ids: list[str] | None = None,
    ) -> list[dict[str, str]]:
        working_dir = self._task_dir(task_id) / "docutranslate"
        adapter = self._build_docutranslate_adapter(runtime, target_language)
        effective_record_ids = record_ids or [f"{task_id}_{index}" for index in range(len(original_texts))]
        records = [
            CadTextRecord(record_id=record_id, source_text=source_text)
            for record_id, source_text in zip(effective_record_ids, original_texts)
            if source_text and source_text.strip()
        ]

        self._append_log(
            task_id,
            f"开始翻译: {len(records)} 条文本, 执行路径=DocuTranslate, 工作目录={working_dir.name}",
        )
        self._update_task(
            task_id,
            status="processing",
            stage="translating",
            provider="docutranslate",
            model=runtime.get("model", ""),
            batch_size=batch_size,
            retry_count=int(runtime.get("retry_count") or 0),
            total_chunks=total_chunks,
            completed_chunks=0,
            current_chunk=0,
            translated_count=0,
            last_error="",
        )

        ensure_not_cancelled()
        batch_result = adapter.translate_records(records, working_dir=working_dir)
        ensure_not_cancelled()

        translated_by_id = {
            record.record_id: str(record.translated_text or "").strip()
            for record in batch_result.records
        }

        translations: list[dict[str, str]] = []
        failed_count = 0
        for record in records:
            translated = translated_by_id.get(record.record_id, "")
            item = {
                "record_id": record.record_id,
                "original": record.source_text,
                "translated": translated,
            }
            translations.append(item)
            if not translated:
                failed_count += 1

        self._save_checkpoint(task_id, translations)
        successful = len(translations) - failed_count
        self._update_task(
            task_id,
            status="processing",
            stage="translating",
            provider="docutranslate",
            model=runtime.get("model", ""),
            batch_size=batch_size,
            retry_count=int(runtime.get("retry_count") or 0),
            total_chunks=total_chunks,
            completed_chunks=total_chunks,
            current_chunk=total_chunks,
            translated_count=successful,
            last_error="",
        )
        self._append_log(
            task_id,
            f"DocuTranslate 翻译完成: {successful} 条成功, {failed_count} 条失败, artifacts={batch_result.translated_json_path.name}",
        )
        return translations

    def process_upload(
        self,
        uploaded_file: UploadFile,
        target_language: str = "en",
        converter_backend: str | None = None,
        extract_only: bool = False,
        translation_mode: str = "replace",
        font_name: str | None = None,
        font_size_reduction: int = 2,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        task_id: str | None = None
        try:
            def ensure_not_cancelled() -> None:
                if task_id and self._is_task_cancelled(task_id):
                    raise TaskCancelledError("Task cancelled by user.")

            extract_result = self.extract_upload(
                uploaded_file=uploaded_file,
                target_language=target_language,
                converter_backend=converter_backend,
            )
            task_id = extract_result["task_id"]
            self._append_log(task_id, f"任务创建: {extract_result.get('text_count', 0)} 条文本已提取")
            ensure_not_cancelled()
            self._update_task(
                task_id,
                extract_only=extract_only,
                status="processing",
                stage="extracted",
                last_error="",
                processing_time=f"{time.perf_counter() - started_at:.1f}s",
            )

            if extract_only:
                self._update_task(
                    task_id,
                    status="done",
                    stage="completed",
                    processing_time=f"{time.perf_counter() - started_at:.1f}s",
                )
                self._append_log(task_id, "仅提取模式，任务完成")
                return {
                    **extract_result,
                    "translation_count": 0,
                    "translated_cad_file": None,
                }

            text_entries = self._build_text_entries(task_id, extract_result.get("texts", []))
            original_texts = [entry["original"] for entry in text_entries]
            record_ids = [entry["record_id"] for entry in text_entries]
            if not original_texts:
                self._update_task(
                    task_id,
                    status="done",
                    stage="completed",
                    processing_time=f"{time.perf_counter() - started_at:.1f}s",
                )
                self._append_log(task_id, "无有效文本，任务完成")
                return {
                    **extract_result,
                    "translation_count": 0,
                    "translated_cad_file": None,
                }

            # Use the config snapshot captured when the task was created so
            # that a mid-flight global config update cannot silently change
            # batch_size / provider / model / rate-limit params for this task.
            runtime_summary = self._snapshot_runtime_summary(task_id)
            batch_size = max(1, int(runtime_summary.get("batch_size") or 1))
            translatable_count = alibaba_ai_translation_service.count_translatable_texts(original_texts)
            total_chunks = (translatable_count + batch_size - 1) // batch_size if translatable_count else 0
            self._update_task(
                task_id,
                status="processing",
                stage="translating",
                provider=runtime_summary.get("provider", ""),
                model=runtime_summary.get("model", ""),
                batch_size=batch_size,
                retry_count=int(runtime_summary.get("retry_count") or 0),
                total_chunks=total_chunks,
                completed_chunks=0,
                current_chunk=0,
                translated_count=0,
                last_error="",
            )

            translations = self._run_translation_with_logging(
                task_id=task_id,
                original_texts=original_texts,
                target_language=target_language,
                runtime_summary=runtime_summary,
                batch_size=batch_size,
                total_chunks=total_chunks,
                ensure_not_cancelled=ensure_not_cancelled,
                record_ids=record_ids,
            )

            successful_count = len([t for t in translations if t.get("translated")])
            failed_count = len([t for t in translations if not t.get("translated")])
            has_failures = failed_count > 0

            self._update_task(
                task_id,
                status="processing",
                stage="applying",
                completed_chunks=total_chunks,
                current_chunk=total_chunks,
                translated_count=successful_count,
                translation_count=successful_count,
                failed_count=failed_count,
                processing_time=f"{time.perf_counter() - started_at:.1f}s",
            )
            self._append_log(task_id, f"开始回写翻译: {successful_count} 条成功, {failed_count} 条失败")
            apply_result = self.apply_translation(
                task_id=extract_result["task_id"],
                translations=translations,
                translation_mode=translation_mode,
                font_name=font_name,
                font_size_reduction=font_size_reduction,
            )
            ensure_not_cancelled()
            final_status = "partial" if has_failures else "done"
            self._update_task(
                task_id,
                status=final_status,
                stage="completed",
                completed_chunks=total_chunks,
                current_chunk=total_chunks,
                translated_count=apply_result["translation_count"],
                translation_count=apply_result["translation_count"],
                failed_count=failed_count,
                translated_cad_filename=self._load_task(task_id).get("translated_cad_filename"),
                processing_time=f"{time.perf_counter() - started_at:.1f}s",
            )
            if has_failures:
                self._append_log(task_id, f"任务部分完成: {successful_count} 条成功, {failed_count} 条失败，可点击「继续翻译」重试")
            else:
                self._append_log(task_id, f"任务完成: 翻译 {apply_result['translation_count']} 条")
            return {
                **extract_result,
                "translation_count": apply_result["translation_count"],
                "failed_count": failed_count,
                "translated_cad_file": apply_result["translated_cad_file"],
                "status": final_status,
            }
        except TaskCancelledError as exc:
            if task_id:
                self._update_task(
                    task_id,
                    status="cancelled",
                    stage="cancelled",
                    last_error=str(exc),
                    processing_time=f"{time.perf_counter() - started_at:.1f}s",
                )
                self._append_log(task_id, f"任务已取消: {exc}")
                self._clear_task_cancel(task_id)
            raise
        except Exception as exc:
            cancelled = "cancelled by user" in str(exc).lower() or "stopped by user" in str(exc).lower()
            if task_id:
                self._update_task(
                    task_id,
                    status="cancelled" if cancelled else "error",
                    stage="cancelled" if cancelled else "failed",
                    last_error=str(exc),
                    processing_time=f"{time.perf_counter() - started_at:.1f}s",
                )
                self._append_log(task_id, f"任务失败: {exc}")
            raise
        finally:
            if task_id:
                self._clear_task_cancel(task_id)

    def resume_task(
        self,
        task_id: str,
        target_language: str = "en",
        translation_mode: str = "replace",
        font_name: str | None = None,
        font_size_reduction: int = 2,
    ) -> dict[str, Any]:
        """Resume an interrupted or failed task from its last checkpoint."""
        started_at = time.perf_counter()
        metadata = self._load_task(task_id)
        task_dir = self._task_dir(task_id)

        # Refresh the config snapshot for this resumed execution so that
        # changes made since the original task creation are reflected in the
        # resumed task's behaviour (the operator chose to resume, so they
        # implicitly accept the current config as the new baseline).
        self._update_task(task_id, config_snapshot=self._capture_config_snapshot())
        metadata = self._load_task(task_id)

        text_count = metadata.get("text_count", 0)
        translated_count = metadata.get("translated_count", 0)
        is_done = metadata.get("status") == "done" and metadata.get("stage") == "completed"
        has_untranslated = translated_count < text_count
        if is_done and not has_untranslated:
            raise ValueError("Task is already completed. Use 'Restart' instead.")

        self._append_log(task_id, "=" * 40)
        self._append_log(task_id, f"任务恢复: stage={metadata.get('stage')}, status={metadata.get('status')}")

        def ensure_not_cancelled() -> None:
            if self._is_task_cancelled(task_id):
                raise TaskCancelledError("Task cancelled by user.")

        # Stage 1: If extraction was not done, we can't resume (need original file re-upload)
        stage = metadata.get("stage", "")
        if stage in ("", "queued") or not metadata.get("excel_filename"):
            raise ValueError("Task has not been extracted yet. Please restart with the original file.")

        # Load existing translations checkpoint if available
        checkpoint = self._load_checkpoint(task_id)
        translations = checkpoint[:]

        try:
            # If we have a translated CAD file already, task is effectively done
            if metadata.get("translated_cad_filename"):
                self._update_task(
                    task_id,
                    status="done",
                    stage="completed",
                    last_error="",
                    processing_time=f"{time.perf_counter() - started_at:.1f}s",
                )
                self._append_log(task_id, "任务已包含翻译结果，标记为完成")
                return {
                    "task_id": task_id,
                    "translation_count": len(translations),
                    "translated_cad_file": f"/api/cad/download/{task_id}/translated_cad",
                }

            # If we are before applying stage, ensure we have translations
            if stage in ("extracted", "extracting", "translating", "failed") or not translations:
                # Need to re-translate if no checkpoint
                if not translations:
                    self._append_log(task_id, "未找到翻译断点，重新执行翻译")
                    text_entries = self._load_excel_text_entries(task_id, metadata)
                    original_texts = [entry["original"] for entry in text_entries]
                    record_ids = [entry["record_id"] for entry in text_entries]

                    if not original_texts:
                        self._update_task(
                            task_id,
                            status="done",
                            stage="completed",
                            processing_time=f"{time.perf_counter() - started_at:.1f}s",
                        )
                        self._append_log(task_id, "Excel 中无有效文本，任务完成")
                        return {
                            "task_id": task_id,
                            "translation_count": 0,
                            "translated_cad_file": None,
                        }

                    runtime_summary = self._snapshot_runtime_summary(task_id)
                    batch_size = max(1, int(runtime_summary.get("batch_size") or 1))
                    translatable_count = alibaba_ai_translation_service.count_translatable_texts(original_texts)
                    total_chunks = (translatable_count + batch_size - 1) // batch_size if translatable_count else 0

                    self._update_task(
                        task_id,
                        status="processing",
                        stage="translating",
                        provider=runtime_summary.get("provider", ""),
                        model=runtime_summary.get("model", ""),
                        batch_size=batch_size,
                        retry_count=int(runtime_summary.get("retry_count") or 0),
                        total_chunks=total_chunks,
                        completed_chunks=0,
                        current_chunk=0,
                        translated_count=0,
                        last_error="",
                    )

                    translations = self._run_translation_with_logging(
                        task_id=task_id,
                        original_texts=original_texts,
                        target_language=target_language,
                        runtime_summary=runtime_summary,
                        batch_size=batch_size,
                        total_chunks=total_chunks,
                        ensure_not_cancelled=ensure_not_cancelled,
                        record_ids=record_ids,
                    )
                else:
                    successful = [t for t in translations if t.get("translated")]
                    failed = [t for t in translations if not t.get("translated")]
                    if failed:
                        self._append_log(task_id, f"从断点恢复: {len(successful)} 条已翻译, {len(failed)} 条待重新翻译")
                        failed_texts = [t["original"] for t in failed]
                        failed_record_ids = [str(t.get("record_id") or "").strip() for t in failed]
                        record_ids_for_retry = failed_record_ids if all(failed_record_ids) else None
                        runtime_summary = self._snapshot_runtime_summary(task_id)
                        batch_size = max(1, int(runtime_summary.get("batch_size") or 1))
                        translatable_count = alibaba_ai_translation_service.count_translatable_texts(failed_texts)
                        total_chunks = (translatable_count + batch_size - 1) // batch_size if translatable_count else 0
                        self._update_task(
                            task_id,
                            status="processing",
                            stage="translating",
                            provider=runtime_summary.get("provider", ""),
                            model=runtime_summary.get("model", ""),
                            batch_size=batch_size,
                            retry_count=int(runtime_summary.get("retry_count") or 0),
                            total_chunks=total_chunks,
                            completed_chunks=0,
                            current_chunk=0,
                            translated_count=0,
                            last_error="",
                        )
                        new_translations = self._run_translation_with_logging(
                            task_id=task_id,
                            original_texts=failed_texts,
                            target_language=target_language,
                            runtime_summary=runtime_summary,
                            batch_size=batch_size,
                            total_chunks=total_chunks,
                            ensure_not_cancelled=ensure_not_cancelled,
                            record_ids=record_ids_for_retry,
                        )
                        # Merge new translations into checkpoint, keeping successful ones
                        new_map = {self._translation_identity(t): t for t in new_translations}
                        merged: list[dict[str, str]] = []
                        for t in successful:
                            merged.append(t)
                        for t in failed:
                            updated = new_map.get(self._translation_identity(t))
                            merged_item = {
                                "original": t["original"],
                                "translated": updated.get("translated", "") if updated else "",
                            }
                            if t.get("record_id") or (updated and updated.get("record_id")):
                                merged_item["record_id"] = str(
                                    (updated.get("record_id") if updated else "") or t.get("record_id") or ""
                                )
                            merged.append(merged_item)
                        translations = merged
                        self._save_checkpoint(task_id, translations)
                    else:
                        self._append_log(task_id, f"从断点恢复: {len(translations)} 条已翻译")
                    self._update_task(
                        task_id,
                        status="processing",
                        stage="applying",
                        last_error="",
                    )

            # Stage: apply translation
            self._append_log(task_id, f"开始回写翻译: {len(translations)} 条")
            apply_result = self.apply_translation(
                task_id=task_id,
                translations=translations,
                translation_mode=translation_mode,
                font_name=font_name,
                font_size_reduction=font_size_reduction,
            )
            ensure_not_cancelled()
            failed_count = len([t for t in translations if not t.get("translated")])
            final_status = "partial" if failed_count > 0 else "done"
            self._update_task(
                task_id,
                status=final_status,
                stage="completed",
                completed_chunks=metadata.get("total_chunks", 0),
                current_chunk=metadata.get("total_chunks", 0),
                translated_count=apply_result["translation_count"],
                translation_count=apply_result["translation_count"],
                failed_count=failed_count,
                translated_cad_filename=self._load_task(task_id).get("translated_cad_filename"),
                processing_time=f"{time.perf_counter() - started_at:.1f}s",
                last_error="",
            )
            if failed_count > 0:
                self._append_log(task_id, f"任务恢复部分完成: {apply_result['translation_count']} 条成功, {failed_count} 条失败，可点击「继续翻译」重试")
            else:
                self._append_log(task_id, f"任务恢复完成: 翻译 {apply_result['translation_count']} 条")
            return {
                "task_id": task_id,
                "translation_count": apply_result["translation_count"],
                "failed_count": failed_count,
                "translated_cad_file": apply_result["translated_cad_file"],
                "status": final_status,
            }

        except TaskCancelledError as exc:
            self._update_task(
                task_id,
                status="cancelled",
                stage="cancelled",
                last_error=str(exc),
                processing_time=f"{time.perf_counter() - started_at:.1f}s",
            )
            self._append_log(task_id, f"恢复任务已取消: {exc}")
            self._clear_task_cancel(task_id)
            raise
        except Exception as exc:
            cancelled = "cancelled by user" in str(exc).lower() or "stopped by user" in str(exc).lower()
            self._update_task(
                task_id,
                status="cancelled" if cancelled else "error",
                stage="cancelled" if cancelled else "failed",
                last_error=str(exc),
                processing_time=f"{time.perf_counter() - started_at:.1f}s",
            )
            self._append_log(task_id, f"恢复任务失败: {exc}")
            raise
        finally:
            self._clear_task_cancel(task_id)

    def get_task_logs(self, task_id: str) -> str:
        log_path = self._task_log_path(task_id)
        if log_path.exists():
            # Acquire the same cross-process file lock used by _append_log
            # so we get a consistent snapshot even mid-write.
            with file_lock(log_path):
                return log_path.read_text(encoding="utf-8")
        # Fallback: return task metadata as pseudo-log for old tasks.
        # Uses _load_task which acquires the cross-process file lock.
        metadata = self._load_task(task_id)  # raises FileNotFoundError if absent
        lines = [f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(metadata.get('created_at', 0)))}] 任务创建"]
        lines.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(metadata.get('last_activity_at', 0)))}] 最后活动: stage={metadata.get('stage')}, status={metadata.get('status')}")
        if metadata.get("last_error"):
            lines.append(f"错误: {metadata['last_error']}")
        return "\n".join(lines)

    def apply_translation(
        self,
        task_id: str,
        translations: list[dict[str, str]],
        translation_mode: str = "replace",
        font_name: str | None = None,
        font_size_reduction: int = 2,
    ) -> dict[str, Any]:
        """
        将用户提供的翻译应用到 DXF 文件。

        Args:
            task_id:             任务 ID
            translations:        [{"original": ..., "translated": ...}] 列表
            translation_mode:    "replace" 替换原文 | "add" 在下方追加翻译（默认 "replace"）
            font_name:           输出字体名称（默认使用配置中的 DEFAULT_FONT_NAME）
            font_size_reduction: 字号缩小量（默认 2）
        """
        metadata = self._load_task(task_id)
        task_dir = self._task_dir(task_id)
        normalized_dxf_path = task_dir / metadata["normalized_dxf_filename"]
        if not normalized_dxf_path.exists():
            raise FileNotFoundError(f"Normalized DXF is missing for task {task_id}")

        translation_map: dict[str, str] = {}
        for item in translations:
            original = (item.get("original") or "").strip()
            translated = (item.get("translated") or "").strip()
            if original and translated:
                translation_map[original] = translated

        if not translation_map:
            raise ValueError("No non-empty translations were provided.")

        resolved_font = font_name or self.settings.DEFAULT_FONT_NAME
        translated_filename = f"translated_{normalized_dxf_path.name}"
        translated_output = task_dir / translated_filename

        # 使用新的 TextApplier 功能模块（通过 pipeline 调用）
        self._pipeline.run_apply_only(
            dxf_file=str(normalized_dxf_path),
            task_dir=str(task_dir),
            translation_map=translation_map,
            translation_mode=translation_mode,
            font_name=resolved_font,
            font_size_reduction=font_size_reduction,
        )
        translated_excel_path = self._write_translated_excel(task_id, translation_map)

        metadata["translation_count"] = len(translation_map)
        metadata["translated_count"] = len(translation_map)
        metadata["translated_cad_filename"] = translated_filename
        metadata["translated_excel_filename"] = translated_excel_path.name
        metadata["translation_mode"] = translation_mode
        metadata["font_name"] = resolved_font
        metadata["font_size_reduction"] = font_size_reduction
        self._save_task(task_id, metadata)

        return {
            "task_id": task_id,
            "translation_count": len(translation_map),
            "translation_mode": translation_mode,
            "font_name": resolved_font,
            "font_size_reduction": font_size_reduction,
            "translated_cad_file": f"/api/cad/download/{task_id}/translated_cad",
        }

    def list_tasks(self) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for metadata_path in self._tasks_root().glob("*/task.json"):
            task_id = metadata_path.parent.name
            try:
                metadata = self._load_task(task_id)
                tasks.append(self._build_task_summary(metadata))
            except (json.JSONDecodeError, OSError, FileNotFoundError) as exc:
                # A concurrent writer may have been mid-update or the task was deleted.
                logger.warning("task_meta_read_skipped", task_id=task_id, error=str(exc))
                continue
        status_rank = {"processing": 0, "error": 1, "queued": 2, "cancelled": 3, "done": 4}
        tasks.sort(
            key=lambda item: (
                status_rank.get(str(item.get("status") or "queued").lower(), 9),
                -(item.get("last_activity_at") or item.get("created_at") or 0),
            )
        )
        return tasks

    def clear_all_tasks(self) -> None:
        """Clear all tasks by removing the root tasks directory.

        Cross-process safe: we first mark every processing/queued task as
        cancelled by writing external `.cancel` markers (in the stable
        ``cad_cancel_marks/`` directory), then remove the task tree.  The
        markers signal any worker currently executing a task in this tree
        to stop before we delete files, preventing a "deleted-under-the-writer"
        race where a running worker writes task.json after we removed it.
        """
        tasks_root = self._tasks_root()
        cancel_root = self._cancel_marks_root()
        # Phase 1: mark all processing/queued tasks as cancelled.
        if tasks_root.exists():
            for metadata_path in tasks_root.glob("*/task.json"):
                task_id = metadata_path.parent.name
                try:
                    self._mark_task_cancelled(task_id)
                except OSError:
                    pass  # Already deleted or locked by another process.
        # Phase 2: remove the root tasks directory.
        if tasks_root.exists():
            self._delete_tree(tasks_root)
        # Recreate the root directory to ensure it exists for future tasks
        tasks_root.mkdir(parents=True, exist_ok=True)
        # Phase 3: clean up all external cancellation markers now that the
        # task tree is gone and any worker has already observed the deletion.
        if cancel_root.exists():
            for marker in cancel_root.glob("*.cancel"):
                try:
                    marker.unlink(missing_ok=True)
                except OSError:
                    pass

    def delete_task(self, task_id: str) -> None:
        task_dir = self._task_dir(task_id)
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
        # Clean up the external cancellation marker after the directory is
        # gone.  Any worker that was mid-flight has already observed the
        # directory deletion and treats the task as cancelled.
        self._clear_task_cancel(task_id)

    def stop_all_tasks(self) -> dict[str, Any]:
        cancelled_task_ids: list[str] = []
        for metadata_path in self._tasks_root().glob("*/task.json"):
            task_id = metadata_path.parent.name
            meta_path = self._task_meta_path(task_id)
            try:
                # Hold the task.json file_lock across the entire
                # read-modify-write so another process/thread cannot race
                # between the status check and the cancelled-state save.
                with file_lock(meta_path):
                    metadata = self._load_task(task_id)  # re-entrant lock
                    status = str(metadata.get("status") or "").strip().lower()
                    if not task_id or status not in {"processing", "queued"}:
                        continue
                    # File-based cross-process cancellation marker.
                    self._mark_task_cancelled(task_id)
                    metadata["status"] = "cancelled"
                    metadata["stage"] = "cancelled"
                    metadata["last_error"] = "Task cancelled by user."
                    metadata["last_activity_at"] = time.time()
                    self._save_task(task_id, metadata)  # re-entrant lock
                    cancelled_task_ids.append(task_id)
            except (json.JSONDecodeError, OSError, FileNotFoundError) as exc:
                logger.warning("stop_task_meta_skipped", task_id=task_id, error=str(exc))
                continue
        return {
            "cancelled_task_ids": cancelled_task_ids,
            "cancelled_count": len(cancelled_task_ids),
        }

    def resolve_download(self, task_id: str, file_type: str) -> tuple[Path, str]:
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

    def build_download_package(self, task_ids: list[str]) -> tuple[Path, str]:
        normalized_ids: list[str] = []
        seen: set[str] = set()
        for task_id in task_ids:
            cleaned = str(task_id or "").strip()
            if cleaned and cleaned not in seen:
                normalized_ids.append(cleaned)
                seen.add(cleaned)

        if not normalized_ids:
            raise ValueError("No task IDs were provided for packaging.")

        files_to_add: list[tuple[Path, str]] = []
        for task_id in normalized_ids:
            metadata = self._load_task(task_id)
            task_dir = self._task_dir(task_id)
            folder_name = self._archive_name(
                f"{Path(get_safe_filename(metadata.get('original_filename') or task_id)).stem}_{task_id}"
            )

            excel_filename = metadata.get("translated_excel_filename") or metadata.get("excel_filename")
            if excel_filename:
                excel_path = task_dir / excel_filename
                if excel_path.exists():
                    files_to_add.append((excel_path, f"{folder_name}/excel/{excel_path.name}"))

            translated_cad_filename = metadata.get("translated_cad_filename")
            if translated_cad_filename:
                cad_path = task_dir / translated_cad_filename
                if cad_path.exists():
                    files_to_add.append((cad_path, f"{folder_name}/cad/{cad_path.name}"))

        if not files_to_add:
            raise FileNotFoundError("No downloadable CAD task outputs were found for the selected tasks.")

        fd, temp_path = mkstemp(
            prefix="cad-package-",
            suffix=".zip",
            dir=str(self._packages_root()),
        )
        os.close(fd)
        zip_path = Path(temp_path)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for source_path, archive_name in files_to_add:
                archive.write(source_path, archive_name)

        return zip_path, "application/zip"


cad_pipeline_service = CADPipelineService()
