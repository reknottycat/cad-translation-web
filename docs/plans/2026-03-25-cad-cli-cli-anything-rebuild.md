# CAD CLI Rebuild Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the CAD CLI around the CLI-Anything harness standard, keeping the backend as a local engine while preserving the core user-facing variables and leaving room for the CAD-specific features that will be added later.

**Architecture:** Treat `agent-harness/cli_anything/cad` as the new source of truth and keep `cad_legacy` only as an archive. The new CLI stays Click-based with REPL + JSON output, but the code is reorganized into a thin command layer, a backend-bridge layer, and a config/onboarding layer so future CAD-specific features can land without colliding with the harness skeleton.

**Tech Stack:** Python 3.10+, Click, pytest, prompt-toolkit, setuptools namespace packages, backend local bridge modules under `backend/app/*`.

---

### Task 1: Freeze the new package boundary and keep the legacy tree out of runtime paths

**Files:**
- Modify: `agent-harness/setup.py`
- Modify: `pytest.ini`
- Modify: `agent-harness/MANIFEST.in`
- Modify: `agent-harness/CAD.md`

**Step 1: Write the failing test**

Add or update a packaging smoke test that asserts the installed package exposes `cli_anything.cad` only and that `cad_legacy` is not part of the install surface or pytest discovery.

**Step 2: Run test to verify it fails**

Run:
```bash
python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -k namespace_package_importable -v
python -m build
```
Expected: the new packaging rule should fail until the package boundary is explicitly narrowed.

**Step 3: Write minimal implementation**

Update `setup.py` so the console entry point stays `cli-anything-cad=cli_anything.cad.cad_cli:main`, namespace packaging includes only the active tree, and the legacy archive is excluded. Add `cad_legacy` to `norecursedirs` in `pytest.ini` and document the archive boundary in `CAD.md`.

**Step 4: Run test to verify it passes**

Run:
```bash
python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -k namespace_package_importable -v
python -m build
```
Expected: pass, and the build must not bundle `cad_legacy` as a runtime package.

**Step 5: Commit**

```bash
git add agent-harness/setup.py agent-harness/MANIFEST.in pytest.ini agent-harness/CAD.md
git commit -m "chore: freeze CAD CLI package boundary"
```

### Task 2: Re-center the CLI around the harness-standard command surface

**Files:**
- Modify: `agent-harness/cli_anything/cad/cad_cli.py`
- Modify: `agent-harness/cli_anything/cad/__main__.py`
- Modify: `agent-harness/cli_anything/cad/README.md`
- Modify: `agent-harness/cli_anything/cad/README_CN.md`

**Step 1: Write the failing test**

Add tests that assert the top-level command surface contains the harness-standard entry points:
`onboard`, `config`, `project`, `files`, `pipeline`, `tasks`, and `repl`.

**Step 2: Run test to verify it fails**

Run:
```bash
python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -k 'help_command or onboard' -v
```
Expected: fail until the new command surface is present and stable.

**Step 3: Write minimal implementation**

Keep the current Click root group, but reduce it to the harness-style entry points and route `invoke_without_command=True` to `repl`. Make `onboard` the explicit first-run entry. Keep the current helper-based JSON/Human output behavior.

**Step 4: Run test to verify it passes**

Run:
```bash
python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -k 'help_command or onboard' -v
python -m cli_anything.cad --help
```
Expected: pass, and `--help` must show the harness command groups.

**Step 5: Commit**

```bash
git add agent-harness/cli_anything/cad/cad_cli.py agent-harness/cli_anything/cad/__main__.py agent-harness/cli_anything/cad/README.md agent-harness/cli_anything/cad/README_CN.md
git commit -m "feat: align CAD CLI with harness command surface"
```

### Task 3: Keep the core user variables, but isolate them behind onboarding and config APIs

**Files:**
- Modify: `agent-harness/cli_anything/cad/cad_cli.py`
- Modify: `backend/app/services/config_manager.py`
- Modify: `backend/app/services/runtime_config_service.py`
- Modify: `backend/app/functions/dwg_converter.py`
- Modify: `backend/app/services/llm/translation_service.py`
- Modify: `agent-harness/cli_anything/cad/core/project.py`
- Modify: `agent-harness/cli_anything/cad/core/pipeline.py`
- Modify: `tests/backend/test_backend_runtime.py`
- Modify: `agent-harness/cli_anything/cad/tests/test_core.py`

**Step 1: Write the failing test**

Add coverage for the preserved variables:
- target language
- translation mode
- DWG backend
- provider/model/base URL/API key
- glossary file
- system prompt mode

Also add onboarding tests that prove the values can be written into the unified config and read back from the CLI.

**Step 2: Run test to verify it fails**

Run:
```bash
python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -k onboard -v
python -m pytest tests/backend/test_backend_runtime.py -k 'translation_config_can_be_updated_and_read_back or config_manager_can_write_project_config' -v
```
Expected: fail if the new onboarding/config plumbing is not wired through cleanly.

**Step 3: Write minimal implementation**

Keep the current unified config shape, but make the onboarding flow the canonical way to set the preserved variables. Leave the advanced CAD-specific model options for later tasks, and only add the stable config pathways needed for the new skeleton.

**Step 4: Run test to verify it passes**

Run:
```bash
python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -k onboard -v
python -m pytest tests/backend/test_backend_runtime.py -k 'translation_config_can_be_updated_and_read_back or config_manager_can_write_project_config' -v
```
Expected: pass, and onboarding must persist the key variables without breaking the old config precedence rules.

**Step 5: Commit**

```bash
git add agent-harness/cli_anything/cad/cad_cli.py backend/app/services/config_manager.py backend/app/services/runtime_config_service.py backend/app/functions/dwg_converter.py backend/app/services/llm/translation_service.py agent-harness/cli_anything/cad/core/project.py agent-harness/cli_anything/cad/core/pipeline.py tests/backend/test_backend_runtime.py agent-harness/cli_anything/cad/tests/test_core.py
git commit -m "feat: isolate CAD onboarding and config variables"
```

### Task 4: Refresh docs and tests so the new skeleton is the only thing people follow

**Files:**
- Modify: `agent-harness/cli_anything/cad/tests/TEST.md`
- Modify: `agent-harness/cli_anything/cad/QA.md`
- Modify: `agent-harness/cli_anything/cad/QA_CN.md`
- Modify: `agent-harness/cli_anything/cad/improve.md`
- Modify: `agent-harness/cli_anything/cad/README.md`
- Modify: `agent-harness/cli_anything/cad/README_CN.md`

**Step 1: Write the failing test**

Add a documentation check or a simple content assertion to confirm the docs mention:
- the harness-standard command surface
- the legacy archive boundary
- the fact that CAD-specific features will land later

**Step 2: Run test to verify it fails**

Run:
```bash
python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -k 'release_build_help_exists or release_package_info_json' -v
```
Expected: fail until the docs and command references match the new structure.

**Step 3: Write minimal implementation**

Update the docs so the root README stays short, the CAD README becomes the real usage guide, and the QA/improve docs explain the current split between harness skeleton and later CAD-specific enhancements.

**Step 4: Run test to verify it passes**

Run:
```bash
python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -k 'release_build_help_exists or release_package_info_json' -v
python -m build
```
Expected: pass, and the package build should remain clean.

**Step 5: Commit**

```bash
git add agent-harness/cli_anything/cad/tests/TEST.md agent-harness/cli_anything/cad/QA.md agent-harness/cli_anything/cad/QA_CN.md agent-harness/cli_anything/cad/improve.md agent-harness/cli_anything/cad/README.md agent-harness/cli_anything/cad/README_CN.md
git commit -m "docs: align CAD harness docs with new rebuild"
```

