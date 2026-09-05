"""Excel facade for the unified LLM translation service."""

from __future__ import annotations

from typing import Any

import pandas as pd


class LLMExcelTranslationProcessor:
    def __init__(self, service: Any | None = None) -> None:
        if service is None:
            from .translation_service import LLMTranslationService

            service = LLMTranslationService()
        self.service = service

    @staticmethod
    def _detect_text_columns(frame: pd.DataFrame) -> list[str]:
        columns: list[str] = []
        for column in frame.columns:
            if frame[column].dtype != "object":
                continue
            sample = frame[column].dropna().astype(str).head(10)
            if not sample.empty and any(
                any(char.isalpha() or "\u4e00" <= char <= "\u9fff" for char in text)
                for text in sample
            ):
                columns.append(column)
        return columns

    def translate_excel_file(
        self,
        input_file_path: str,
        output_file_path: str,
        text_columns: list[str] | None = None,
        source_lang: str = "auto",
        target_lang: str = "en",
        translation_mode: str = "add",
    ) -> dict[str, Any]:
        frame = pd.read_excel(input_file_path)
        text_columns = text_columns or self._detect_text_columns(frame)
        stats = {
            "total_rows": len(frame),
            "text_columns": text_columns,
            "translated_cells": 0,
            "skipped_cells": 0,
            "error_cells": 0,
        }
        for column in text_columns:
            if column not in frame.columns:
                continue
            values = frame[column].fillna("").astype(str).tolist()
            translated = self.service.translate_batch(
                values, source_lang=source_lang, target_lang=target_lang
            )
            cleaned: list[str] = []
            for original, target in zip(values, translated):
                if not original.strip():
                    stats["skipped_cells"] += 1
                elif target.startswith("[translation_error]"):
                    stats["error_cells"] += 1
                else:
                    stats["translated_cells"] += 1
                cleaned.append(
                    "" if target.startswith("[translation_error]") else target
                )
            if translation_mode == "replace":
                frame[column] = cleaned
            else:
                frame[f"{column}_translated"] = cleaned
        frame.to_excel(output_file_path, index=False)
        stats.update(
            {
                "sheets_processed": 1,
                "rows_translated": len(frame),
                "columns_translated": len(text_columns),
                "successful_translations": stats["translated_cells"],
                "failed_translations": stats["error_cells"],
            }
        )
        return stats

    def create_translation_report(
        self, stats: dict[str, Any], output_path: str
    ) -> str:
        summary = self.service.get_runtime_summary()
        report = {
            "engine": "unified-llm-translation-service",
            "provider": summary["provider"],
            "model": summary["model"],
            "total_rows": stats["total_rows"],
            "translated_cells": stats["translated_cells"],
            "skipped_cells": stats["skipped_cells"],
            "error_cells": stats["error_cells"],
        }
        pd.DataFrame(list(report.items()), columns=["item", "value"]).to_excel(
            output_path.replace(".xlsx", "_translation_report.xlsx"), index=False
        )
        return output_path.replace(".xlsx", "_translation_report.xlsx")
