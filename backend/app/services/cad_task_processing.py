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

class CadTaskProcessingMixin:
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

    def extract_upload(self, uploaded_file: UploadFile, target_language: str = "en", converter_backend: str | None = None) -> dict[str, Any]:
        task_id = self.reserve_upload(uploaded_file, target_language, converter_backend)
        try:
            return self._extract_reserved(task_id)
        except BaseException:
            self._abandon_partial_task(task_id)
            raise

    def _register_uploaded_task(
        self,
        task_id: str,
        uploaded_file: UploadFile,
        suffix: str,
        target_language: str,
        converter_backend: str | None,
        safe_filename: str,
        started_at: float,
    ) -> dict[str, Any]:
        """Perform upload → DWG-convert → extract → first ``_save_task``.

        Caller holds the global creation/clear coordination lock, so this task
        directory cannot be concurrently cleared/reaped while it is being
        populated.
        """
        task_dir = self._task_dir(task_id)
        input_path = task_dir / safe_filename
        if str(getattr(uploaded_file.file, "name", "")) != str(input_path):
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
                    "entity_handle": str(text_info.get("实体句柄") or ""),
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
        registered = self._load_task(task_id)
        metadata = {
            **registered,
            "task_id": task_id,
            "original_filename": safe_filename,
            "normalized_dxf_filename": normalized_dxf_path.name,
            "target_language": target_language,
            "requested_backend": converter_backend or "",
            "resolved_backend": resolved_backend,
            "config_snapshot": registered.get("config_snapshot") or self._capture_config_snapshot(),
            "extract_only": False,
            "status": "processing",
            "stage": "extracted",
            "text_count": len(texts),
            "entity_handles": {t["id"]: t["entity_handle"] for t in texts if t["entity_handle"]},
            "record_originals": {t["id"]: t["original_text"] for t in texts},
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
            "created_at": registered.get("created_at", time.time()),
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

    def _abandon_partial_task(self, task_id: str) -> None:
        """Remove only this failed registration under its stable lifecycle lock."""
        if not task_id:
            return
        with self._task_lifecycle_lock(task_id):
            task_dir = self._task_dir(task_id)
            try:
                if task_dir.exists():
                    self._delete_tree(task_dir)
            except OSError as exc:
                self._update_task(task_id, status="error", stage="failed",
                                  last_error=f"Upload cleanup failed. Close CAD/files and delete this task: {exc}")
                logger.warning("partial_task_cleanup_failed", task_id=task_id, error=str(exc))
        self._clear_task_cancel(task_id)

    def process_upload(self, uploaded_file: UploadFile, target_language="en", converter_backend=None,
                       extract_only=False, translation_mode="replace", font_name=None,
                       font_size_reduction=2):
        task_id = self.reserve_upload(uploaded_file, target_language, converter_backend)
        with self._task_execution_claim(task_id):
            return self._process_registered(task_id, target_language=target_language,
                converter_backend=converter_backend, extract_only=extract_only,
                translation_mode=translation_mode, font_name=font_name,
                font_size_reduction=font_size_reduction)

    def _process_registered(
        self,
        task_id: str,
        target_language: str = "en",
        converter_backend: str | None = None,
        extract_only: bool = False,
        translation_mode: str = "replace",
        font_name: str | None = None,
        font_size_reduction: int = 2,
    ) -> dict[str, Any]:
        self._update_task(task_id, job_options={
            "target_language": target_language, "converter_backend": converter_backend,
            "extract_only": extract_only, "translation_mode": translation_mode,
            "font_name": font_name, "font_size_reduction": font_size_reduction,
        })
        started_at = time.perf_counter()
        try:
            def ensure_not_cancelled() -> None:
                if task_id and self._is_task_cancelled(task_id):
                    raise TaskCancelledError("Task cancelled by user.")

            extract_result = self._extract_reserved(task_id)
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

    def _resume_options(self, task_id, target_language=None, translation_mode=None,
                        font_name=None, font_size_reduction=None):
        metadata = self._load_task(task_id)
        saved = metadata.get("job_options") or {}
        language = metadata.get("target_language") or saved.get("target_language") or "en"
        if target_language is not None and target_language != language:
            raise ValueError("Resume must keep the original target language. Use Restart to change it.")
        if (metadata.get("status") == "done" and metadata.get("stage") == "completed"
                and metadata.get("translated_count", 0) >= metadata.get("text_count", 0)):
            raise ValueError("Task is already completed. Use Restart instead.")
        return {
            "target_language": language,
            "translation_mode": translation_mode if translation_mode is not None else
                metadata.get("translation_mode", saved.get("translation_mode", "replace")),
            "font_name": font_name if font_name is not None else
                metadata.get("font_name", saved.get("font_name")),
            "font_size_reduction": font_size_reduction if font_size_reduction is not None else
                metadata.get("font_size_reduction", saved.get("font_size_reduction", 2)),
        }

    @task_execution
    def resume_task(
        self,
        task_id: str,
        target_language: str | None = None,
        translation_mode: str | None = None,
        font_name: str | None = None,
        font_size_reduction: int | None = None,
        _preserve_cancel: bool = False,
    ) -> dict[str, Any]:
        """Resume an interrupted or failed task from its last checkpoint."""
        validate_task_id(task_id)
        options = self._resume_options(task_id, target_language, translation_mode,
                                       font_name, font_size_reduction)
        target_language = options["target_language"]
        translation_mode = options["translation_mode"]
        font_name = options["font_name"]
        font_size_reduction = options["font_size_reduction"]
        started_at = time.perf_counter()
        if not _preserve_cancel:
            self._clear_task_cancel(task_id)
        if self._is_task_cancelled(task_id):
            raise TaskCancelledError("Task cancelled by user.")
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

        # The durable upload permits recovery before extraction has completed.
        stage = metadata.get("stage", "")
        if stage in ("", "queued") or not metadata.get("excel_filename"):
            self._extract_reserved(task_id)
            metadata = self._load_task(task_id)
            stage = metadata.get("stage", "extracted")

        # Load existing translations checkpoint if available
        checkpoint = self._load_checkpoint(task_id)
        entries = self._load_excel_text_entries(task_id, metadata)
        by_id = {str(t.get("record_id")): t for t in checkpoint if t.get("record_id")}
        by_original = {t.get("original"): t for t in checkpoint if not t.get("record_id")}
        translations = [dict(by_id.get(e["record_id"]) or by_original.get(e["original"]) or
                             {**e, "translated": ""}) for e in entries] if checkpoint else []

        try:
            # If we have a translated CAD file already, task is effectively done
            if metadata.get("translated_cad_filename") and not metadata.get("failed_count") and translations and all(t.get("translated") for t in translations):
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
            if stage in ("extracted", "extracting", "translating", "failed") or not translations or any(not t.get("translated") for t in translations):
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

    @task_execution
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

        Concurrency: the entire write of the translated DXF / translated Excel
        outputs and the metadata write-back happens while holding the per-task
        lifecycle lock.  After confirming the task directory still exists, no
        ``delete_task`` / ``clear_all_tasks`` can interleave (they must acquire
        the *same* lifecycle lock to remove the directory), so a deleted task
        directory is never re-created by a half-finished apply and no orphaned
        half-written DXF/Excel can survive a delete.  ``_update_task`` /
        ``_save_task`` / ``_write_translated_excel`` acquire the same lifecycle
        lock re-entrantly (file_lock is a per-thread RLock), so no deadlock.
        """
        validate_task_id(task_id)
        with self._task_lifecycle_lock(task_id):
            task_dir = self._task_dir(task_id)
            meta_path = self._task_meta_path(task_id)
            if not task_dir.exists() or not meta_path.exists():
                # Task deleted/cleared concurrently while we waited for the lock:
                # do not write any output into (or re-create) its directory.
                raise TaskCancelledError("Task deleted while applying translation.")

            metadata = self._load_task(task_id)  # nested file_lock, re-entrant
            normalized_dxf_path = resolve_within_directory(task_dir, metadata["normalized_dxf_filename"])
            if not normalized_dxf_path.exists():
                raise FileNotFoundError(f"Normalized DXF is missing for task {task_id}")

            translation_map: dict[str, str] = {}
            records: dict[str, str] = {}
            handles = metadata.get("entity_handles") or {}
            for item in translations:
                original = (item.get("original") or "").strip()
                translated = (item.get("translated") or "").strip()
                if original and translated:
                    record_id = item.get("record_id")
                    if record_id and handles:
                        if record_id not in handles:
                            raise ValueError(f"Unknown translation record: {record_id}")
                        records[record_id] = translated
                    else:
                        if original in translation_map and translation_map[original] != translated:
                            raise ValueError("Conflicting translations for the same text require record_id")
                        translation_map[original] = translated

            if not translation_map and not records:
                raise ValueError("No non-empty translations were provided.")

            entity_translations = {
                handle: records.get(record_id, translation_map.get((metadata.get("record_originals") or {}).get(record_id, ""), ""))
                for record_id, handle in handles.items()
            }
            entity_translations = {handle: value for handle, value in entity_translations.items() if value}
            applied_count = len(entity_translations) if handles else len(translation_map)

            resolved_font = font_name or self.settings.DEFAULT_FONT_NAME
            translated_filename = f"translated_{normalized_dxf_path.name}"

            # 使用新的 TextApplier 功能模块（通过 pipeline 调用）写入 translated DXF
            # 输出到 task_dir —— 全程持有 per-task lifecycle lock。
            self._pipeline.run_apply_only(
                dxf_file=str(normalized_dxf_path),
                task_dir=str(task_dir),
                translation_map=translation_map,
                translation_mode=translation_mode,
                font_name=resolved_font,
                font_size_reduction=font_size_reduction,
                entity_translations=entity_translations or None,
            )
            # 写 translated Excel 输出到 task_dir（同样在 lifecycle lock 内）。
            translated_excel_path = self._write_translated_excel(task_id, translation_map, records)

            metadata["translation_count"] = applied_count
            metadata["translated_count"] = applied_count
            metadata["translated_cad_filename"] = translated_filename
            metadata["translated_excel_filename"] = translated_excel_path.name
            metadata["translation_mode"] = translation_mode
            metadata["font_name"] = resolved_font
            metadata["font_size_reduction"] = font_size_reduction
            self._save_task(task_id, metadata)  # nested lifecycle+file_lock

        return {
            "task_id": task_id,
            "translation_count": applied_count,
            "translation_mode": translation_mode,
            "font_name": resolved_font,
            "font_size_reduction": font_size_reduction,
            "translated_cad_file": f"/api/cad/download/{task_id}/translated_cad",
        }
