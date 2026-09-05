#!/usr/bin/env python3
"""Public facade for the unified LLM translation engine."""

from __future__ import annotations

import json
import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any, Callable

import structlog

from app.config import get_settings

from .config_support import LLMConfigMixin
from .excel_processor import LLMExcelTranslationProcessor
from .gateway import LLMGatewayMixin
from .prompt_support import CAD_SPECIALIZED_SYSTEM_PROMPT, LLMPromptMixin
from .providers import (
    BUILTIN_PROVIDER_IDS,
    PROVIDER_PRESETS,
    ProviderPreset,
    add_custom_provider,
    delete_custom_provider,
    list_provider_presets,
    load_custom_providers,
    refresh_custom_providers,
    save_custom_providers,
)
from .rate_limit import TokenBucket, _TokenBucket
from .transport import shared_transport

logger = structlog.get_logger(__name__)


class LLMTranslationService(LLMConfigMixin, LLMPromptMixin, LLMGatewayMixin):
    """Translate CAD text through configured providers and ordered fallbacks."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._logger = logger
        self._thread_local = threading.local()
        self._transport = shared_transport
        self._rate_lock = threading.Lock()
        self._rate_buckets: dict[tuple[Any, ...], TokenBucket] = {}
        self._probe_lock = threading.Lock()
        self._probe_cache: dict[
            tuple[str, str, str, str, str], tuple[float, dict[str, Any]]
        ] = {}
        self._probe_credentials: dict[tuple[str, str, str, str], str] = {}
        self._probe_inflight: dict[
            tuple[str, str, str, str, str], threading.Event
        ] = {}
        self._probe_ttl_seconds = 300.0
        self._probe_event_factory = threading.Event

    def translate_text(
        self,
        text: str,
        source_lang: str = "auto",
        target_lang: str = "en",
        system_prompt_override: str | None = None,
    ) -> str:
        if not text or not text.strip():
            return text
        prompt = (
            f"Translate from {source_lang} to {target_lang}. "
            "Return translated text only, keep units/codes/symbols unchanged:\n\n"
            f"{text}"
        )
        system_prompt = system_prompt_override or self._compose_system_prompt(
            [text], source_lang, target_lang, enable_inference=False
        )
        try:
            translated = self._chat(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ]
            )
            return self._strip_think_tags(translated)
        except Exception as exc:
            self._ensure_not_cancelled()
            logger.error("translate_text_failed", error=str(exc))
            return f"[translation_error]{text}"

    @staticmethod
    def _extract_json_block(content: str) -> str:
        stripped = content.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 3:
                return "\n".join(lines[1:-1]).strip()
        return stripped

    @staticmethod
    def _strip_think_tags(text: str) -> str:
        if not text:
            return text
        while True:
            start = text.lower().find("<think>")
            if start < 0:
                break
            end = text.lower().find("</think>", start)
            if end < 0:
                text = text[:start]
                break
            prefix, suffix = text[:start], text[end + 8 :]
            text = (
                prefix.rstrip() + " " + suffix.lstrip()
                if prefix.rstrip() and suffix.lstrip()
                else prefix + suffix
            )
        return text.strip()

    def _translate_batch_json(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        system_prompt_override: str | None = None,
    ) -> dict[str, str]:
        self._ensure_not_cancelled()
        payload = {f"text_{index}": value for index, value in enumerate(texts)}
        prompt = (
            f"Translate JSON values from {source_lang} to {target_lang}. "
            "Keep keys unchanged. Output valid JSON only."
        )
        system_prompt = system_prompt_override or self._compose_system_prompt(
            texts, source_lang, target_lang, enable_inference=False
        )
        content = self._chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ]
        )
        parsed = json.loads(
            self._extract_json_block(self._strip_think_tags(content))
        )
        if not isinstance(parsed, dict):
            raise ValueError("Batch translation response must be a JSON object")
        expected = set(payload)
        actual = set(parsed)
        if actual != expected:
            missing = sorted(expected - actual)
            unexpected = sorted(actual - expected)
            details = []
            if missing:
                details.append(f"missing keys: {', '.join(missing)}")
            if unexpected:
                details.append(f"unexpected keys: {', '.join(unexpected)}")
            raise ValueError(
                "Batch translation response has invalid keys ("
                + "; ".join(details)
                + ")"
            )
        invalid = [key for key, value in parsed.items() if not isinstance(value, str)]
        if invalid:
            raise ValueError(
                "Batch translation response values must be strings: "
                + ", ".join(sorted(invalid))
            )
        return {
            original: parsed[f"text_{index}"]
            for index, original in enumerate(texts)
        }

    def translate_batch(
        self,
        texts: list[str],
        source_lang: str = "auto",
        target_lang: str = "en",
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[str]:
        if not texts:
            return []
        frozen = getattr(self._thread_local, "frozen_llm_config", None)
        runtime = self._active_config()
        batch_size = max(1, int(runtime["batch_size"]))
        batch_json = bool(runtime["batch_json"])
        parallel_count = max(1, int(runtime.get("parallel_count", 1)))
        translatable = [text for text in texts if self._is_translatable_text(text)]
        if not translatable:
            return texts
        chunks = [
            (index, translatable[start : start + batch_size])
            for index, start in enumerate(
                range(0, len(translatable), batch_size), start=1
            )
        ]
        total_chunks = len(chunks)
        translated_by_text: dict[str, str] = {}
        processed_count = 0
        completed_chunks = 0
        last_effective: dict[str, Any] | None = None
        progress_lock = threading.Lock()

        def raise_if_cancelled() -> None:
            if should_cancel is not None and should_cancel():
                raise RuntimeError("Task cancelled by user.")

        def emit_progress(
            event: str,
            *,
            effective: dict[str, Any] | None = None,
            **payload: Any,
        ) -> None:
            if progress_callback is None:
                return
            selected = effective or runtime
            try:
                with progress_lock:
                    progress_callback(
                        {
                            "event": event,
                            "provider": selected["provider"],
                            "model": selected["model"],
                            "base_url": selected.get("base_url", ""),
                            "format": selected.get("format", ""),
                            "batch_size": batch_size,
                            "retry_count": int(runtime["retry_count"]),
                            "total_texts": len(translatable),
                            "translated_count": processed_count,
                            "total_chunks": total_chunks,
                            "completed_chunks": completed_chunks,
                            "parallel_count": parallel_count,
                            **payload,
                        }
                    )
            except Exception as exc:
                logger.warning(
                    "translate_batch_progress_callback_failed", error=str(exc)
                )

        def worker(
            chunk_index: int, chunk: list[str]
        ) -> tuple[int, dict[str, str], str, dict[str, Any]]:
            with self.frozen_config(frozen), self.cancellation_check(should_cancel):
                raise_if_cancelled()
                translated: dict[str, str] = {}
                batch_error = ""
                try:
                    if batch_json and len(chunk) > 1:
                        translated.update(
                            self._translate_batch_json(
                                chunk,
                                source_lang,
                                target_lang,
                                system_prompt_override=system_prompt,
                            )
                        )
                    else:
                        for item in chunk:
                            raise_if_cancelled()
                            translated[item] = self.translate_text(
                                item,
                                source_lang,
                                target_lang,
                                system_prompt_override=system_prompt,
                            )
                except Exception as exc:
                    raise_if_cancelled()
                    batch_error = str(exc)
                    logger.warning("batch_json_failed_fallback_single", error=str(exc))
                    translated.clear()
                    for item in chunk:
                        raise_if_cancelled()
                        translated[item] = self.translate_text(
                            item,
                            source_lang,
                            target_lang,
                            system_prompt_override=system_prompt,
                        )
                selected = getattr(
                    self._thread_local, "effective_candidate", None
                ) or runtime
                return chunk_index, translated, batch_error, selected

        with self.cancellation_check(should_cancel):
            raise_if_cancelled()
            system_prompt = self._compose_system_prompt(
                translatable[:30],
                source_lang,
                target_lang,
                enable_inference=True,
            )
            inferred = getattr(self._thread_local, "effective_candidate", None)
            emit_progress("started", effective=inferred)

            def consume(
                result: tuple[int, dict[str, str], str, dict[str, Any]]
            ) -> None:
                nonlocal processed_count, completed_chunks, last_effective
                index, translated, batch_error, selected = result
                last_effective = selected
                translated_by_text.update(translated)
                processed_count += len(chunks[index - 1][1])
                completed_chunks += 1
                emit_progress(
                    "chunk_completed",
                    effective=selected,
                    chunk_index=index,
                    chunk_size=len(chunks[index - 1][1]),
                    last_error=batch_error,
                    chunk_translations=translated,
                )

            if parallel_count == 1:
                for index, chunk in chunks:
                    raise_if_cancelled()
                    emit_progress(
                        "chunk_started", chunk_index=index, chunk_size=len(chunk)
                    )
                    consume(worker(index, chunk))
            else:
                executor = ThreadPoolExecutor(max_workers=parallel_count)
                pending: dict[Future[Any], int] = {}
                chunk_iterator = iter(chunks)

                def submit_one() -> bool:
                    raise_if_cancelled()
                    try:
                        index, chunk = next(chunk_iterator)
                    except StopIteration:
                        return False
                    emit_progress(
                        "chunk_started", chunk_index=index, chunk_size=len(chunk)
                    )
                    pending[executor.submit(worker, index, chunk)] = index
                    return True

                try:
                    for _ in range(min(parallel_count, total_chunks)):
                        submit_one()
                    while pending:
                        raise_if_cancelled()
                        done, _ = wait(
                            pending, timeout=0.1, return_when=FIRST_COMPLETED
                        )
                        for future in done:
                            pending.pop(future, None)
                            consume(future.result())
                            submit_one()
                except Exception:
                    for future in pending:
                        future.cancel()
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise
                else:
                    executor.shutdown(wait=True)

        output = [
            translated_by_text.get(item, item)
            if item and item.strip()
            else item
            for item in texts
        ]
        emit_progress("completed", effective=last_effective or inferred)
        return output


llm_translation_service = LLMTranslationService()
llm_excel_processor = LLMExcelTranslationProcessor(llm_translation_service)

__all__ = [
    "BUILTIN_PROVIDER_IDS",
    "CAD_SPECIALIZED_SYSTEM_PROMPT",
    "LLMExcelTranslationProcessor",
    "LLMTranslationService",
    "PROVIDER_PRESETS",
    "ProviderPreset",
    "_TokenBucket",
    "add_custom_provider",
    "delete_custom_provider",
    "list_provider_presets",
    "llm_excel_processor",
    "llm_translation_service",
    "load_custom_providers",
    "refresh_custom_providers",
    "save_custom_providers",
]
