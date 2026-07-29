"""CAD API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.services.alibaba_ai_translation_service import alibaba_ai_translation_service
from app.services.runtime_config_service import runtime_config_service
from app.services.cad_pipeline_service import TaskCancelledError, cad_pipeline_service
from app.utils.file_utils import validate_file
from app.security import require_admin_access


router = APIRouter(prefix="/api/cad", tags=["cad"])


async def _validate_uploaded_cad_file(file: UploadFile) -> None:
    validation = await validate_file(file, get_settings())
    if not validation.get("valid"):
        raise HTTPException(status_code=400, detail=validation.get("error", "Invalid file"))


@router.get("/defaults")
async def get_cad_defaults():
    try:
        return JSONResponse({"success": True, "data": runtime_config_service.get_cad_defaults_summary()})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Get CAD defaults failed: {exc}") from exc


@router.post("/defaults", dependencies=[Depends(require_admin_access)])
async def save_cad_defaults(request: dict):
    try:
        result = runtime_config_service.update_cad_defaults(request or {})
        return JSONResponse({"success": True, "message": result["message"], "data": result["runtime"]})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Save CAD defaults failed: {exc}") from exc


@router.post("/extract")
async def extract_cad_text(
    file: UploadFile = File(...),
    converter_backend: str = Form(default="auto"),
    target_language: str = Form(default="en"),
):
    try:
        await _validate_uploaded_cad_file(file)
        result = await run_in_threadpool(
            cad_pipeline_service.extract_upload,
            uploaded_file=file,
            target_language=target_language,
            converter_backend=converter_backend,
        )
        return JSONResponse(
            {
                "success": True,
                "data": {
                    "task_id": result["task_id"],
                    "text_count": result["text_count"],
                    "translatable_count": result.get("translatable_count", result["text_count"]),
                    "excel_file": result["excel_file_url"],
                    "texts": result["texts"],
                },
            }
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CAD extract failed: {exc}") from exc


@router.post("/apply-translation")
async def apply_translation_to_cad(request: dict):
    """
    将用户提供的翻译应用到 CAD 文件。

    Request body 字段:
      - task_id (str, required): 任务 ID
      - translations (list):     [{"original": ..., "translated": ...}]
      - translation_mode (str):  'replace' 替换原文 (default) | 'add' 在下方追加翻译
      - font_name (str):         字体名称（可选）
      - font_size_reduction (int): 字号缩小量，默认 2
    """
    task_id = request.get("task_id")
    translations = request.get("translations", [])
    translation_mode = request.get("translation_mode", "replace")
    font_name = request.get("font_name") or None
    font_size_reduction = int(request.get("font_size_reduction", 2))

    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required")
    if translation_mode not in ("replace", "add"):
        raise HTTPException(status_code=400, detail="translation_mode must be 'replace' or 'add'")

    try:
        result = await run_in_threadpool(
            cad_pipeline_service.apply_translation,
            task_id=task_id,
            translations=translations,
            translation_mode=translation_mode,
            font_name=font_name,
            font_size_reduction=font_size_reduction,
        )
        return JSONResponse({"success": True, "data": result})
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Apply translation failed: {exc}") from exc


@router.post("/upload")
async def upload_cad_file(
    file: UploadFile = File(...),
    target_language: str = Form(default="en"),
    extract_only: bool = Form(default=False),
    converter_backend: str = Form(default="auto"),
    translation_mode: str = Form(default="replace"),
    font_name: str | None = Form(default=None),
    font_size_reduction: int = Form(default=2),
):
    try:
        await _validate_uploaded_cad_file(file)
        result = await run_in_threadpool(
            cad_pipeline_service.process_upload,
            uploaded_file=file,
            target_language=target_language,
            converter_backend=converter_backend,
            extract_only=extract_only,
            translation_mode=translation_mode,
            font_name=font_name,
            font_size_reduction=font_size_reduction,
        )
        return JSONResponse(
            {
                "success": True,
                "data": {
                    "task_id": result["task_id"],
                    "text_count": result["text_count"],
                    "translation_count": result.get("translation_count", 0),
                    "excel_file": result.get("excel_file_url"),
                    "translated_cad_file": result.get("translated_cad_file"),
                    "texts": result.get("texts", []),
                },
            }
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TaskCancelledError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"CAD upload failed: {exc}") from exc


@router.get("/download/{task_id}/{file_type}")
async def download_file(task_id: str, file_type: str):
    try:
        file_path, media_type = cad_pipeline_service.resolve_download(task_id, file_type)
        return FileResponse(path=str(file_path), media_type=media_type, filename=file_path.name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Download failed: {exc}") from exc


@router.post("/download-package", dependencies=[Depends(require_admin_access)])
async def download_package(request: dict):
    task_ids = request.get("task_ids", [])
    try:
        file_path, media_type = cad_pipeline_service.build_download_package(task_ids)
        return FileResponse(path=str(file_path), media_type=media_type, filename=file_path.name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Package download failed: {exc}") from exc


@router.get("/tasks")
async def list_tasks():
    try:
        return JSONResponse({"success": True, "data": cad_pipeline_service.list_tasks()})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"List tasks failed: {exc}") from exc


@router.post("/tasks/stop-all", dependencies=[Depends(require_admin_access)])
async def stop_all_tasks():
    try:
        result = cad_pipeline_service.stop_all_tasks()
        return JSONResponse({"success": True, "message": "all active tasks stopped", "data": result})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Stop tasks failed: {exc}") from exc


@router.delete("/tasks", dependencies=[Depends(require_admin_access)])
async def clear_all_tasks():
    try:
        cad_pipeline_service.clear_all_tasks()
        return JSONResponse({"success": True, "message": "all tasks cleared"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Clear tasks failed: {exc}") from exc


@router.post("/tasks/{task_id}/resume")
async def resume_task(task_id: str, request: dict):
    """Resume an interrupted or failed CAD task from its last checkpoint."""
    try:
        result = await run_in_threadpool(
            cad_pipeline_service.resume_task,
            task_id=task_id,
            target_language=request.get("target_language", "en"),
            translation_mode=request.get("translation_mode", "replace"),
            font_name=request.get("font_name"),
            font_size_reduction=int(request.get("font_size_reduction", 2)),
        )
        return JSONResponse({"success": True, "data": result})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TaskCancelledError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Resume task failed: {exc}") from exc


@router.get("/tasks/{task_id}/logs")
async def get_task_logs(task_id: str):
    """Get human-readable logs for a CAD task."""
    try:
        logs = await run_in_threadpool(cad_pipeline_service.get_task_logs, task_id)
        return JSONResponse({"success": True, "data": {"logs": logs}})
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Get logs failed: {exc}") from exc


@router.delete("/tasks/{task_id}", dependencies=[Depends(require_admin_access)])
async def delete_task(task_id: str):
    try:
        cad_pipeline_service.delete_task(task_id)
        return JSONResponse({"success": True, "message": f"task {task_id} deleted"})
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Delete task failed: {exc}") from exc


@router.post("/translate-text")
async def translate_text(
    text: str = Form(...),
    target_language: str = Form(default="en"),
):
    if not text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    try:
        translated_text = await run_in_threadpool(
            alibaba_ai_translation_service.translate_text,
            text=text,
            target_lang=target_language,
        )
        return JSONResponse(
            {
                "success": True,
                "data": {
                    "original_text": text,
                    "translated_text": translated_text,
                    "target_language": target_language,
                },
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Translation failed: {exc}") from exc


@router.post("/translate-batch")
async def batch_translate_texts(request: dict):
    texts = request.get("texts", [])
    target_lang = request.get("target_lang", "en")
    if not texts:
        raise HTTPException(status_code=400, detail="texts is required")

    try:
        translated_texts = await run_in_threadpool(
            alibaba_ai_translation_service.translate_batch,
            texts=texts,
            target_lang=target_lang,
        )
        return JSONResponse({"success": True, "data": {"translated_texts": translated_texts}})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Batch translation failed: {exc}") from exc


@router.get("/health")
async def health_check():
    return JSONResponse(
        {
            "success": True,
            "message": "CAD service is healthy",
            "services": {
                "pipeline": "active",
                "translation_service": "active",
            },
        }
    )


@router.put("/dictionary/{task_id}/update")
async def update_dictionary_entry(task_id: str, request: dict):
    return {"success": True, "message": "dictionary update acknowledged", "task_id": task_id, "request": request}
