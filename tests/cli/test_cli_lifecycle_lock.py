#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression: a stage's final task.json write-back must hold the per-task
lifecycle lock, and a concurrent ``tasks clear`` / ``tasks delete`` must never
leave an orphan, partial or duplicate record — writers return 0 with complete
metadata, and surviving tasks are fully queryable.

This is the "hard" regression for PR #19 review blocker: it does **not** merely
check that the final ``tasks list`` succeeds; it asserts each concurrent
writer's subprocess exit code and the integrity of every task.json / the
absence of residual orphan state.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_DRIVER = Path(__file__).resolve().parent / "_cli_driver.py"


def _writer(env_dir: Path, sample_dxf: Path) -> subprocess.Popen:
    """Start one pipeline-extract writer subprocess."""
    return subprocess.Popen(
        [sys.executable, str(_DRIVER), str(env_dir), "json",
         "--json", "pipeline", "extract", "-i", str(sample_dxf)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
        cwd=str(REPO_ROOT),
    )


def _finish(p: subprocess.Popen) -> tuple[int, dict | None, str]:
    """Wait for a writer and return (cli_exit_code, result_dict, raw_err).

    With ``--json`` the CLI emits the result dict (success / task_id / ...) on
    stdout, wrapped by the driver in a single JSON envelope on its last line.
    """
    p.wait(timeout=120)
    assert p.returncode == 0, "subprocess itself must not crash"
    stdout = p.stdout.read() if p.stdout else ""
    stderr = p.stderr.read() if p.stderr else ""
    raw = stdout.strip()
    if not raw:
        return -1, None, f"no output; stderr={stderr}"
    envelope = json.loads(raw.splitlines()[-1])
    code = envelope.get("exit_code", -1)
    out = envelope.get("output") or ""
    result = None
    if out.strip():
        try:
            result = json.loads(out)
        except json.JSONDecodeError:
            result = None
    return code, result, stderr


def _run_driver(env_dir: Path, *cmd: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(_DRIVER), str(env_dir), "json", "--json", *cmd],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
        cwd=str(REPO_ROOT),
    )
    payload = json.loads(proc.stdout.splitlines()[-1] if proc.stdout.strip() else "{}")
    return payload.get("exit_code", -1), (payload.get("output") or "")


def _scan_orphans(env_dir: Path):
    """Return a list of (path, reason) describing residual/orphan task state.

    Any directory directly under cad_tasks/ that is a valid task id must hold a
    complete, parseable task.json.  Anything else that looks like a leftover
    (a task dir with a missing/broken task.json) is an orphan/partial state.
    """
    root = env_dir / "outputs" / "cad_tasks"
    problems: list[tuple[str, str]] = []
    if not root.exists():
        return problems
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            # A stray file directly in the managed tree is abnormal.
            problems.append((str(child), "non-directory entry under cad_tasks/"))
            continue
        name = child.name
        # Only id-shaped dirs are tasks; other dirs (e.g. lifecycle) are unrelated.
        if len(name) == 8 and all(c in "0123456789abcdef" for c in name):
            meta = child / "task.json"
            if not meta.exists():
                problems.append((str(meta), "task dir with missing task.json (orphan)"))
                continue
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                problems.append((str(meta), f"task.json not parseable: {exc}"))
                continue
            # A completed task must carry the finished fields.
            if data.get("status") != "done" or data.get("stage") != "extract":
                problems.append((str(meta), f"incomplete task record: {data.get('status')}/{data.get('stage')}"))
    return problems


def test_clear_racing_writers_asserts_return_codes_and_no_orphan(cli_env, sample_dxf):
    """Clear racing writers: every writer returns 0 with complete metadata and
    no orphan/partial task remains (writers are serialised per-task lifecycle
    lock, so clear waits then removes completed tasks)."""
    writers = [_writer(cli_env, sample_dxf) for _ in range(4)]
    # Race a clear while writers may still be running/finishing.
    code, _ = _run_driver(cli_env, "tasks", "clear")
    assert code == 0, "tasks clear must succeed"

    results = [_finish(w) for w in writers]
    for code, payload, stderr in results:
        assert code == 0, f"writer should succeed; payload={payload} stderr={stderr}"
        assert payload is not None and payload.get("success") is True
        task_id = payload.get("task_id")
        assert task_id, payload

    # No residual/orphan task state under the managed tree.
    assert _scan_orphans(cli_env) == [], f"orphan/partial state left: {_scan_orphans(cli_env)}"

    # A follow-up list and clear must still behave.
    code, out = _run_driver(cli_env, "tasks", "list")
    assert code == 0
    # Every writer finished under the lifecycle lock; clear either removed the
    # task or the writer's task survived clear — both are consistent states.
    remaining = [t["task_id"] for t in json.loads(out)["tasks"]]
    known = {r[1]["task_id"] for r in results if r[1]}
    for tid in remaining:
        assert tid in known, f"unexpected task {tid} left after clear"
    code2, _ = _run_driver(cli_env, "tasks", "clear")
    assert code2 == 0
    assert _scan_orphans(cli_env) == []


def test_delete_racing_writers_targets_only_one_task(cli_env, sample_dxf):
    """A delete aimed at one specific task races writers; the deleted task is
    fully gone, other tasks are complete and valid, and no orphan remains."""
    # Pre-create a stable task to delete later.
    w = _writer(cli_env, sample_dxf)
    code, payload, _ = _finish(w)
    assert code == 0
    target = payload["task_id"]

    writers = [_writer(cli_env, sample_dxf) for _ in range(3)]
    code, _ = _run_driver(cli_env, "tasks", "delete", target)
    assert code == 0, "tasks delete must succeed"

    results = [_finish(w) for w in writers]
    for code, payload, stderr in results:
        assert code == 0, f"writer should succeed; payload={payload} stderr={stderr}"

    # Deleted target must be gone and not re-created as an orphan.
    code, out = _run_driver(cli_env, "tasks", "list")
    assert code == 0
    tasks = json.loads(out)["tasks"]
    ids = [t["task_id"] for t in tasks]
    assert target not in ids, "deleted task must not reappear"

    # Every surviving task is complete/valid metadata.
    for t in tasks:
        assert t["status"] == "done" and t["stage"] == "extract", t
        assert t["last_activity_at"] and t["created_at"], t

    assert _scan_orphans(cli_env) == [], f"orphan/partial state left: {_scan_orphans(cli_env)}"


def test_writer_metadata_roundtrip_complete_after_concurrent_clear(cli_env, sample_dxf):
    """Even under concurrency, a surviving task's task.json is fully complete
    (task_id, original_filename, status=done, stage=extract, output_file)."""
    writers = [_writer(cli_env, sample_dxf) for _ in range(5)]
    _run_driver(cli_env, "tasks", "clear")
    results = [_finish(w) for w in writers]
    for code, payload, stderr in results:
        assert code == 0, (payload, stderr)

    root = cli_env / "outputs" / "cad_tasks"
    if not root.exists():
        return  # clear removed everything; nothing to verify
    for child in root.iterdir():
        meta = child / "task.json"
        if not meta.exists():
            continue
        data = json.loads(meta.read_text(encoding="utf-8"))
        for key in ("task_id", "original_filename", "normalized_dxf_filename",
                    "text_count", "status", "stage", "output_dir", "output_file",
                    "created_at", "last_activity_at"):
            assert key in data, f"{meta} missing {key}"
        assert data["status"] == "done" and data["stage"] == "extract", data
