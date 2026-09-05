"""Glossary loading and prompt composition for CAD translation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


CAD_SPECIALIZED_SYSTEM_PROMPT = (
    "You are a professional CAD drawing translation specialist. "
    "Preserve engineering meaning, drawing codes, units, tag numbers, and punctuation. "
    "Use concise domain terminology, keep repeated labels consistent, and output translated text only."
)


class LLMPromptMixin:
    def _load_glossary_records(
        self, glossary_file: str | None
    ) -> list[tuple[str, str]]:
        if not glossary_file:
            return []
        path = Path(glossary_file)
        if not path.is_absolute():
            path = (self.settings.BASE_DIR / path).resolve()
        if not path.exists():
            return []
        if path.suffix.lower() == ".csv":
            frame = None
            last_error: Exception | None = None
            for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
                try:
                    frame = pd.read_csv(
                        path, dtype=str, encoding=encoding, header=None
                    ).fillna("")
                    break
                except UnicodeDecodeError as exc:
                    last_error = exc
                except (pd.errors.EmptyDataError, pd.errors.ParserError):
                    return []
            if frame is None:
                if last_error is not None:
                    self._logger.warning(
                        "glossary_undecodable_file",
                        path=str(path),
                        error=str(last_error),
                    )
                return []
        elif path.suffix.lower() in {".xlsx", ".xls"}:
            frame = pd.read_excel(path, dtype=str, header=None).fillna("")
        else:
            return []
        if frame.empty or frame.shape[1] < 2:
            return []
        header_words = {
            "原文", "译文", "术语", "中文", "英文", "source", "target",
            "term", "translation", "from", "to", "原文/术语", "英文/中文",
        }
        first_source = str(frame.iloc[0, 0]).strip().casefold()
        first_target = str(frame.iloc[0, 1]).strip().casefold()
        start = 1 if first_source in header_words or first_target in header_words else 0
        records: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for index in range(start, len(frame)):
            pair = (
                str(frame.iloc[index, 0]).strip(),
                str(frame.iloc[index, 1]).strip(),
            )
            if not pair[0] or not pair[1] or pair in seen:
                continue
            seen.add(pair)
            records.append(pair)
        return records

    def _select_glossary_records(
        self,
        records: list[tuple[str, str]],
        texts: list[str],
        limit: int = 30,
    ) -> list[tuple[str, str]]:
        if not records:
            return []
        haystack = "\n".join(texts).casefold()
        if not haystack.strip():
            return records[:limit]
        matched = [pair for pair in records if pair[0].casefold() in haystack]
        return matched[:limit] if matched else records[: min(limit, 12)]

    @staticmethod
    def _format_glossary_block(records: list[tuple[str, str]]) -> str:
        return "\n".join(f"- {source} => {target}" for source, target in records)

    def _infer_terminology_preferences(
        self, texts: list[str], source_lang: str, target_lang: str
    ) -> str:
        samples = [text.strip() for text in texts if text and text.strip()][:30]
        if len(samples) < 2:
            return ""
        try:
            return self._chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "You analyze CAD labels and infer likely translation terminology preferences. "
                            "Return only short practical guidance, at most 4 bullet points."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Based on these sample CAD labels from {source_lang} to {target_lang}, "
                            "infer likely terminology preferences that should stay consistent:\n\n"
                            + "\n".join(samples)
                        ),
                    },
                ]
            ).strip()
        except Exception as exc:
            self._logger.warning("terminology_inference_failed", error=str(exc))
            return ""

    def _compose_system_prompt(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        *,
        enable_inference: bool,
    ) -> str:
        cfg = self._active_config()
        mode = cfg["system_prompt_mode"]
        if mode == "custom" and cfg["custom_system_prompt"]:
            base = cfg["custom_system_prompt"]
        elif mode == "cad_specialized":
            base = CAD_SPECIALIZED_SYSTEM_PROMPT
        else:
            base = cfg["system_prompt"]
        sections = [base]
        selected = self._select_glossary_records(
            self._load_glossary_records(cfg["glossary_file"]), texts
        )
        if selected:
            sections.append(
                "Preferred glossary terms. When applicable, these terms take priority:\n"
                + self._format_glossary_block(selected)
            )
        if enable_inference and mode == "default":
            inferred = self._infer_terminology_preferences(
                texts, source_lang, target_lang
            )
            if inferred:
                sections.append(
                    "Likely terminology preferences inferred from the current task:\n"
                    + inferred
                )
        return "\n\n".join(
            section.strip() for section in sections if section and section.strip()
        )
