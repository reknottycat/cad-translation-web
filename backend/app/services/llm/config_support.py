"""Configuration resolution for the unified LLM service."""

from __future__ import annotations

import contextlib
import os
import re
from pathlib import Path
from typing import Any, Iterator

from app.services.config_manager import ConfigManager

from .providers import PROVIDER_PRESETS


class LLMConfigMixin:
    @contextlib.contextmanager
    def frozen_config(self, llm_config: dict[str, Any] | None) -> Iterator[None]:
        """Resolve stable task settings while fetching credentials at call time."""
        previous = getattr(self._thread_local, "frozen_llm_config", None)
        self._thread_local.frozen_llm_config = llm_config
        try:
            yield
        finally:
            self._thread_local.frozen_llm_config = previous

    @contextlib.contextmanager
    def cancellation_check(self, check: Any) -> Iterator[None]:
        previous = getattr(self._thread_local, "cancellation_check", None)
        self._thread_local.cancellation_check = check
        try:
            yield
        finally:
            self._thread_local.cancellation_check = previous

    def _ensure_not_cancelled(self) -> None:
        check = getattr(self._thread_local, "cancellation_check", None)
        if check is not None and check():
            raise RuntimeError("Task cancelled by user.")

    @staticmethod
    def _is_translatable_text(text: str) -> bool:
        stripped = (text or "").strip()
        if not stripped:
            return False
        if re.fullmatch(r"\d+(?:[.,:/-]\d+)*", stripped):
            return False
        if re.fullmatch(r"[^\w\u4e00-\u9fff]+", stripped, flags=re.UNICODE):
            return False
        return True

    def count_translatable_texts(self, texts: list[str]) -> int:
        return sum(1 for text in texts if self._is_translatable_text(text))

    def _resolve_api_key(
        self,
        provider: str,
        raw_api_key: str,
        provider_api_keys: dict[str, str] | None = None,
    ) -> tuple[str, str]:
        api_key = (raw_api_key or "").strip()
        if api_key and api_key != "***":
            return api_key, "config"
        if provider_api_keys:
            provider_key = str(provider_api_keys.get(provider) or "").strip()
            if provider_key:
                return provider_key, "config"
        preset = PROVIDER_PRESETS.get(provider)
        env_keys: list[str] = []
        if preset is not None and preset.api_key_env:
            env_keys.append(preset.api_key_env)
        if "LLM_API_KEY" not in env_keys:
            env_keys.append("LLM_API_KEY")
        for env_key in env_keys:
            candidate = (os.environ.get(env_key) or "").strip()
            if candidate:
                return candidate, "env"
            candidate = (getattr(self.settings, env_key, "") or "").strip()
            if candidate:
                return candidate, "settings"
        return "", "none"

    def _setting_default(self, field_name: str) -> Any:
        return getattr(
            self.settings,
            field_name,
            type(self.settings).model_fields[field_name].default,
        )

    def _resolve_candidate_config(
        self,
        raw: dict[str, Any],
        provider_api_keys: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        provider = str(
            raw.get("provider")
            or self._setting_default("TRANSLATION_PROVIDER")
            or "custom"
        ).strip().lower()
        if provider == "openai_compatible":
            provider = "custom"
        preset = PROVIDER_PRESETS.get(provider)
        api_format = str(
            raw.get("format")
            or (preset.api_format if preset else self._setting_default("LLM_API_FORMAT"))
            or "openai_compatible"
        ).strip().lower()
        base_url = str(
            raw.get("base_url") or self._setting_default("LLM_BASE_URL") or ""
        ).strip().rstrip("/")
        model = str(
            raw.get("model") or self._setting_default("LLM_MODEL") or ""
        ).strip()
        if preset is not None:
            base_url = base_url or preset.base_url
            model = model or preset.default_model
        api_key, api_key_source = self._resolve_api_key(
            provider, str(raw.get("api_key") or ""), provider_api_keys
        )
        return {
            "provider": provider,
            "format": api_format,
            "base_url": base_url,
            "model": model,
            "api_key": api_key,
            "api_key_source": api_key_source,
            "timeout": int(
                raw.get("timeout")
                or raw.get("timeout_seconds")
                or self._setting_default("LLM_TIMEOUT_SECONDS")
            ),
            "temperature": float(
                raw.get("temperature")
                if raw.get("temperature") is not None
                else self._setting_default("LLM_TEMPERATURE")
            ),
            "max_tokens": int(
                raw.get("max_tokens") or self._setting_default("LLM_MAX_TOKENS")
            ),
            "reasoning_enabled": bool(
                raw.get(
                    "reasoning_enabled",
                    self._setting_default("LLM_REASONING_ENABLED"),
                )
            ),
        }

    def _active_config(self) -> dict[str, Any]:
        frozen = getattr(self._thread_local, "frozen_llm_config", None)
        if frozen is not None:
            file_runtime = dict(frozen)
            live_runtime = ConfigManager().get_effective_config().get("llm", {})
            frozen_provider_keys = dict(file_runtime.get("provider_api_keys") or {})
            live_provider_keys = dict(live_runtime.get("provider_api_keys") or {})
            for provider_id, value in list(frozen_provider_keys.items()):
                if not str(value or "").strip() or str(value).strip() == "***":
                    if provider_id in live_provider_keys:
                        frozen_provider_keys[provider_id] = live_provider_keys[provider_id]
                    else:
                        frozen_provider_keys.pop(provider_id, None)
            for provider_id, value in live_provider_keys.items():
                frozen_provider_keys.setdefault(provider_id, value)
            file_runtime["provider_api_keys"] = frozen_provider_keys
            primary_raw = dict(frozen.get("primary") or {})
            live_primary = dict(live_runtime.get("primary") or {})
            frozen_key = str(primary_raw.get("api_key") or "").strip()
            if not frozen_key or frozen_key == "***":
                primary_raw["api_key"] = live_primary.get("api_key", "")
            file_runtime["primary"] = primary_raw
        else:
            file_runtime = ConfigManager().get_effective_config().get("llm", {})
        if not isinstance(file_runtime, dict):
            file_runtime = {}
        provider_keys = file_runtime.get("provider_api_keys")
        primary = self._resolve_candidate_config(
            file_runtime.get("primary") or {}, provider_keys
        )
        configured_glossary = str(
            file_runtime.get("glossary_file")
            or self._setting_default("LLM_GLOSSARY_FILE")
            or ""
        ).strip()
        glossary_path, default_glossary_used = self._resolve_default_glossary(
            configured_glossary
        )
        fallback_models = [
            self._resolve_candidate_config(entry, provider_keys)
            for entry in (file_runtime.get("fallback_models") or [])
            if isinstance(entry, dict)
        ]
        inherited = {
            "retry_count",
            "rpm",
            "tpm",
            "extra_body",
            "use_system_proxy",
            "allow_demo_fallback",
        }
        for fallback in fallback_models:
            for key in inherited:
                fallback[key] = file_runtime.get(key)
        primary.update(
            {
                "system_prompt": str(
                    file_runtime.get("system_prompt")
                    or self._setting_default("LLM_SYSTEM_PROMPT")
                    or ""
                ).strip(),
                "system_prompt_mode": str(
                    file_runtime.get("system_prompt_mode")
                    or self._setting_default("LLM_SYSTEM_PROMPT_MODE")
                    or "default"
                ).strip().lower(),
                "custom_system_prompt": str(
                    file_runtime.get("custom_system_prompt")
                    or self._setting_default("LLM_CUSTOM_SYSTEM_PROMPT")
                    or ""
                ).strip(),
                "glossary_file": glossary_path,
                "default_glossary_used": default_glossary_used,
                "batch_size": int(
                    file_runtime.get("batch_size")
                    or self._setting_default("LLM_BATCH_SIZE")
                ),
                "batch_json": bool(
                    file_runtime.get(
                        "batch_json", self._setting_default("LLM_ENABLE_BATCH_JSON")
                    )
                ),
                "parallel_count": int(
                    file_runtime.get("parallel_count")
                    or self._setting_default("LLM_PARALLEL_COUNT")
                ),
                "retry_count": int(
                    file_runtime.get("retry_count")
                    if file_runtime.get("retry_count") is not None
                    else self._setting_default("LLM_RETRY_COUNT")
                ),
                "rpm": int(
                    file_runtime.get("rpm")
                    or self._setting_default("LLM_RPM")
                ),
                "tpm": str(
                    file_runtime.get("tpm")
                    or self._setting_default("LLM_TPM")
                    or ""
                ).strip(),
                "extra_body": str(
                    file_runtime.get("extra_body")
                    or self._setting_default("LLM_EXTRA_BODY")
                    or ""
                ).strip(),
                "use_system_proxy": bool(
                    file_runtime.get(
                        "use_system_proxy",
                        self._setting_default("LLM_USE_SYSTEM_PROXY"),
                    )
                ),
                "allow_demo_fallback": bool(
                    file_runtime.get(
                        "allow_demo_fallback",
                        self._setting_default("LLM_ALLOW_DEMO_FALLBACK"),
                    )
                ),
                "fallback_models": fallback_models,
            }
        )
        return primary

    def _resolve_default_glossary(
        self, configured_glossary: str
    ) -> tuple[str, bool]:
        if configured_glossary:
            return configured_glossary, False
        for name in ("DocuTranslate.csv", "DocuTranslate.xlsx", "DocuTranslate.xls"):
            candidate = self.settings.BASE_DIR / name
            if candidate.exists():
                return str(candidate), True
        return "", False

    def get_runtime_summary(self) -> dict[str, Any]:
        cfg = self._active_config()
        glossary = Path(cfg["glossary_file"]) if cfg["glossary_file"] else None
        if glossary and not glossary.is_absolute():
            glossary = (self.settings.BASE_DIR / glossary).resolve()
        fallbacks = [
            {
                "provider": item["provider"],
                "format": item["format"],
                "base_url": item["base_url"],
                "model": item["model"],
                "api_key_configured": bool(item["api_key"]),
                "reasoning_enabled": item.get("reasoning_enabled", False),
            }
            for item in cfg.get("fallback_models", [])
        ]
        return {
            "provider": cfg["provider"],
            "format": cfg["format"],
            "base_url": cfg["base_url"],
            "model": cfg["model"],
            "api_key_configured": bool(cfg["api_key"]),
            "api_key_source": cfg.get("api_key_source", "none"),
            "system_prompt_mode": cfg["system_prompt_mode"],
            "custom_system_prompt": cfg["custom_system_prompt"],
            "custom_system_prompt_configured": bool(cfg["custom_system_prompt"]),
            "glossary_file": str(glossary) if glossary else cfg["glossary_file"],
            "glossary_configured": bool(glossary) and glossary.exists(),
            "default_glossary_used": cfg["default_glossary_used"],
            "reasoning_enabled": cfg["reasoning_enabled"],
            "timeout_seconds": cfg["timeout"],
            "temperature": cfg["temperature"],
            "max_tokens": cfg["max_tokens"],
            "batch_size": cfg["batch_size"],
            "batch_json": cfg["batch_json"],
            "parallel_count": cfg["parallel_count"],
            "retry_count": cfg["retry_count"],
            "rpm": cfg["rpm"],
            "tpm": cfg["tpm"],
            "extra_body": cfg["extra_body"],
            "use_system_proxy": cfg["use_system_proxy"],
            "fallback_count": len(fallbacks),
            "fallback_models": fallbacks,
        }
