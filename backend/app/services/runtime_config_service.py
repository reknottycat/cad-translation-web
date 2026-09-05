#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runtime configuration helpers for translation model settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from app.config import get_settings, load_runtime_config
from app.services.config_manager import ConfigManager
from app.services.llm.translation_service import PROVIDER_PRESETS, llm_translation_service


class RuntimeConfigService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _setting_default(self, field_name: str) -> Any:
        # Return the actual value from settings (which reflects .env / environment),
        # falling back to the Pydantic field default only if the attribute is missing.
        return getattr(
            self.settings,
            field_name,
            type(self.settings).model_fields[field_name].default,
        )

    def _config_manager(self, cli_overrides: Dict[str, Any] | None = None) -> ConfigManager:
        return ConfigManager(cli_overrides=cli_overrides)

    def _global_runtime_payload(self) -> Dict[str, Any]:
        payload = load_runtime_config(self.settings.get_runtime_config_path())
        return payload if isinstance(payload, dict) else {}

    def _global_llm_payload(self) -> Dict[str, Any]:
        payload = self._global_runtime_payload()
        llm_payload = payload.get("llm")
        if isinstance(llm_payload, dict):
            return llm_payload
        return payload

    def _global_cad_payload(self) -> Dict[str, Any]:
        payload = self._global_runtime_payload()
        cad_payload = payload.get("cad")
        if isinstance(cad_payload, dict):
            return cad_payload
        return payload

    def mask_api_key(self, api_key: str) -> str | None:
        if not api_key:
            return None
        if len(api_key) <= 8:
            return "*" * len(api_key)
        return f"{api_key[:4]}...{api_key[-4:]}"

    def _preset_defaults(self, provider: str) -> tuple[str, str]:
        normalized = (provider or "").strip().lower()
        preset = PROVIDER_PRESETS.get(normalized)
        if preset is None:
            return "", ""
        return preset.base_url, preset.default_model

    def _preset_format(self, provider: str) -> str:
        normalized = (provider or "").strip().lower()
        preset = PROVIDER_PRESETS.get(normalized)
        if preset is None:
            return "openai_compatible"
        return preset.api_format

    @staticmethod
    def _normalize_provider(provider: Any) -> str:
        normalized = str(provider or "custom").strip().lower()
        return "custom" if normalized == "openai_compatible" else normalized

    @staticmethod
    def _public_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
        """Return the durable, non-secret part of a provider profile."""
        allowed = {
            "format",
            "base_url",
            "model",
            "timeout_seconds",
            "temperature",
            "max_tokens",
            "reasoning_enabled",
        }
        return {key: profile[key] for key in allowed if key in profile}

    def _stored_provider_profiles(self) -> Dict[str, Dict[str, Any]]:
        file_runtime = self._global_llm_payload()
        raw_profiles = file_runtime.get("provider_profiles")
        if not isinstance(raw_profiles, dict):
            return {}
        return {
            self._normalize_provider(provider): self._public_profile(profile)
            for provider, profile in raw_profiles.items()
            if isinstance(profile, dict)
        }

    def _current_provider(self) -> str:
        file_runtime = self._global_llm_payload()
        primary = file_runtime.get("primary") if isinstance(file_runtime.get("primary"), dict) else {}
        provider = str(primary.get("provider") or file_runtime.get("provider") or self._setting_default("TRANSLATION_PROVIDER") or "custom").strip().lower()
        return "custom" if provider == "openai_compatible" else provider

    def _resolve_api_key(self, provider: str, explicit_api_key: Any = None) -> tuple[str, str]:
        if explicit_api_key is not None:
            candidate = str(explicit_api_key or "").strip()
            if candidate:
                return candidate, "config"

        file_runtime = self._global_llm_payload()
        primary = file_runtime.get("primary") if isinstance(file_runtime.get("primary"), dict) else {}
        normalized_provider = self._normalize_provider(provider)

        # 1. Check provider-specific api key from effective config (includes global config)
        effective_config = self._config_manager().get_effective_config()
        effective_llm = effective_config.get("llm") if isinstance(effective_config, dict) else {}
        effective_provider_api_keys = effective_llm.get("provider_api_keys") if isinstance(effective_llm, dict) else None
        if isinstance(effective_provider_api_keys, dict):
            provider_key = str(effective_provider_api_keys.get(normalized_provider) or "").strip()
            if provider_key:
                return provider_key, "config"

        # 2. Fallback to runtime config file (backward compatibility)
        provider_api_keys = file_runtime.get("provider_api_keys") if isinstance(file_runtime, dict) else None
        if isinstance(provider_api_keys, dict):
            provider_key = str(provider_api_keys.get(normalized_provider) or "").strip()
            if provider_key:
                return provider_key, "config"

        # 3. Fallback to global api_key (backward compatibility)
        primary_provider = self._normalize_provider(
            primary.get("provider") or file_runtime.get("provider")
        )
        file_api_key = str(primary.get("api_key") or file_runtime.get("api_key") or "").strip()
        if primary_provider == normalized_provider and file_api_key:
            return file_api_key, "config"

        preset = PROVIDER_PRESETS.get(normalized_provider)
        env_keys: list[str] = []
        if preset is not None and preset.api_key_env:
            env_keys.append(preset.api_key_env)
        configured_provider = self._normalize_provider(
            self._setting_default("TRANSLATION_PROVIDER")
        )
        if (
            normalized_provider in {configured_provider, "custom"}
            and "LLM_API_KEY" not in env_keys
        ):
            env_keys.append("LLM_API_KEY")

        for env_key in env_keys:
            candidate = (os.environ.get(env_key) or "").strip()
            if candidate:
                return candidate, "env"
            settings_value = (getattr(self.settings, env_key, "") or "").strip()
            if settings_value:
                return settings_value, "settings"

        candidate = (self.settings.LLM_API_KEY or "").strip()
        if candidate and configured_provider == normalized_provider:
            return candidate, "settings"
        return "", "none"

    def _uses_explicit_api_key(self, payload: Dict[str, Any]) -> bool:
        return bool(str(payload.get("api_key") or "").strip())

    def _normalize_fallback_models(
        self,
        payload: Dict[str, Any],
        file_runtime: Dict[str, Any],
    ) -> list[Dict[str, Any]]:
        raw_models = payload.get("fallback_models")
        if raw_models is None:
            raw_models = file_runtime.get("fallback_models") or []
        if not raw_models:
            return []
        if not isinstance(raw_models, list):
            raise ValueError("fallback_models must be a list")

        normalized: list[Dict[str, Any]] = []
        for raw_entry in raw_models:
            if not isinstance(raw_entry, dict):
                raise ValueError("Each fallback model must be an object")

            provider = str(raw_entry.get("provider") or "custom").strip().lower()
            provider = "custom" if provider == "openai_compatible" else provider
            preset_base_url, preset_model = self._preset_defaults(provider)
            api_format = str(
                raw_entry.get("format")
                or self._preset_format(provider)
            ).strip().lower()
            base_url = str(raw_entry.get("base_url") or preset_base_url or "").strip().rstrip("/")
            model = str(raw_entry.get("model") or preset_model or "").strip()
            api_key, api_key_source = self._resolve_api_key(
                provider,
                raw_entry["api_key"] if "api_key" in raw_entry else None,
            )
            timeout_seconds = int(
                raw_entry.get("timeout_seconds")
                or payload.get("timeout_seconds")
                or self._setting_default("LLM_TIMEOUT_SECONDS")
            )
            temperature = float(
                raw_entry.get("temperature")
                or payload.get("temperature")
                or self._setting_default("LLM_TEMPERATURE")
            )
            max_tokens = int(
                raw_entry.get("max_tokens")
                or payload.get("max_tokens")
                or self._setting_default("LLM_MAX_TOKENS")
            )
            reasoning_enabled = bool(raw_entry.get("reasoning_enabled", False))

            normalized.append(
                {
                    "provider": provider,
                    "format": api_format,
                    "base_url": base_url,
                    "api_key": api_key,
                    "api_key_source": api_key_source,
                    "api_key_configured": bool(api_key),
                    "model": model,
                    "reasoning_enabled": reasoning_enabled,
                    "timeout_seconds": timeout_seconds,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
            )
        return normalized

    def _normalized_runtime(self, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        payload = payload or {}
        file_runtime = self._global_llm_payload()
        primary = file_runtime.get("primary") if isinstance(file_runtime.get("primary"), dict) else {}
        provider = self._normalize_provider(
            payload.get("provider")
            or primary.get("provider")
            or file_runtime.get("provider")
            or self._setting_default("TRANSLATION_PROVIDER")
        )

        preset_base_url, preset_model = self._preset_defaults(provider)
        preset_format = self._preset_format(provider)
        stored_profile = self._stored_provider_profiles().get(provider, {})
        incoming_profiles = payload.get("provider_profiles")
        incoming_profile = (
            incoming_profiles.get(provider, {})
            if isinstance(incoming_profiles, dict)
            and isinstance(incoming_profiles.get(provider), dict)
            else {}
        )
        profile = {**stored_profile, **self._public_profile(incoming_profile)}
        current_provider = self._current_provider()
        current_summary = llm_translation_service.get_runtime_summary() if current_provider == provider else {}
        file_matches_provider = str(primary.get("provider") or file_runtime.get("provider") or "").strip().lower() == provider
        api_format = str(
            payload.get("format")
            or profile.get("format")
            or (primary.get("format") if file_matches_provider else "")
            or current_summary.get("format")
            or preset_format
        ).strip().lower()

        base_url = str(
            payload.get("base_url")
            or profile.get("base_url")
            or (primary.get("base_url") if file_matches_provider else "")
            or current_summary.get("base_url")
            or preset_base_url
            or self._setting_default("LLM_BASE_URL")
        ).strip().rstrip("/")
        model = str(
            payload.get("model")
            or profile.get("model")
            or (primary.get("model") if file_matches_provider else "")
            or current_summary.get("model")
            or preset_model
            or self._setting_default("LLM_MODEL")
        ).strip()
        api_key, api_key_source = self._resolve_api_key(
            provider,
            payload.get("api_key") if self._uses_explicit_api_key(payload) else None,
        )

        timeout_seconds = int(
            payload.get("timeout_seconds")
            or profile.get("timeout_seconds")
            or (primary.get("timeout_seconds") if file_matches_provider else 0)
            or self._setting_default("LLM_TIMEOUT_SECONDS")
        )
        system_prompt_mode = str(
            payload.get("system_prompt_mode")
            or (file_runtime.get("system_prompt_mode") if file_matches_provider else "")
            or current_summary.get("system_prompt_mode")
            or self._setting_default("LLM_SYSTEM_PROMPT_MODE")
            or "default"
        ).strip().lower()
        custom_system_prompt = str(
            payload.get("custom_system_prompt")
            if "custom_system_prompt" in payload
            else (file_runtime.get("custom_system_prompt") if file_matches_provider else "")
            or current_summary.get("custom_system_prompt")
            or self._setting_default("LLM_CUSTOM_SYSTEM_PROMPT")
            or ""
        ).strip()
        glossary_file = str(
            payload.get("glossary_file")
            if "glossary_file" in payload
            else (file_runtime.get("glossary_file") if file_matches_provider else "")
            or current_summary.get("glossary_file")
            or self._setting_default("LLM_GLOSSARY_FILE")
            or ""
        ).strip()
        if "reasoning_enabled" in payload and payload.get("reasoning_enabled") is not None:
            reasoning_enabled = bool(payload.get("reasoning_enabled"))
        elif "reasoning_enabled" in profile:
            reasoning_enabled = bool(profile["reasoning_enabled"])
        elif file_matches_provider and ("reasoning_enabled" in primary or "reasoning_enabled" in file_runtime):
            reasoning_enabled = bool(primary.get("reasoning_enabled", file_runtime.get("reasoning_enabled")))
        else:
            reasoning_enabled = bool(current_summary.get("reasoning_enabled", self._setting_default("LLM_REASONING_ENABLED")))
        temperature = float(
            payload.get("temperature")
            if payload.get("temperature") is not None
            else profile.get("temperature")
            or (primary.get("temperature") if file_matches_provider else 0)
            or self._setting_default("LLM_TEMPERATURE")
        )
        max_tokens = int(
            payload.get("max_tokens")
            or profile.get("max_tokens")
            or (primary.get("max_tokens") if file_matches_provider else 0)
            or self._setting_default("LLM_MAX_TOKENS")
        )
        batch_size = int(
            payload.get("batch_size")
            or (file_runtime.get("batch_size") if file_matches_provider else 0)
            or self._setting_default("LLM_BATCH_SIZE")
        )
        if "batch_json" in payload and payload.get("batch_json") is not None:
            batch_json = bool(payload.get("batch_json"))
        elif file_matches_provider and "batch_json" in file_runtime:
            batch_json = bool(file_runtime.get("batch_json"))
        else:
            batch_json = bool(self._setting_default("LLM_ENABLE_BATCH_JSON"))
        parallel_count = int(
            payload.get("parallel_count")
            or (file_runtime.get("parallel_count") if file_matches_provider else 0)
            or self._setting_default("LLM_PARALLEL_COUNT")
        )
        retry_count = int(
            payload.get("retry_count")
            or (file_runtime.get("retry_count") if file_matches_provider else 0)
            or self._setting_default("LLM_RETRY_COUNT")
        )
        rpm = int(
            payload.get("rpm")
            or (file_runtime.get("rpm") if file_matches_provider else 0)
            or self._setting_default("LLM_RPM")
        )
        tpm = str(
            payload.get("tpm")
            if "tpm" in payload
            else (file_runtime.get("tpm") if file_matches_provider else "")
            or current_summary.get("tpm")
            or self._setting_default("LLM_TPM")
            or ""
        ).strip()
        extra_body = str(
            payload.get("extra_body")
            if "extra_body" in payload
            else (file_runtime.get("extra_body") if file_matches_provider else "")
            or current_summary.get("extra_body")
            or self._setting_default("LLM_EXTRA_BODY")
            or ""
        ).strip()
        if "use_system_proxy" in payload and payload.get("use_system_proxy") is not None:
            use_system_proxy = bool(payload.get("use_system_proxy"))
        elif file_matches_provider and "use_system_proxy" in file_runtime:
            use_system_proxy = bool(file_runtime.get("use_system_proxy"))
        else:
            use_system_proxy = bool(current_summary.get("use_system_proxy", self._setting_default("LLM_USE_SYSTEM_PROXY")))
        system_prompt = str(
            payload.get("system_prompt")
            if "system_prompt" in payload
            else (file_runtime.get("system_prompt") if file_matches_provider else "")
            or current_summary.get("system_prompt")
            or self._setting_default("LLM_SYSTEM_PROMPT")
            or ""
        ).strip()
        allow_demo_fallback = (
            bool(payload.get("allow_demo_fallback"))
            if "allow_demo_fallback" in payload and payload.get("allow_demo_fallback") is not None
            else (
                bool(file_runtime.get("allow_demo_fallback"))
                if file_matches_provider and "allow_demo_fallback" in file_runtime
                else bool(current_summary.get("allow_demo_fallback", self._setting_default("LLM_ALLOW_DEMO_FALLBACK")))
            )
        )
        fallback_models = self._normalize_fallback_models(payload, file_runtime)

        result: Dict[str, Any] = {
            "provider": provider,
            "format": api_format,
            "base_url": base_url,
            "api_key": api_key,
            "api_key_source": api_key_source,
            "explicit_api_key": self._uses_explicit_api_key(payload),
            "clear_api_key": bool(payload.get("clear_api_key", False)),
            "model": model,
            "system_prompt_mode": system_prompt_mode,
            "custom_system_prompt": custom_system_prompt,
            "glossary_file": glossary_file,
            "reasoning_enabled": reasoning_enabled,
            "timeout_seconds": timeout_seconds,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "batch_size": batch_size,
            "batch_json": batch_json,
            "parallel_count": parallel_count,
            "retry_count": retry_count,
            "rpm": rpm,
            "tpm": tpm,
            "extra_body": extra_body,
            "use_system_proxy": use_system_proxy,
            "system_prompt": system_prompt,
            "allow_demo_fallback": allow_demo_fallback,
            "fallback_models": fallback_models,
            "provider_profiles": payload.get("provider_profiles"),
        }
        if "provider_api_keys" in payload:
            result["provider_api_keys"] = payload["provider_api_keys"]
        return result

    def get_public_runtime_summary(self) -> Dict[str, Any]:
        runtime = dict(llm_translation_service.get_runtime_summary())
        api_key, key_source = self._resolve_api_key(runtime["provider"])
        runtime["masked_api_key"] = self.mask_api_key(api_key)
        runtime["api_key_source"] = key_source
        runtime["config_file"] = str(self.settings.get_runtime_config_path())
        # Credentials are write-only. Return status metadata for every provider
        # the UI can select, without returning any usable secret value.
        provider_ids = set(PROVIDER_PRESETS)
        provider_ids.update(self._stored_provider_profiles())
        file_runtime = self._global_llm_payload()
        provider_api_keys = file_runtime.get("provider_api_keys")
        if isinstance(provider_api_keys, dict):
            provider_ids.update(map(str, provider_api_keys))
        runtime["provider_credentials"] = {
            provider_id: {
                "configured": bool(resolved_key),
                "source": source,
                "masked": self.mask_api_key(resolved_key),
            }
            for provider_id in sorted(provider_ids)
            for resolved_key, source in [self._resolve_api_key(provider_id)]
        }

        profiles: Dict[str, Dict[str, Any]] = {}
        stored_profiles = self._stored_provider_profiles()
        for provider_id in provider_ids:
            preset = PROVIDER_PRESETS.get(provider_id)
            profile: Dict[str, Any] = {
                "format": preset.api_format if preset else "openai_compatible",
                "base_url": preset.base_url if preset else "",
                "model": preset.default_model if preset else "",
            }
            profile.update(stored_profiles.get(provider_id, {}))
            profiles[provider_id] = self._public_profile(profile)
        profiles[runtime["provider"]] = self._public_profile(
            {
                **profiles.get(runtime["provider"], {}),
                "format": runtime.get("format"),
                "base_url": runtime.get("base_url"),
                "model": runtime.get("model"),
                "timeout_seconds": runtime.get("timeout_seconds"),
                "temperature": runtime.get("temperature"),
                "max_tokens": runtime.get("max_tokens"),
                "reasoning_enabled": runtime.get("reasoning_enabled"),
            }
        )
        runtime["provider_profiles"] = profiles
        runtime.pop("provider_api_keys", None)
        return runtime

    def _persist_runtime_config_file(self, values: Dict[str, Any]) -> Path:
        runtime_path = self.settings.get_runtime_config_path()
        primary_patch: dict[str, Any] = {
            "provider": values["provider"],
            "format": values["format"],
            "base_url": values["base_url"],
            "model": values["model"],
            "timeout_seconds": values["timeout_seconds"],
            "temperature": values["temperature"],
            "max_tokens": values["max_tokens"],
            "reasoning_enabled": values["reasoning_enabled"],
        }
        # Determine whether to write/clear api_key in primary.
        file_runtime = self._global_llm_payload()
        primary_in_file = file_runtime.get("primary") or {}
        old_provider = str(primary_in_file.get("provider") or "").strip().lower()
        new_provider = values["provider"]
        # Read provider_api_keys from file (values may not contain it if frontend didn't send)
        file_provider_api_keys = dict(file_runtime.get("provider_api_keys") or {})

        if values.get("clear_api_key"):
            primary_patch["api_key"] = ""
            file_provider_api_keys[values["provider"]] = ""
        elif values.get("explicit_api_key"):
            primary_patch["api_key"] = values["api_key"]
        elif values.get("api_key") and values.get("api_key_source") == "config":
            # Keep a resolved stored key when the form only changes non-secret
            # settings (including provider). The user can clear it explicitly.
            primary_patch["api_key"] = values["api_key"]
        elif old_provider != new_provider:
            # No stored key was resolved for the selected provider. Prefer its
            # provider-specific entry and otherwise leave the key unset.
            primary_patch["api_key"] = file_provider_api_keys.get(new_provider, "")
        llm_patch: dict[str, Any] = {
            "primary": {
                **primary_patch,
            },
            "system_prompt": values["system_prompt"],
            "system_prompt_mode": values["system_prompt_mode"],
            "custom_system_prompt": values["custom_system_prompt"],
            "glossary_file": values["glossary_file"],
            "batch_size": values["batch_size"],
            "batch_json": values["batch_json"],
            "parallel_count": values["parallel_count"],
            "retry_count": values["retry_count"],
            "rpm": values["rpm"],
            "tpm": values["tpm"],
            "extra_body": values["extra_body"],
            "use_system_proxy": values["use_system_proxy"],
            "allow_demo_fallback": values["allow_demo_fallback"],
            "fallback_models": values["fallback_models"],
        }
        # Merge provider-specific api keys
        provider_api_keys = dict(values.get("provider_api_keys") or {})
        provider_api_keys = {
            **file_provider_api_keys,
            **{
                self._normalize_provider(provider_id): str(key or "").strip()
                for provider_id, key in provider_api_keys.items()
            },
        }
        if values.get("explicit_api_key"):
            provider_api_keys[values["provider"]] = values["api_key"]
        llm_patch["provider_api_keys"] = provider_api_keys

        profiles = self._stored_provider_profiles()
        incoming_profiles = values.get("provider_profiles")
        if isinstance(incoming_profiles, dict):
            profiles.update(
                {
                    self._normalize_provider(provider_id): self._public_profile(profile)
                    for provider_id, profile in incoming_profiles.items()
                    if isinstance(profile, dict)
                }
            )
        profiles[values["provider"]] = self._public_profile(
            {
                "format": values["format"],
                "base_url": values["base_url"],
                "model": values["model"],
                "timeout_seconds": values["timeout_seconds"],
                "temperature": values["temperature"],
                "max_tokens": values["max_tokens"],
                "reasoning_enabled": values["reasoning_enabled"],
            }
        )
        llm_patch["provider_profiles"] = profiles
        self._config_manager().update_global_config(
            {
                "llm": llm_patch
            }
        )
        return runtime_path

    def _normalized_cad_defaults(self, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        payload = payload or {}
        cad_override_keys = {
            "target_language",
            "translation_mode",
            "font_name",
            "font_size_reduction",
            "default_output_dir",
            "converter_backend",
        }
        cad_overrides = {
            key: value
            for key, value in payload.items()
            if key in cad_override_keys and value is not None
        }
        effective = self._config_manager(cli_overrides={"cad": cad_overrides}).get_effective_config()["cad"]

        target_language = str(
            effective.get("target_language") or self.settings.DEFAULT_TARGET_LANGUAGE
        ).strip()
        translation_mode = str(
            effective.get("translation_mode") or self.settings.DEFAULT_TRANSLATION_MODE
        ).strip().lower()
        font_name = str(
            effective.get("font_name") or self.settings.DEFAULT_FONT_NAME
        ).strip()
        font_size_reduction = int(
            effective.get("font_size_reduction", self.settings.DEFAULT_FONT_SIZE_REDUCTION)
        )
        default_output_dir = str(
            effective.get("default_output_dir") or str(self.settings.get_output_path())
        ).strip()
        converter_backend = str(
            effective.get("converter_backend") or self.settings.DWG_CONVERTER_BACKEND
        ).strip().lower()

        return {
            "target_language": target_language,
            "translation_mode": translation_mode,
            "font_name": font_name,
            "font_size_reduction": font_size_reduction,
            "default_output_dir": default_output_dir,
            "converter_backend": converter_backend,
            "config_file": str(self.settings.get_runtime_config_path()),
        }

    def get_cad_defaults_summary(self) -> Dict[str, Any]:
        return self._normalized_cad_defaults()

    def update_cad_defaults(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        values = self._normalized_cad_defaults(payload)
        if not values["target_language"]:
            raise ValueError("target_language is required")
        if values["translation_mode"] not in {"add", "replace"}:
            raise ValueError("translation_mode must be add or replace")
        if values["font_size_reduction"] < 0:
            raise ValueError("font_size_reduction must be >= 0")

        runtime_path = self.settings.get_runtime_config_path()
        self._config_manager().update_global_config(
            {
                "cad": {
                    "target_language": values["target_language"],
                    "translation_mode": values["translation_mode"],
                    "font_name": values["font_name"],
                    "font_size_reduction": values["font_size_reduction"],
                    "default_output_dir": values["default_output_dir"],
                    "converter_backend": values["converter_backend"],
                }
            }
        )

        return {
            "message": "cad runtime defaults saved",
            "runtime": self.get_cad_defaults_summary(),
            "config_file": str(runtime_path),
        }

    def update_project_cad_defaults(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        values = self._normalized_cad_defaults(payload)
        if not values["target_language"]:
            raise ValueError("target_language is required")
        if values["translation_mode"] not in {"add", "replace"}:
            raise ValueError("translation_mode must be add or replace")
        if values["font_size_reduction"] < 0:
            raise ValueError("font_size_reduction must be >= 0")

        project_config_path = self._config_manager().paths.project_config
        self._config_manager().update_project_config(
            {
                "cad": {
                    "target_language": values["target_language"],
                    "translation_mode": values["translation_mode"],
                    "font_name": values["font_name"],
                    "font_size_reduction": values["font_size_reduction"],
                    "default_output_dir": values["default_output_dir"],
                    "converter_backend": values["converter_backend"],
                }
            }
        )

        return {
            "message": "cad project defaults saved",
            "runtime": self._config_manager().get_effective_config_summary(),
            "config_file": str(project_config_path),
        }

    def update_project_config(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._config_manager().update_project_config(payload)
        return {
            "message": "project config saved",
            "runtime": self._config_manager().get_effective_config_summary(),
            "config_file": str(self._config_manager().paths.project_config),
        }

    def get_effective_config_summary(self) -> Dict[str, Any]:
        return self._config_manager().get_effective_config_summary()

    def validate_effective_config(self) -> Dict[str, Any]:
        return self._config_manager().validate_effective_config()

    def get_config_value(self, path: str) -> Dict[str, Any]:
        try:
            value = self._config_manager().get_path_value(path)
        except KeyError as exc:
            raise ValueError(f"Unknown config path: {path}") from exc
        return {"path": path, "value": value}

    def set_config_value(self, path: str, value: Any) -> Dict[str, Any]:
        self._config_manager().set_global_path_value(path, value)
        return {
            "path": path,
            "value": self._config_manager().get_path_value(path),
            "config_file": str(self.settings.get_runtime_config_path()),
        }

    def set_project_config_value(self, path: str, value: Any) -> Dict[str, Any]:
        self._config_manager().set_project_path_value(path, value)
        return {
            "path": path,
            "value": self._config_manager().get_path_value(path),
            "config_file": str(self._config_manager().paths.project_config),
        }

    def update_runtime_config(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        values = self._normalized_runtime(payload)
        cad_values = self._normalized_cad_defaults(payload)
        if values["system_prompt_mode"] == "custom" and not values["custom_system_prompt"]:
            raise ValueError("custom_system_prompt is required when system_prompt_mode is custom")
        if not cad_values["target_language"]:
            raise ValueError("target_language is required")
        if cad_values["translation_mode"] not in {"add", "replace"}:
            raise ValueError("translation_mode must be add or replace")
        if cad_values["font_size_reduction"] < 0:
            raise ValueError("font_size_reduction must be >= 0")

        config_path = self._persist_runtime_config_file(values)
        self._config_manager().update_global_config(
            {
                "cad": {
                    "target_language": cad_values["target_language"],
                    "translation_mode": cad_values["translation_mode"],
                    "font_name": cad_values["font_name"],
                    "font_size_reduction": cad_values["font_size_reduction"],
                    "default_output_dir": cad_values["default_output_dir"],
                    "converter_backend": cad_values["converter_backend"],
                }
            }
        )

        return {
            "message": "translation runtime config saved",
            "runtime": self.get_public_runtime_summary(),
            "cad_defaults": self.get_cad_defaults_summary(),
            "config_file": str(config_path),
        }

    def test_connection(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        values = self._normalized_runtime(payload)
        return llm_translation_service.test_connection(values)

runtime_config_service = RuntimeConfigService()
