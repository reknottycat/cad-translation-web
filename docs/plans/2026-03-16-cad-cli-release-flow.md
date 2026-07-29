# CAD CLI Release Flow Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a beginner-friendly local release flow to `cli-anything-cad` so the user can build, inspect, and smoke-test the package with a small set of commands.

**Architecture:** Keep the release flow inside the existing Click CLI by adding a `release` command group that shells out to standard Python packaging commands. Pair that with a minimal README update and a few ignore-rule cleanup changes so local packaging does not leave confusing workspace noise behind.

**Tech Stack:** Python 3.12, Click, setuptools, pytest, standard library `subprocess`, existing `cli_anything.cad` package.

---

### Task 1: Add failing CLI tests for the release command group

**Files:**
- Modify: `agent-harness/cli_anything/cad/tests/test_core.py`
- Modify: `agent-harness/cli_anything/cad/tests/test_full_e2e.py`

**Step 1: Write the failing tests**

Add tests that expect:

- `cli-anything-cad release package-info --json` returns package metadata
- `cli-anything-cad release build --help` exists
- `cli-anything-cad release smoke --help` exists

**Step 2: Run the tests to verify they fail**

Run:

```bash
python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -v
```

Expected: release command tests fail because the command group does not exist yet.

### Task 2: Implement release helpers and Click commands

**Files:**
- Create: `agent-harness/cli_anything/cad/core/release.py`
- Modify: `agent-harness/cli_anything/cad/cad_cli.py`
- Modify: `agent-harness/setup.py`

**Step 1: Add minimal release helpers**

Implement:

- `package_info()`
- `build_distributions()`
- `run_smoke_checks()`

The helpers should:

- build into `agent-harness/dist`
- call `python -m build`
- run smoke commands against the local CLI module
- return structured dict payloads

**Step 2: Expose the `release` command group**

Add:

- `release package-info`
- `release build`
- `release smoke`

### Task 3: Document the beginner flow and reduce workspace noise

**Files:**
- Modify: `agent-harness/cli_anything/cad/README.md`
- Modify: `agent-harness/cli_anything/cad/tests/TEST.md`
- Modify: `.gitignore`

**Step 1: Document the two-command release flow**

Keep the README focused on:

1. `cli-anything-cad release build`
2. `cli-anything-cad release smoke`

**Step 2: Ignore local release/test artifacts**

Add ignore rules for:

- `tools/AcadSharpBridge/bin/`
- `tools/AcadSharpBridge/obj/`
- `output/cad_cli_convert_test/`

### Task 4: Verify the new flow end to end

**Files:**
- No new files required

**Step 1: Run targeted unit tests**

```bash
python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -v
```

**Step 2: Run release smoke checks through the CLI**

```bash
python -m cli_anything.cad release package-info --json
python -m cli_anything.cad release build
python -m cli_anything.cad release smoke
```

**Step 3: Run the existing important regression checks**

```bash
python -m pytest tests/backend/test_backend_runtime.py::test_dwg_converter_resolves_acadsharp_project_relative_to_repo_root tests/backend/test_backend_runtime.py::test_text_applier_can_save_acadsharp_converted_dxf agent-harness/cli_anything/cad/tests/test_full_e2e.py::test_dwg_convert_extract_apply_roundtrip -v -s
```
