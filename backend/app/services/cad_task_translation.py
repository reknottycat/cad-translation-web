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

class CadTaskTranslationMixin:
    def _docutranslate_work_root(self) -> Path:
        """Stable sibling directory for per-run DocuTranslate working artifacts.

        ``delete_task`` / ``clear_all_tasks`` only ever remove task directories
        under ``cad_tasks/`` and external cancel markers under
        ``cad_cancel_marks/``.  DocuTranslate's intermediate JSON artifacts
        (``cad_records.json`` / translated JSON) are written here — *outside*
        the task tree — so a running worker can never recreate a deleted task
        directory by writing its working files.  The ``cad_work/`` root is
        never removed by delete/clear; each per-run staging subdirectory is
        removed by the worker in a ``finally`` block after translation.
        """
        root = self.settings.get_output_path() / "cad_work" / "docutranslate"
        root.mkdir(parents=True, exist_ok=True)
        return root

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
                    if k == "provider_api_keys" and isinstance(v, dict):
                        out[k] = {provider: "***" for provider in v}
                    elif isinstance(k, str) and k.strip().lower().replace("-", "_") in {
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
        checkpoint_items = {self._translation_identity(t): dict(t) for t in self._load_checkpoint(task_id)}
        original_records: dict[str, list[str]] = {}
        for index, original in enumerate(original_texts):
            record = record_ids[index] if record_ids else ""
            item = {"original": original, "translated": ""}
            if record:
                item["record_id"] = record
            key = self._translation_identity(item)
            checkpoint_items.setdefault(key, item)
            original_records.setdefault(original, []).append(key)
        self._save_checkpoint(task_id, list(checkpoint_items.values()))

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
                        value = translated if translated and not translated.startswith("[translation_error]") else ""
                        for key in original_records.get(original, []):
                            checkpoint_items[key]["translated"] = value
                    self._save_checkpoint(task_id, list(checkpoint_items.values()))
            elif event == "completed":
                self._append_log(task_id, f"翻译完成: 共翻译 {translated} 条文本")
                self._save_checkpoint(task_id, list(checkpoint_items.values()))

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
        for index, original in enumerate(original_texts):
            translated = translated_texts[index] if index < len(translated_texts) else ""
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
        # Preserve earlier successful records when this execution retries only a subset.
        checkpoint_items.update({self._translation_identity(t): t for t in translations})
        self._save_checkpoint(task_id, list(checkpoint_items.values()))
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
        # DocuTranslate writes intermediate JSON artifacts (cad_records.json /
        # translated JSON) into its ``working_dir``.  These are *purely
        # intermediate* — the method consumes them in-memory to build
        # ``translations``, then persists only the lifecycle-locked checkpoint.
        #
        # Historically the working_dir was ``<task_dir>/docutranslate``, and the
        # adapter unconditionally ``mkdir(parents=True, exist_ok=True)`` there.
        # ``process_upload`` / ``resume_task`` hold no per-task lifecycle lock
        # between ``ensure_not_cancelled()`` and that write, so
        # ``delete_task`` / ``clear_all_tasks`` could remove ``task_dir`` first
        # and the still-running worker would then *re-create* the deleted task
        # directory (plus orphan ``docutranslate`` files) by its mkdir/write.
        #
        # Fix: run DocuTranslate in a per-run staging directory *outside* the
        # task tree (``outputs/cad_work/docutranslate``), which delete/clear
        # never remove.  A worker therefore can never recreate a deleted
        # task_dir by writing DocuTranslate artifacts.  All task-dir products
        # (task.json / task.log / checkpoint) are still written through the
        # existing lifecycle-locked helpers (``_save_checkpoint`` /
        # ``_update_task`` / ``_append_log``) that skip when the task dir is
        # gone — so nothing is recreated after deletion.
        adapter = self._build_docutranslate_adapter(runtime, target_language)
        effective_record_ids = record_ids or [f"{task_id}_{index}" for index in range(len(original_texts))]
        records = [
            CadTextRecord(record_id=record_id, source_text=source_text)
            for record_id, source_text in zip(effective_record_ids, original_texts)
            if source_text and source_text.strip()
        ]

        self._append_log(
            task_id,
            f"开始翻译: {len(records)} 条文本, 执行路径=DocuTranslate (外部临时工作区)",
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

        # Staging dir is external to the task tree, so delete/clear cannot
        # race it and no deleted task_dir is recreated.
        staging_dir = Path(mkdtemp(prefix=f"{task_id}_", dir=str(self._docutranslate_work_root())))
        try:
            batch_result = adapter.translate_records(records, working_dir=staging_dir)
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

            # Lifecycle-protected checkpoint write: a no-op when the task was
            # deleted concurrently, so no orphan checkpoint is recreated.
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
                f"DocuTranslate 翻译完成: {successful} 条成功, {failed_count} 条失败, "
                f"artifacts={batch_result.translated_json_path.name}",
            )
            return translations
        finally:
            # Best-effort cleanup of the external per-run staging directory.
            shutil.rmtree(staging_dir, ignore_errors=True)
