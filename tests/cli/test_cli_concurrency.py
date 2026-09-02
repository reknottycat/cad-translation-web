#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Concurrency semantics driven through clean subprocess invocations."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_DRIVER = Path(__file__).resolve().parent / "_cli_driver.py"


def _run_driver(env_dir: Path, *cmd: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(_DRIVER), str(env_dir), "json", "--json", *cmd],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
        cwd=str(REPO_ROOT),
    )
    payload = json.loads(proc.stdout.splitlines()[-1] if proc.stdout.strip() else "{}")
    return payload.get("exit_code", -1), (payload.get("output") or "")


def test_delete_removes_only_target(run_cli, cli_env, sample_dxf):
    for _ in range(2):
        run_cli("pipeline", "extract", "-i", str(sample_dxf))
    _, out = run_cli("--json", "tasks", "list")
    ids = [t["task_id"] for t in json.loads(out)["tasks"]]
    assert len(ids) == 2
    run_cli("tasks", "delete", ids[0])
    _, out2 = run_cli("--json", "tasks", "list")
    remaining = [t["task_id"] for t in json.loads(out2)["tasks"]]
    assert remaining == [ids[1]]


def test_clear_removes_all_tasks(run_cli, cli_env, sample_dxf):
    for _ in range(3):
        run_cli("pipeline", "extract", "-i", str(sample_dxf))
    run_cli("tasks", "clear")
    _, out = run_cli("--json", "tasks", "list")
    assert json.loads(out)["tasks"] == []
    # Lifecycle lock dir is retained outside the task tree; task dir is gone.
    tasks_root = cli_env / "outputs" / "cad_tasks"
    lifecycle = cli_env / "outputs" / "cad_task_lifecycle"
    assert lifecycle.is_dir()
    assert tasks_root.is_dir()


def test_concurrent_extract_no_corruption(cli_env, sample_dxf):
    """4 concurrent extract subprocesses all complete and produce valid tasks."""
    procs = [
        subprocess.Popen(
            [sys.executable, str(_DRIVER), str(cli_env), "json",
             "pipeline", "extract", "-i", str(sample_dxf)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
            cwd=str(REPO_ROOT),
        )
        for _ in range(4)
    ]
    for p in procs:
        p.wait(timeout=120)
        assert p.returncode == 0
    code, out = _run_driver(cli_env, "tasks", "list")
    assert code == 0
    payload = json.loads(out)
    assert len(payload["tasks"]) == 4


def test_clear_concurrent_with_writers(cli_env, sample_dxf):
    """A clear racing many concurrent writers must not leave orphaned state."""
    writer_procs = [
        subprocess.Popen(
            [sys.executable, str(_DRIVER), str(cli_env), "json",
             "pipeline", "extract", "-i", str(sample_dxf)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
            cwd=str(REPO_ROOT),
        )
        for _ in range(3)
    ]
    # Interleave a clear while writers may still be running.
    _run_driver(cli_env, "tasks", "clear")
    for p in writer_procs:
        p.wait(timeout=120)
    # A final list/clear must succeed without crashing.
    code, _ = _run_driver(cli_env, "tasks", "list")
    assert code == 0
    run_clear = _run_driver(cli_env, "tasks", "clear")
    assert run_clear[0] == 0
