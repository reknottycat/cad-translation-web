#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared fixtures for the cad-translate CLI regression tests.

CLI tests run in a **fresh subprocess** per invocation (see ``_cli_driver.py``)
so the runtime environment (dotenv path, output root) is baked before
``app.config`` is first imported -- this is exactly the "clean environment"
scenario the acceptance criteria require and avoids cross-test config caching.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_HARNESS = REPO_ROOT / "agent-harness"
_DRIVER = Path(__file__).resolve().parent / "_cli_driver.py"


@pytest.fixture()
def cli_env(tmp_path: Path) -> Path:
    """A fresh, isolated runtime environment (temp .env, config, output root)."""
    env_dir = tmp_path / "env"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / ".env").write_text(
        f"DEBUG=false\n"
        f"DATABASE_URL=sqlite:///{env_dir}/test.db\n"
        f"UPLOAD_DIR={env_dir}/uploads\n"
        f"OUTPUT_DIR={env_dir}/outputs\n"
        f"ENABLE_ADMIN_GUARD=false\n"
        f"LLM_ALLOW_DEMO_FALLBACK=true\n"
        f"ASYNC_TASKS_MODE=local\n"
        f"DWG_CONVERTER_BACKEND=dxf_only\n",
        encoding="utf-8",
    )
    (env_dir / "config.json").write_text(
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
    return env_dir


@pytest.fixture()
def run_cli(cli_env: Path):
    """Return a callable that runs the CLI in a subprocess and returns (exit, out)."""

    def _run(*cmd: str, expect_ok: bool = True) -> tuple[int, str]:
        proc = subprocess.run(
            [sys.executable, str(_DRIVER), str(cli_env), "text", *cmd],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
            cwd=str(REPO_ROOT),
        )
        # The driver always prints one JSON line on stdout.
        payload = json.loads(proc.stdout.splitlines()[-1] if proc.stdout.strip() else "{}")
        out = payload.get("output") or ""
        code = payload.get("exit_code", -1)
        if expect_ok:
            assert code == 0, f"command {cmd!r} failed:\n{out}\n{proc.stderr}"
        return code, out

    return _run


@pytest.fixture()
def sample_dxf() -> Path:
    return REPO_ROOT / "tests" / "fixtures" / "building_a.dxf"
