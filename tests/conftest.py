#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test configuration for the CAD translation backend."""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure backend modules are importable
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# Set test environment BEFORE importing any app modules.
# Use a temporary directory for all runtime data.
_test_env = tempfile.mkdtemp(prefix="cad_test_")
os.environ["CAD_TRANSLATION_ENV_FILE"] = str(Path(_test_env) / ".env")
os.environ["CAD_TRANSLATION_RUNTIME_CONFIG_FILE"] = str(Path(_test_env) / "config.json")
os.environ["ASYNC_TASKS_MODE"] = "local"

# Write a minimal .env file
env_path = Path(_test_env) / ".env"
env_path.write_text(
    "DEBUG=false\n"
    f"DATABASE_URL=sqlite:///{Path(_test_env) / 'test.db'}\n"
    f"UPLOAD_DIR={Path(_test_env) / 'uploads'}\n"
    f"OUTPUT_DIR={Path(_test_env) / 'outputs'}\n"
    f"TEMP_DIR={Path(_test_env) / 'temp'}\n"
    "ENABLE_ADMIN_GUARD=false\n"
    "LLM_ALLOW_DEMO_FALLBACK=true\n"
    "LLM_PARALLEL_COUNT=2\n"
    "LLM_BATCH_SIZE=4\n"
    "LLM_RPM=100\n",
    encoding="utf-8",
)

# Write a minimal runtime config file
config_path = Path(_test_env) / "config.json"
config_path.write_text(
    json.dumps(
        {
            "llm": {
                "primary": {
                    "provider": "custom",
                    "format": "openai_compatible",
                    "base_url": "http://localhost:9999/v1",
                    "api_key": "",
                    "model": "test-model",
                },
                "allow_demo_fallback": True,
                "batch_size": 4,
                "parallel_count": 2,
            },
            "cad": {
                "target_language": "en",
                "translation_mode": "replace",
                "font_name": "Times New Roman",
                "font_size_reduction": 2,
                "converter_backend": "dxf_only",
            },
        }
    ),
    encoding="utf-8",
)


@pytest.fixture(autouse=True)
def reset_settings():
    """Reset the cached Settings instance between tests."""
    import app.config as config_module

    config_module._settings = None
    yield
    config_module._settings = None


@pytest.fixture
def test_env_dir() -> Path:
    return Path(_test_env)


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).resolve().parent / "fixtures"
