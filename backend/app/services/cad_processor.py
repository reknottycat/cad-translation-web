"""Compatibility facade over the canonical CAD pipeline.

The SQL/Celery routes historically imported ``CADProcessor``.  This class now
delegates to the maintained pipeline and stage implementations instead of
returning simulated files that were never created.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import structlog
from fastapi import UploadFile

from app.config import get_settings
from app.functions.text_applier import TextApplier
from app.functions.text_extractor import TextExtractor
from app.services.cad_text_processor import cad_text_processor

logger = structlog.get_logger(__name__)


class CADProcessingError(RuntimeError):
    """Raised when a canonical CAD stage cannot complete."""


class CADProcessor:
    """Keep old method names while routing all work to maintained code."""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def process_cad_file(
        self,
        input_file: str | None = None,
        output_dir: str | None = None,
        auto_translate: bool = True,
        target_language: str = "en",
        *,
        file_path: str | None = None,
        extract_only: bool | None = None,
        converter_backend: str | None = None,
        translation_mode: str = "replace",
        font_name: str | None = None,
        font_size_reduction: float = 2.0,
        **_legacy: Any,
    ) -> dict[str, Any]:
        """Process one path through ``CADPipelineService.process_upload``.

        ``file_path`` remains an accepted alias for old task callers.  The
        canonical pipeline owns output placement, task state, conversion,
        extraction, translation, and backfill.
        """
        source_path = Path(input_file or file_path or "")
        if not source_path.is_file():
            raise FileNotFoundError(f"CAD input file does not exist: {source_path}")
        from app.services.cad_pipeline_service import cad_pipeline_service

        effective_extract_only = (
            bool(extract_only) if extract_only is not None else not auto_translate
        )
        with source_path.open("rb") as source:
            upload = UploadFile(filename=source_path.name, file=source)
            try:
                return await asyncio.to_thread(
                    cad_pipeline_service.process_upload,
                    upload,
                    target_language,
                    converter_backend,
                    effective_extract_only,
                    translation_mode,
                    font_name,
                    font_size_reduction,
                )
            finally:
                await upload.close()

    async def convert_dwg_to_dxf(
        self, dwg_file: str, output_dir: str
    ) -> dict[str, Any]:
        return await self._convert_dwg_to_dxf(dwg_file, output_dir)

    async def _convert_dwg_to_dxf(
        self, dwg_file: str, output_dir: str
    ) -> dict[str, Any]:
        try:
            output = await asyncio.to_thread(
                cad_text_processor._convert_dwg_to_dxf,
                dwg_file,
                Path(output_dir),
                None,
            )
            return {
                "success": True,
                "message": "DWG conversion completed",
                "output_file": str(output),
            }
        except Exception as exc:
            raise CADProcessingError(
                f"DWG conversion failed for {dwg_file}: {exc}"
            ) from exc

    async def extract_texts_from_dxf(
        self, dxf_file: str, output_dir: str
    ) -> dict[str, Any]:
        return await self._extract_text_from_dxf(dxf_file, output_dir)

    async def _extract_text_from_dxf(
        self, dxf_file: str, output_dir: str
    ) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(
                TextExtractor().extract_to_excel, dxf_file, output_dir
            )
            count = len(result.get("texts") or [])
            return {
                **result,
                "success": True,
                "message": f"Extracted {count} text entities",
                "excel_file": result.get("output_file"),
                "texts_count": count,
                "text_count": count,
            }
        except Exception as exc:
            raise CADProcessingError(
                f"Text extraction failed for {dxf_file}: {exc}"
            ) from exc

    async def apply_translation_to_dxf(
        self,
        dxf_file: str,
        excel_file: str,
        output_dir: str,
        font_name: str = "Times New Roman",
        translation_mode: str = "replace",
        font_size_reduction: float = 2.0,
    ) -> dict[str, Any]:
        return await self._apply_translations_to_cad(
            dxf_file,
            excel_file,
            output_dir,
            font_name,
            translation_mode,
            font_size_reduction,
        )

    async def _apply_translations_to_cad(
        self,
        dxf_file: str,
        translated_excel: str,
        output_dir: str,
        font_name: str = "Times New Roman",
        translation_mode: str = "replace",
        font_size_reduction: float = 2.0,
    ) -> dict[str, Any]:
        try:
            translation_map = cad_text_processor._load_translation_map(
                translated_excel
            )
            output_path = Path(output_dir) / f"{Path(dxf_file).stem}_translated.dxf"
            result = await asyncio.to_thread(
                TextApplier().apply,
                dxf_file,
                str(output_path),
                translation_map,
                translation_mode,
                font_name,
                font_size_reduction,
            )
            return {
                **result,
                "success": True,
                "translation_count": int(
                    result.get("translated_entities") or len(translation_map)
                ),
            }
        except Exception as exc:
            raise CADProcessingError(
                f"Translation apply failed for {dxf_file}: {exc}"
            ) from exc

    async def process_project_files(
        self,
        project_id: int,
        file_paths: list[str],
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Process every legacy SQL project file with per-file truth."""
        options = dict(config or {})
        results: list[dict[str, Any]] = []
        for file_path in file_paths:
            try:
                result = await self.process_cad_file(
                    input_file=file_path,
                    auto_translate=bool(options.get("auto_translate", True)),
                    target_language=str(
                        options.get("target_language")
                        or options.get("target_lang")
                        or "en"
                    ),
                    converter_backend=options.get("converter_backend"),
                    translation_mode=str(options.get("translation_mode") or "replace"),
                    font_name=options.get("font_name"),
                    font_size_reduction=float(options.get("font_size_reduction") or 2.0),
                )
                results.append(
                    {"file_path": file_path, "success": True, "result": result}
                )
            except Exception as exc:
                logger.error(
                    "legacy_project_file_failed",
                    project_id=project_id,
                    file=file_path,
                    error=str(exc),
                )
                results.append(
                    {"file_path": file_path, "success": False, "error": str(exc)}
                )
        succeeded = sum(1 for item in results if item["success"])
        failed = len(results) - succeeded
        return {
            "success": failed == 0,
            "project_id": project_id,
            "total_files": len(results),
            "converted_files": succeeded,
            "successful_files": succeeded,
            "failed_files": failed,
            "processed_files": results,
        }


cad_processor = CADProcessor()
