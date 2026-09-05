#!/usr/bin/env python3
"""Regression tests for the write-only model configuration contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture
def runtime_config_file(test_env_dir: Path) -> Iterator[Path]:
    path = test_env_dir / "config.json"
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    yield path
    if original:
        path.write_text(original, encoding="utf-8")
    else:
        path.unlink(missing_ok=True)


def _write_runtime(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "llm": {
                    "primary": {
                        "provider": "openai",
                        "format": "openai_compatible",
                        "base_url": "https://example.invalid/v1",
                        "api_key": "primary-secret-value",
                        "model": "primary-model",
                        "temperature": 0.2,
                    },
                    "provider_api_keys": {
                        "openai": "primary-secret-value",
                        "deepseek": "secondary-secret-value",
                    },
                    "provider_profiles": {
                        "openai": {
                            "provider": "openai",
                            "format": "openai_compatible",
                            "base_url": "https://example.invalid/v1",
                            "model": "remembered-openai",
                        },
                        "deepseek": {
                            "provider": "deepseek",
                            "format": "openai_compatible",
                            "base_url": "https://deepseek.invalid/v1",
                            "model": "remembered-deepseek",
                        },
                    },
                },
                "cad": {"target_language": "en", "translation_mode": "replace"},
            }
        ),
        encoding="utf-8",
    )


def test_public_summary_never_returns_provider_secrets(runtime_config_file: Path) -> None:
    _write_runtime(runtime_config_file)
    from app.services.runtime_config_service import RuntimeConfigService

    summary = RuntimeConfigService().get_public_runtime_summary()
    rendered = json.dumps(summary)

    assert "primary-secret-value" not in rendered
    assert "secondary-secret-value" not in rendered
    assert "provider_api_keys" not in summary
    assert summary["provider_credentials"]["openai"]["configured"] is True
    assert summary["provider_credentials"]["deepseek"]["configured"] is True
    assert summary["provider_profiles"]["deepseek"]["model"] == "remembered-deepseek"


def test_omitted_or_blank_key_preserves_existing_secret(runtime_config_file: Path) -> None:
    _write_runtime(runtime_config_file)
    from app.services.runtime_config_service import RuntimeConfigService

    service = RuntimeConfigService()
    service.update_runtime_config({"provider": "openai", "temperature": 0.6})
    first = json.loads(runtime_config_file.read_text(encoding="utf-8"))
    assert first["llm"]["provider_api_keys"]["openai"] == "primary-secret-value"

    service.update_runtime_config(
        {"provider": "openai", "api_key": "", "temperature": 0.7}
    )
    second = json.loads(runtime_config_file.read_text(encoding="utf-8"))
    assert second["llm"]["provider_api_keys"]["openai"] == "primary-secret-value"


def test_explicit_clear_only_removes_selected_provider_key(runtime_config_file: Path) -> None:
    _write_runtime(runtime_config_file)
    from app.services.runtime_config_service import RuntimeConfigService

    RuntimeConfigService().update_runtime_config(
        {"provider": "openai", "clear_api_key": True}
    )
    saved = json.loads(runtime_config_file.read_text(encoding="utf-8"))

    assert saved["llm"]["primary"]["api_key"] == ""
    assert saved["llm"]["provider_api_keys"]["openai"] == ""
    assert saved["llm"]["provider_api_keys"]["deepseek"] == "secondary-secret-value"


def test_provider_profiles_survive_provider_switches(runtime_config_file: Path) -> None:
    _write_runtime(runtime_config_file)
    from app.services.runtime_config_service import RuntimeConfigService

    service = RuntimeConfigService()
    service.update_runtime_config(
        {
            "provider": "deepseek",
            "format": "openai_compatible",
            "base_url": "https://new-deepseek.invalid/v1",
            "model": "new-deepseek-model",
        }
    )
    service.update_runtime_config(
        {
            "provider": "openai",
            "format": "openai_compatible",
            "base_url": "https://new-openai.invalid/v1",
            "model": "new-openai-model",
        }
    )

    summary = service.get_public_runtime_summary()
    assert summary["provider_profiles"]["deepseek"]["base_url"] == "https://new-deepseek.invalid/v1"
    assert summary["provider_profiles"]["deepseek"]["model"] == "new-deepseek-model"
    assert summary["provider_profiles"]["openai"]["model"] == "new-openai-model"
