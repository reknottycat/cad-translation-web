#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Subprocess driver for CLI tests.

Usage: python _cli_driver.py <env_dir> <json|text> <cmd...>

Runs the cad-translate CLI inside a fresh process that sets the isolated
runtime env *before* importing app.config, so pydantic-settings bakes the
correct dotenv path. Emits the full result as JSON on stdout and exits with the
CLI exit code.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 4:
        print("usage: driver <env_dir> <json|text> <cmd...>", file=sys.stderr)
        return 2
    env_dir = Path(sys.argv[1])
    mode = sys.argv[2]
    cmd = sys.argv[3:]

    os.environ["CAD_TRANSLATION_ENV_FILE"] = str(env_dir / ".env")
    os.environ["CAD_TRANSLATION_RUNTIME_CONFIG_FILE"] = str(env_dir / "config.json")
    os.environ["ASYNC_TASKS_MODE"] = "local"

    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo / "agent-harness"))
    sys.path.insert(0, str(repo / "backend"))

    from click.testing import CliRunner

    from cad_translate.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, cmd)
    out = result.output
    if mode == "json":
        # Try to parse; some commands emit human text. Return raw text too.
        try:
            parsed = json.loads(out)
            out = out
        except Exception:  # noqa: BLE001
            parsed = None
    payload = {
        "exit_code": result.exit_code,
        "output": out,
        "exception": repr(result.exception) if result.exception else None,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if result.exit_code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
