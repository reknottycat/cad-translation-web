# Unified Config Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Consolidate CAD CLI and backend runtime settings into one schema-driven config system with a single main entry point, fixed global/project file locations, deep merge, and predictable precedence.

**Architecture:** Add a shared config manager in the backend that loads defaults, global config, project config, env overrides, and CLI overrides into one validated Pydantic model. Point existing runtime-config and CLI entry points at this manager so user-facing config commands and translation/CAD defaults resolve through one source of truth.

**Tech Stack:** Python, Pydantic, Click, pytest

---

### Task 1: Lock the target behavior with tests

**Files:**
- Modify: `agent-harness/cli_anything/cad/tests/test_core.py`
- Modify: `tests/backend/test_backend_runtime.py`

**Step 1: Write the failing tests**

- Add a core test for deep-merged config resolution with precedence:
  `CLI > ENV > project rc > global config > defaults`
- Add a core test for fixed config paths:
  global config under `~/.config/cli-anything-cad/config.json`
  project config in current working directory as `.cli-anything-cadrc`
- Add a core test for CLI `config get` and `config validate`
- Add a backend test for schema validation rejecting invalid `translation_mode`

**Step 2: Run tests to verify they fail**

Run:
`python -m pytest agent-harness/cli_anything/cad/tests/test_core.py tests/backend/test_backend_runtime.py -k "config" -v`

Expected:
new config tests fail because the unified config manager and commands do not exist yet

**Step 3: Commit**

```bash
git add agent-harness/cli_anything/cad/tests/test_core.py tests/backend/test_backend_runtime.py docs/plans/2026-03-16-unified-config-implementation.md
git commit -m "test: add unified config expectations"
```

### Task 2: Build the shared config manager

**Files:**
- Create: `backend/app/services/config_manager.py`
- Modify: `backend/app/config.py`

**Step 1: Write the failing test**

- Add a backend test that imports the manager and verifies:
  - defaults are loaded
  - global config is read from XDG path
  - project config is read from cwd
  - include/import fragments are deep-merged before the main file
  - invalid values raise validation errors

**Step 2: Run test to verify it fails**

Run:
`python -m pytest tests/backend/test_backend_runtime.py::test_config_manager_resolves_precedence_and_deep_merge -v`

Expected:
FAIL because `config_manager.py` and the schema are missing

**Step 3: Write minimal implementation**

- Define Pydantic models for the full config document
- Implement path helpers for:
  - global: `~/.config/cli-anything-cad/config.json`
  - project: `.cli-anything-cadrc`
- Implement recursive deep merge
- Implement config resolution order:
  defaults -> global -> project -> env -> cli overrides
- Add `include` handling for config fragments

**Step 4: Run test to verify it passes**

Run:
`python -m pytest tests/backend/test_backend_runtime.py::test_config_manager_resolves_precedence_and_deep_merge -v`

Expected:
PASS

**Step 5: Commit**

```bash
git add backend/app/services/config_manager.py backend/app/config.py tests/backend/test_backend_runtime.py
git commit -m "feat: add shared unified config manager"
```

### Task 3: Point runtime services at the unified config

**Files:**
- Modify: `backend/app/services/runtime_config_service.py`
- Modify: `backend/app/services/llm/translation_service.py`

**Step 1: Write the failing test**

- Add backend tests that verify runtime summaries and updates now use the unified config manager paths and schema

**Step 2: Run test to verify it fails**

Run:
`python -m pytest tests/backend/test_backend_runtime.py -k "runtime_config or translation_config" -v`

Expected:
FAIL because runtime services still read the legacy backend-local JSON directly

**Step 3: Write minimal implementation**

- Replace direct JSON path usage with the config manager
- Preserve current public API shape where possible
- Write validated updates back into the single main config file

**Step 4: Run test to verify it passes**

Run:
`python -m pytest tests/backend/test_backend_runtime.py -k "runtime_config or translation_config" -v`

Expected:
PASS

**Step 5: Commit**

```bash
git add backend/app/services/runtime_config_service.py backend/app/services/llm/translation_service.py tests/backend/test_backend_runtime.py
git commit -m "refactor: route runtime settings through unified config"
```

### Task 4: Expand CLI config commands

**Files:**
- Modify: `agent-harness/cli_anything/cad/cad_cli.py`
- Modify: `agent-harness/cli_anything/cad/tests/test_core.py`

**Step 1: Write the failing test**

- Add CLI tests for:
  - `config get cad.target_language`
  - `config validate`
  - `config show` displaying global/project paths and precedence-aware values

**Step 2: Run test to verify it fails**

Run:
`python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -k "config_get or config_validate or config_show" -v`

Expected:
FAIL because those commands and outputs do not exist yet

**Step 3: Write minimal implementation**

- Add `config get`
- Add `config validate`
- Keep `config set` but write into the unified config file through the config manager

**Step 4: Run test to verify it passes**

Run:
`python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -k "config_get or config_validate or config_show" -v`

Expected:
PASS

**Step 5: Commit**

```bash
git add agent-harness/cli_anything/cad/cad_cli.py agent-harness/cli_anything/cad/tests/test_core.py
git commit -m "feat: add config get and validate commands"
```

### Task 5: Update docs and run full verification

**Files:**
- Modify: `agent-harness/cli_anything/cad/README.md`

**Step 1: Update docs**

- Document the single main config model
- Document the fixed paths and precedence
- Document `config get/set/validate`

**Step 2: Run verification**

Run:
`python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -v`

Run:
`python -m pytest tests/backend/test_backend_runtime.py -v`

Run:
`python -m pytest agent-harness/cli_anything/cad/tests/test_full_e2e.py::test_dwg_convert_extract_apply_roundtrip -v -s`

Run:
`python -m cli_anything.cad --json config show`

Run:
`python -m cli_anything.cad --json config validate`

Expected:
all verification commands pass

**Step 3: Commit**

```bash
git add agent-harness/cli_anything/cad/README.md
git commit -m "docs: document unified config workflow"
```
