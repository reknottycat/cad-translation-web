#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Concurrent / atomic runtime config writes, and config value round-trips."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_DRIVER = Path(__file__).resolve().parent / "_cli_driver.py"


def _set_lang(env_dir: Path, lang: str) -> int:
    proc = subprocess.run(
        [sys.executable, str(_DRIVER), str(env_dir), "json",
         "config", "set", "--target-language", lang],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
        cwd=str(REPO_ROOT),
    )
    payload = json.loads(proc.stdout.splitlines()[-1] if proc.stdout.strip() else "{}")
    return payload.get("exit_code", -1)


def test_concurrent_config_writes_produce_valid_json(cli_env):
    langs = ["fr", "de", "es", "zh", "ja", "ko"]
    procs = [subprocess.Popen([sys.executable, _DRIVER, str(cli_env), "json",
                               "config", "set", "--target-language", lang],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(REPO_ROOT))
             for lang in langs]
    for p in procs:
        p.wait(timeout=120)
        assert p.returncode == 0
    cfg_path = cli_env / "config.json"
    # Config file must remain valid JSON after concurrent atomic writes.
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert data["cad"]["target_language"] in langs


def test_config_set_get_roundtrip(run_cli, cli_env):
    run_cli("config", "set", "--target-language", "it")
    data = json.loads((cli_env / "config.json").read_text(encoding="utf-8"))
    assert data["cad"]["target_language"] == "it"
    _, out = run_cli("--json", "config", "get", "cad.target_language")
    assert json.loads(out)["value"] == "it"
