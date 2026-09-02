#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Clean-environment import, --help / --json / --version / doctor checks."""
from __future__ import annotations

import json
from pathlib import Path


def test_clean_import_and_version(run_cli):
    code, out = run_cli("--version")
    assert "cad-translate" in out
    assert "2.0.0" in out


def test_help_lists_expected_commands(run_cli):
    code, out = run_cli("--help")
    for cmd in ["config", "project", "files", "pipeline", "tasks", "doctor"]:
        assert cmd in out


def test_doctor_reports_locations(run_cli, cli_env):
    code, out = run_cli("doctor")
    assert "backend_dir" in out
    assert str(cli_env / "outputs") in out
    assert "2.0.0" in out


def test_json_output_is_valid_json(run_cli, sample_dxf):
    ex, _ = run_cli("pipeline", "extract", "-i", str(sample_dxf))
    code, out = run_cli("--json", "tasks", "list")
    payload = json.loads(out)
    assert isinstance(payload["tasks"], list)
    assert len(payload["tasks"]) == 1
    assert payload["tasks"][0]["task_id"]


def test_project_new_and_save_roundtrip(run_cli, cli_env):
    proj = cli_env / "my_project.json"
    run_cli("project", "new", "--name", "demo", "-o", str(proj))
    assert proj.exists()
    data = json.loads(proj.read_text(encoding="utf-8"))
    assert data["name"] == "demo"

    # Opening the file again in a fresh process must read the same project.
    run_cli("project", "open", str(proj))
    assert json.loads(proj.read_text(encoding="utf-8"))["name"] == "demo"


def test_pipeline_extract_json(run_cli, cli_env, sample_dxf):
    _, out = run_cli("--json", "pipeline", "extract", "-i", str(sample_dxf))
    payload = json.loads(out)
    assert payload["success"] is True
    assert payload["text_count"] >= 1
    assert (cli_env / "outputs" / "cad_tasks" / payload["task_id"]).is_dir()
