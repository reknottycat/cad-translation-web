#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Translation API routes."""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config import get_settings
from app.utils.file_utils import get_safe_filename, resolve_within_directory
from app.schemas.translation import (
    BatchTranslationRequest,
    ExcelTranslationResponse,
    RuntimeConfigUpdateRequest,
    RuntimeConnectionTestResponse,
    TranslationRequest,
    TranslationResponse,
    TranslationStatsResponse,
)
from app.services.alibaba_ai_translation_service import (
    alibaba_ai_excel_processor,
    alibaba_ai_translation_service,
)
from app.services.llm.translation_service import list_provider_presets, llm_translation_service, add_custom_provider, delete_custom_provider
from app.services.runtime_config_service import runtime_config_service
from app.services.tasks.translation_tasks import translate_excel_task
from app.schemas.translation import CustomProviderPayload


logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/translation", tags=["translation"])
settings = get_settings()


@router.post("/glossary/upload")
async def upload_glossary_file(file: UploadFile = File(...)):
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="glossary filename is required")

        suffix = Path(file.filename).suffix.lower()
        if suffix not in {".csv", ".xlsx", ".xls"}:
            raise HTTPException(status_code=400, detail="only .csv/.xlsx/.xls glossary files are supported")

        glossary_dir = settings.get_upload_path() / "glossaries"
        glossary_dir.mkdir(parents=True, exist_ok=True)
        safe_stem = Path(get_safe_filename(file.filename)).stem.replace(" ", "_")
        saved_name = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{safe_stem}{suffix}"
        saved_path = glossary_dir / saved_name

        with open(saved_path, "wb") as buffer:
            buffer.write(await file.read())

        return {
            "success": True,
            "message": "glossary uploaded",
            "filename": file.filename,
            "saved_path": str(saved_path),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("upload_glossary_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"glossary upload failed: {exc}")


@router.post("/text", response_model=TranslationResponse)
async def translate_text(request: TranslationRequest):
    try:
        translated_text = alibaba_ai_translation_service.translate_text(
            text=request.text,
            source_lang=request.source_lang,
            target_lang=request.target_lang,
        )
        return TranslationResponse(
            original_text=request.text,
            translated_text=translated_text,
            source_lang=request.source_lang,
            target_lang=request.target_lang,
            success=not translated_text.startswith("[translation_error]"),
        )
    except Exception as exc:
        logger.error("translate_text_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"translation failed: {exc}")


@router.post("/batch", response_model=List[TranslationResponse])
async def translate_batch(request: BatchTranslationRequest):
    try:
        if len(request.texts) > 100:
            raise HTTPException(status_code=400, detail="max batch size is 100")

        translated_texts = alibaba_ai_translation_service.translate_batch(
            texts=request.texts,
            source_lang=request.source_lang,
            target_lang=request.target_lang,
        )
        return [
            TranslationResponse(
                original_text=original,
                translated_text=translated,
                source_lang=request.source_lang,
                target_lang=request.target_lang,
                success=not str(translated).startswith("[translation_error]"),
            )
            for original, translated in zip(request.texts, translated_texts)
        ]
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("translate_batch_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"batch translation failed: {exc}")


@router.post("/excel", response_model=ExcelTranslationResponse)
async def translate_excel_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    text_columns: Optional[str] = Form(None),
    source_lang: str = Form("auto"),
    target_lang: str = Form("en"),
    translation_mode: str = Form("add"),
):
    try:
        if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
            raise HTTPException(status_code=400, detail="only .xlsx/.xls is supported")

        columns_list = None
        if text_columns:
            columns_list = [col.strip() for col in text_columns.split(",") if col.strip()]

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as temp_input:
            temp_input.write(await file.read())
            temp_input_path = temp_input.name

        output_filename = f"translated_{get_safe_filename(file.filename)}"
        output_path = settings.get_output_path() / output_filename

        try:
            stats = alibaba_ai_excel_processor.translate_excel_file(
                input_file_path=temp_input_path,
                output_file_path=str(output_path),
                text_columns=columns_list,
                source_lang=source_lang,
                target_lang=target_lang,
                translation_mode=translation_mode,
            )
            report_path = alibaba_ai_excel_processor.create_translation_report(stats, str(output_path))
            background_tasks.add_task(os.unlink, temp_input_path)
            return ExcelTranslationResponse(
                success=True,
                message="excel translation completed",
                output_filename=output_filename,
                download_url=f"/api/translation/download/{output_filename}",
                report_filename=os.path.basename(report_path) if report_path else None,
                stats=TranslationStatsResponse(**stats),
            )
        except Exception:
            if os.path.exists(temp_input_path):
                os.unlink(temp_input_path)
            raise
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("translate_excel_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"excel translation failed: {exc}")


@router.post("/excel/async", response_model=Dict[str, Any])
async def translate_excel_file_async(
    file: UploadFile = File(...),
    text_columns: Optional[str] = Form(None),
    source_lang: str = Form("auto"),
    target_lang: str = Form("en"),
    translation_mode: str = Form("add"),
):
    try:
        if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
            raise HTTPException(status_code=400, detail="only .xlsx/.xls is supported")

        # 使用唯一文件名（UUID 前缀）避免同名文件相互覆盖，造成异步任务读取到错误文件。
        safe_stem = Path(get_safe_filename(file.filename)).stem.replace(" ", "_")
        suffix = Path(file.filename).suffix.lower()
        unique_filename = f"{uuid.uuid4().hex}_{safe_stem}{suffix}"
        upload_path = settings.get_upload_path() / unique_filename
        with open(upload_path, "wb") as buffer:
            buffer.write(await file.read())

        columns_list = None
        if text_columns:
            columns_list = [col.strip() for col in text_columns.split(",") if col.strip()]

        task = translate_excel_task.delay(
            input_file_path=str(upload_path),
            text_columns=columns_list,
            source_lang=source_lang,
            target_lang=target_lang,
            translation_mode=translation_mode,
        )
        return {"task_id": task.id, "status": "submitted", "message": "task submitted"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("translate_excel_async_submit_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"task submit failed: {exc}")


@router.get("/task/{task_id}")
async def get_translation_task_status(task_id: str):
    try:
        from app.services.celery_app import celery_app

        task = celery_app.AsyncResult(task_id)
        if task.state == "PENDING":
            return {"task_id": task_id, "state": task.state, "status": "pending", "message": "queued"}
        if task.state == "PROGRESS":
            return {
                "task_id": task_id,
                "state": task.state,
                "status": "processing",
                "current": task.info.get("current", 0),
                "total": task.info.get("total", 1),
                "message": task.info.get("status", "processing"),
            }
        if task.state == "SUCCESS":
            return {
                "task_id": task_id,
                "state": task.state,
                "status": "completed",
                "result": task.info,
                "message": "done",
            }
        return {
            "task_id": task_id,
            "state": task.state,
            "status": "failed",
            "error": str(task.info),
            "message": "failed",
        }
    except Exception as exc:
        logger.error("task_status_failed", task_id=task_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"task status failed: {exc}")


@router.get("/download/{filename}")
async def download_translated_file(filename: str):
    try:
        file_path = resolve_within_directory(settings.get_output_path(), filename)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="file not found")
        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("download_failed", filename=filename, error=str(exc))
        raise HTTPException(status_code=500, detail=f"download failed: {exc}")


@router.get("/languages")
async def get_supported_languages():
    return {
        "languages": settings.SUPPORTED_LANGUAGES,
        "default_source": settings.DEFAULT_SOURCE_LANGUAGE,
        "default_target": settings.DEFAULT_TARGET_LANGUAGE,
    }


@router.get("/providers")
async def get_provider_presets():
    return {
        "active": runtime_config_service.get_public_runtime_summary(),
        "presets": list_provider_presets(),
        "note": "Some providers advertise free tiers or trial credits. Availability changes over time.",
    }


@router.post("/providers/custom")
async def save_custom_provider(request: CustomProviderPayload):
    try:
        add_custom_provider(
            provider_id=request.id,
            name=request.name,
            base_url=request.base_url,
            default_model=request.default_model,
            notes=request.notes or "Custom provider",
        )
        return {"success": True, "message": "Custom provider added"}
    except Exception as exc:
        logger.error("save_custom_provider_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to add custom provider: {exc}")


@router.delete("/providers/custom/{provider_id}")
async def remove_custom_provider(provider_id: str):
    success = delete_custom_provider(provider_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot delete built-in or non-existent provider.")
    return {"success": True, "message": "Custom provider deleted"}


@router.get("/config")
async def get_translation_config():
    return {
        "supported_languages": settings.SUPPORTED_LANGUAGES,
        "default_source_language": settings.DEFAULT_SOURCE_LANGUAGE,
        "default_target_language": settings.DEFAULT_TARGET_LANGUAGE,
        "translation_modes": {"add": "append translation", "replace": "replace original"},
        "max_batch_size": 100,
        "supported_file_types": [".xlsx", ".xls"],
        "runtime": runtime_config_service.get_public_runtime_summary(),
        "cad_defaults": runtime_config_service.get_cad_defaults_summary(),
        "provider_presets": list_provider_presets(),
    }


@router.post("/config")
async def save_translation_config(request: RuntimeConfigUpdateRequest):
    try:
        return runtime_config_service.update_runtime_config(request.model_dump(exclude_none=False))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("save_translation_config_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"save config failed: {exc}")


@router.post("/test-connection", response_model=RuntimeConnectionTestResponse)
async def test_translation_connection(request: RuntimeConfigUpdateRequest):
    try:
        return RuntimeConnectionTestResponse(
            **runtime_config_service.test_connection(request.model_dump(exclude_none=True))
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("translation_connection_test_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"connection test failed: {exc}")
