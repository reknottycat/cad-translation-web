#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Path safety: task-id traversal, output sanitisation, project traversal."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "bad_id",
    [
        "../etc/passwd",
        "..",
        "abc/def",
        "ABC12345",
        "aaaaaaaaa",
        "zzzzzzzz",
        ".hidden",
    ],
)
def test_task_id_traversal_rejected(run_cli, bad_id):
    for sub in ("show", "delete"):
        code, out = run_cli("tasks", sub, bad_id, expect_ok=False)
        assert code != 0


def test_output_filenames_are_sanitised(cli_env):
    from app.utils.file_utils import get_safe_filename

    safe = get_safe_filename("../../evil<name>.dxf")
    assert "/" not in safe
    assert "\\" not in safe
    assert ".." not in safe


def test_relative_path_resolution_stays_in_output_root(cli_env):
    from app.utils.file_utils import resolve_within_directory

    root = cli_env / "outputs"
    root.mkdir(parents=True, exist_ok=True)
    inside = resolve_within_directory(root, "cad_tasks/abc")
    assert inside == (root / "cad_tasks" / "abc").resolve()
    with pytest.raises(ValueError):
        resolve_within_directory(root, "/etc")
