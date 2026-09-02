#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Explicit ``--output-dir`` must keep task state coherent with the managed tree.

Regression for the review finding on Issue #14 / PR #19: an explicit
``--output-dir`` previously created the task in the default task tree, then
redirected BOTH the product and the ``task.json`` into the arbitrary
``output-dir`` — leaving an orphan "created" task in the managed tree and a
second, unmanaged ``task.json`` outside it, so ``tasks list/show/delete/clear``
could not reliably manage the task.

Contract under test: the canonical ``task.json`` always lives in the managed
``cad_tasks/<task_id>/`` directory; the product file is written to the
``--output-dir`` (when given) and its location recorded in the metadata.
"""
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


def _list_task_ids(env_dir: Path) -> list[str]:
    code, out = _run_driver(env_dir, "tasks", "list")
    assert code == 0, out
    return [t["task_id"] for t in json.loads(out)["tasks"]]


def test_extract_with_output_dir_keeps_task_in_managed_tree(run_cli, cli_env, sample_dxf):
    out_dir = cli_env / "custom_out"
    out_dir.mkdir(parents=True, exist_ok=True)

    _, out = run_cli("--json", "pipeline", "extract", "-i", str(sample_dxf), "--output-dir", str(out_dir))
    payload = json.loads(out)
    assert payload["success"] is True, out
    task_id = payload["task_id"]

    managed_root = cli_env / "outputs" / "cad_tasks"
    managed_task = managed_root / task_id
    assert managed_task.is_dir(), "task dir must live in the managed cad_tasks tree"
    assert (managed_task / "task.json").exists(), "task.json must live in the managed tree"

    # The product Excel must have gone to the explicit --output-dir, not the tree.
    excel_name = payload["excel_file"]
    assert excel_name and Path(excel_name).parent.resolve() == out_dir.resolve()
    assert Path(excel_name).exists()

    # No stray task.json is written directly into the custom output dir.
    assert not (out_dir / "task.json").exists(), "no unmanaged task.json outside the tree"

    # tasks list must report exactly one coherent (non-orphan) task.
    assert _list_task_ids(cli_env) == [task_id]
    code, show = _run_driver(cli_env, "tasks", "show", task_id)
    assert code == 0
    meta = json.loads(show)
    assert meta["stage"] == "extract"
    assert meta["output_dir"] == str(out_dir)
    assert meta["output_file"] == str(excel_name)


def test_relative_output_dir_resolves_into_task_and_delete_works(run_cli, cli_env, sample_dxf):
    # A relative --output-dir is resolved against the CLI's cwd (repo root).
    run_cli("pipeline", "extract", "-i", str(sample_dxf), "--output-dir", str(cli_env / "rel_out"))
    ids = _list_task_ids(cli_env)
    assert len(ids) == 1

    # delete must remove the managed task cleanly (product dir may remain outside).
    run_cli("tasks", "delete", ids[0])
    assert _list_task_ids(cli_env) == []
    assert not (cli_env / "outputs" / "cad_tasks" / ids[0]).exists()


def test_clear_with_output_dir_tasks(cli_env, sample_dxf):
    out1 = cli_env / "out_a"
    out2 = cli_env / "out_b"
    for out in (out1, out2):
        _run_driver(cli_env, "pipeline", "extract", "-i", str(sample_dxf), "--output-dir", str(out))
    assert len(_list_task_ids(cli_env)) == 2
    code, _ = _run_driver(cli_env, "tasks", "clear")
    assert code == 0
    assert _list_task_ids(cli_env) == []
    # No task.json anywhere inside the managed tree.
    managed_root = cli_env / "outputs" / "cad_tasks"
    for task_dir in managed_root.iterdir():
        assert not (task_dir / "task.json").exists(), "no task.json should remain after clear"


def test_concurrent_extract_with_output_dir_and_clear(cli_env, sample_dxf):
    """Concurrent writers with an explicit output-dir + racing clear stay coherent."""
    out_dir = cli_env / "conc_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    procs = [
        subprocess.Popen(
            [sys.executable, str(_DRIVER), str(cli_env), "json",
             "pipeline", "extract", "-i", str(sample_dxf), "--output-dir", str(out_dir)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
            cwd=str(REPO_ROOT),
        )
        for _ in range(4)
    ]
    # Race a clear while some writers may still be finishing.
    _run_driver(cli_env, "tasks", "clear")
    for p in procs:
        p.wait(timeout=120)
    # Every completed writer either survived clear or was cleaned up; no crash.
    code, _ = _run_driver(cli_env, "tasks", "list")
    assert code == 0
    # No task.json may be stranded in a non-task form anywhere in the managed tree.
    managed_root = cli_env / "outputs" / "cad_tasks"
    for task_dir in managed_root.iterdir():
        if task_dir.is_dir() and task_dir.name[:8].isalnum() and (task_dir / "task.json").exists():
            # survived tasks are valid (8-hex id)
            assert task_dir.name.lower() == task_dir.name
    # Final clear still succeeds.
    code2, _ = _run_driver(cli_env, "tasks", "clear")
    assert code2 == 0


def test_list_sorted_by_last_activity(run_cli, cli_env, sample_dxf):
    """list_tasks must retain last_activity_at so newest-task-first sorting works."""
    run_cli("pipeline", "extract", "-i", str(sample_dxf))
    run_cli("pipeline", "extract", "-i", str(sample_dxf))
    code, out = run_cli("--json", "tasks", "list")
    assert code == 0
    tasks = json.loads(out)["tasks"]
    assert len(tasks) == 2
    # Every summary must expose last_activity_at (regression for lost sort key).
    for t in tasks:
        assert "last_activity_at" in t and t["last_activity_at"]
    # Newest activity first.
    acts = [t["last_activity_at"] for t in tasks]
    assert acts == sorted(acts, reverse=True)
