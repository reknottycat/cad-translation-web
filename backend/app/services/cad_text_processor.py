"""Compatibility facade over the canonical CAD stage implementations."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.functions.dwg_converter import DWGConverter
from app.functions.text_extractor import TextExtractor
from app.functions.text_applier import TextApplier


class CADTextProcessor:
    def __init__(self):
        self.settings = get_settings()

    def extract_texts_to_excel(self, dxf_file_path: str, output_dir: str):
        return TextExtractor().extract_to_excel(dxf_file_path, output_dir)

    def _extract_texts_from_space(self, space, space_name):
        return TextExtractor()._extract_from_space(space, space_name)

    def _extract_text_from_entity(self, entity, space_name):
        return TextExtractor()._extract_entity(entity, space_name)

    def apply_translation_to_dxf(self, dxf_file_path, excel_file_path=None, output_file_path="",
                                 font_name="Times New Roman", translation_mode="add",
                                 font_size_reduction=4, translation_map=None):
        if translation_map is None:
            translation_map = self._load_translation_map(excel_file_path)
        return TextApplier().apply(dxf_file_path, output_file_path, translation_map,
                                    translation_mode, font_name, font_size_reduction)

    def _load_translation_map(self, excel_path):
        df = pd.read_excel(excel_path).fillna("")
        if "原文" not in df or "译文" not in df:
            raise ValueError("Excel must contain 原文 and 译文 columns")
        return {str(row["原文"]).strip(): str(row["译文"]).strip()
                for _, row in df.iterrows() if str(row["译文"]).strip()}

    async def process_cad_file(self, input_file, target_language="en", extract_only=False):
        from fastapi import UploadFile
        from app.services.cad_pipeline_service import cad_pipeline_service
        with Path(input_file).open("rb") as source:
            return await run_in_threadpool(cad_pipeline_service.process_upload,
                UploadFile(filename=Path(input_file).name, file=source),
                target_language=target_language, extract_only=extract_only)

    def _convert_dwg_to_dxf(
        self,
        dwg_file_path: str,
        temp_dir: Path,
        backend_override: Optional[str] = None,
    ) -> str:
        """Convert DWG to DXF using configured backend."""
        converter = DWGConverter(
            converter_backend=self.settings.DWG_CONVERTER_BACKEND,
            dwg_auto_backends=self.settings.DWG_AUTO_BACKENDS,
            dwg_disabled_backends=self.settings.DWG_DISABLED_BACKENDS,
            oda_path=self.settings.ODA_FILE_CONVERTER_PATH,
            oda_output_version=self.settings.ODA_OUTPUT_VERSION,
            oda_output_format=self.settings.ODA_OUTPUT_FORMAT,
            cad_converter_timeout=self.settings.CAD_CONVERTER_TIMEOUT,
            libredwg_dwg2dxf_path=self.settings.LIBREDWG_DWG2DXF_PATH,
            libredwg_install_dir=self.settings.LIBREDWG_INSTALL_DIR,
            libredwg_download_url=self.settings.LIBREDWG_DOWNLOAD_URL,
            libredwg_auto_download=self.settings.LIBREDWG_AUTO_DOWNLOAD,
        )
        return converter.convert(
            dwg_file_path=str(dwg_file_path),
            output_dir=temp_dir,
            backend_override=backend_override,
        )


cad_text_processor = CADTextProcessor()
