# CAD CLI Harness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a complete `cli-anything-cad` package under `agent-harness/` that exposes the existing local CAD backend as a full CLI-Anything harness with REPL, JSON output, installable entry point, and tests.

**Architecture:** The implementation keeps the existing CAD backend as the processing engine and adds a thin CLI adaptation layer under the `cli_anything.cad` namespace. The CLI owns lightweight project/session state, while backend task directories and `task.json` remain the source of truth for generated artifacts.

**Tech Stack:** Python 3.10+, Click, prompt-toolkit, setuptools namespace packages, pytest, existing backend modules in `backend/app/functions`, `backend/app/services`, and `backend/app/workflow`

---

### Task 1: Scaffold the CLI-Anything package

**Files:**
- Create: `agent-harness/setup.py`
- Create: `agent-harness/CAD.md`
- Create: `agent-harness/cli_anything/cad/__init__.py`
- Create: `agent-harness/cli_anything/cad/__main__.py`
- Create: `agent-harness/cli_anything/cad/README.md`
- Create: `agent-harness/cli_anything/cad/cad_cli.py`
- Create: `agent-harness/cli_anything/cad/core/__init__.py`
- Create: `agent-harness/cli_anything/cad/utils/__init__.py`
- Create: `agent-harness/cli_anything/cad/tests/TEST.md`

**Step 1: Write the failing package metadata test**

Create `agent-harness/cli_anything/cad/tests/test_core.py` with:

```python
from importlib.util import find_spec


def test_namespace_package_importable():
    spec = find_spec("cli_anything.cad")
    assert spec is not None
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest agent-harness/cli_anything/cad/tests/test_core.py::test_namespace_package_importable -v`
Expected: FAIL because the package and test file do not exist yet.

**Step 3: Create the namespace package scaffold**

Implement:

- `setup.py` using `find_namespace_packages(include=["cli_anything.*"])`
- console entry point `cli-anything-cad=cli_anything.cad.cad_cli:main`
- `__main__.py` that imports and calls `main`
- `README.md` with install, usage, and dependency notes
- `CAD.md` documenting backend mapping and command groups
- initial `TEST.md` with inventory plan placeholders

Use this `setup.py` skeleton:

```python
from setuptools import find_namespace_packages, setup

setup(
    name="cli-anything-cad",
    version="1.0.0",
    packages=find_namespace_packages(include=["cli_anything.*"]),
    install_requires=[
        "click>=8.1.0",
        "prompt-toolkit>=3.0.0",
    ],
    entry_points={
        "console_scripts": [
            "cli-anything-cad=cli_anything.cad.cad_cli:main",
        ],
    },
    python_requires=">=3.10",
)
```

**Step 4: Re-run the package import test**

Run: `python -m pytest agent-harness/cli_anything/cad/tests/test_core.py::test_namespace_package_importable -v`
Expected: PASS

**Step 5: Commit**

```bash
git add agent-harness/setup.py agent-harness/CAD.md agent-harness/cli_anything/cad agent-harness/cli_anything/cad/tests/TEST.md
git commit -m "feat: scaffold cli-anything cad package"
```

### Task 2: Add backend bridge and file/project/session core

**Files:**
- Create: `agent-harness/cli_anything/cad/utils/backend_bridge.py`
- Create: `agent-harness/cli_anything/cad/core/project.py`
- Create: `agent-harness/cli_anything/cad/core/session.py`
- Create: `agent-harness/cli_anything/cad/core/files.py`
- Modify: `agent-harness/cli_anything/cad/tests/test_core.py`

**Step 1: Write failing tests for project/session/files**

Append tests like:

```python
from pathlib import Path

from cli_anything.cad.core.files import scan_cad_files
from cli_anything.cad.core.project import create_project_data
from cli_anything.cad.core.session import Session


def test_create_project_data_defaults():
    data = create_project_data("demo")
    assert data["name"] == "demo"
    assert data["status"] == "idle"
    assert data["source_files"] == []


def test_scan_cad_files_filters_extensions(tmp_path: Path):
    (tmp_path / "a.dwg").write_text("x")
    (tmp_path / "b.dxf").write_text("x")
    (tmp_path / "c.txt").write_text("x")
    result = scan_cad_files(tmp_path)
    assert result["total_dwg"] == 1
    assert result["total_dxf"] == 1


def test_session_tracks_dirty_state():
    session = Session()
    assert session.is_modified() is False
    session.mark_modified()
    assert session.is_modified() is True
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -v`
Expected: FAIL because modules and functions do not exist yet.

**Step 3: Implement the core state modules**

Implement:

- `backend_bridge.py`
  - inserts the repo `backend/` path onto `sys.path`
  - exposes `get_cad_pipeline_service()`, `get_pipeline()`, `get_text_extractor()`, `get_text_applier()`
- `project.py`
  - `create_project_data(name: str) -> dict`
  - `save_project(data: dict, output_path: str) -> dict`
  - `load_project(project_path: str) -> dict`
- `session.py`
  - in-memory state with current project path, data, recent task, active translation map, dirty flag
- `files.py`
  - `scan_cad_files(path)`
  - `validate_input_file(path)`
  - `normalize_path(path)`

Minimal `Session` skeleton:

```python
class Session:
    def __init__(self):
        self.project_path = None
        self.project_data = None
        self.translation_map = {}
        self.recent_task_id = None
        self._modified = False

    def mark_modified(self):
        self._modified = True

    def mark_saved(self):
        self._modified = False

    def is_modified(self):
        return self._modified
```

**Step 4: Re-run the core tests**

Run: `python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -v`
Expected: PASS for the new state and file tests.

**Step 5: Commit**

```bash
git add agent-harness/cli_anything/cad/utils/backend_bridge.py agent-harness/cli_anything/cad/core/project.py agent-harness/cli_anything/cad/core/session.py agent-harness/cli_anything/cad/core/files.py agent-harness/cli_anything/cad/tests/test_core.py
git commit -m "feat: add cad cli state and backend bridge"
```

### Task 3: Implement pipeline and task core modules

**Files:**
- Create: `agent-harness/cli_anything/cad/core/pipeline.py`
- Create: `agent-harness/cli_anything/cad/core/tasks.py`
- Modify: `agent-harness/cli_anything/cad/tests/test_core.py`

**Step 1: Write failing tests for pipeline normalization and task summaries**

Add:

```python
import json

from cli_anything.cad.core.pipeline import build_context
from cli_anything.cad.core.tasks import summarize_task_metadata


def test_build_context_merges_defaults():
    project = {"target_language": "en", "converter_backend": "acadsharp"}
    context = build_context(project_data=project, input_file="a.dxf", output_dir="out")
    assert context["input_file"] == "a.dxf"
    assert context["target_language"] == "en"
    assert context["converter_backend"] == "acadsharp"


def test_summarize_task_metadata_extracts_core_fields():
    metadata = {
        "task_id": "abc12345",
        "original_filename": "a.dwg",
        "text_count": 3,
        "translation_count": 2,
    }
    summary = summarize_task_metadata(metadata)
    assert summary["task_id"] == "abc12345"
    assert summary["text_count"] == 3
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -v`
Expected: FAIL due to missing pipeline/task modules.

**Step 3: Implement the core workflow wrappers**

Implement `pipeline.py` with:

- `build_context(project_data, input_file, output_dir, **overrides)`
- `run_convert(...)`
- `run_extract(...)`
- `run_apply(...)`
- `run_pipeline(...)`

Implementation rule:

- `run_extract` should call the backend text extractor directly for DXF input
- `run_convert` should call the backend converter only for DWG input
- `run_apply` should load or accept translation mappings and call the backend text applier or pipeline apply path
- `run_pipeline` should chain convert, extract, optional translate, and apply

Implement `tasks.py` with:

- `tasks_root()`
- `list_tasks()`
- `load_task(task_id)`
- `summarize_task_metadata(metadata)`
- `delete_task(task_id)`
- `clear_tasks()`

Minimal summary shape:

```python
{
    "task_id": metadata["task_id"],
    "original_filename": metadata["original_filename"],
    "text_count": metadata.get("text_count", 0),
    "translation_count": metadata.get("translation_count", 0),
}
```

**Step 4: Re-run the tests**

Run: `python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -v`
Expected: PASS for the new pipeline and task tests.

**Step 5: Commit**

```bash
git add agent-harness/cli_anything/cad/core/pipeline.py agent-harness/cli_anything/cad/core/tasks.py agent-harness/cli_anything/cad/tests/test_core.py
git commit -m "feat: add cad cli pipeline and task core"
```

### Task 4: Implement Click commands and REPL integration

**Files:**
- Modify: `agent-harness/cli_anything/cad/cad_cli.py`
- Create: `agent-harness/cli_anything/cad/utils/repl_skin.py`
- Modify: `agent-harness/cli_anything/cad/tests/test_core.py`

**Step 1: Write failing CLI smoke tests**

Add:

```python
from click.testing import CliRunner

from cli_anything.cad.cad_cli import cli


def test_help_command():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "project" in result.output


def test_project_new_json():
    result = CliRunner().invoke(cli, ["--json", "project", "new", "--name", "demo"])
    assert result.exit_code == 0
    assert '"project": "demo"' in result.output
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -v`
Expected: FAIL because CLI groups are incomplete.

**Step 3: Implement the CLI surface**

In `cad_cli.py`:

- use `@click.group(invoke_without_command=True)`
- add global `--json` and `--project`
- default to `repl` when no subcommand is provided
- implement command groups:
  - `project`
  - `files`
  - `pipeline`
  - `tasks`
  - `config`
  - `repl`
- route all command bodies through the `core` modules

Copy `repl_skin.py` from the CLI-Anything plugin into `utils/repl_skin.py`.

Minimal CLI structure:

```python
@click.group(invoke_without_command=True)
@click.option("--json", "json_mode", is_flag=True)
@click.option("--project", type=click.Path())
@click.pass_context
def cli(ctx, json_mode, project):
    if ctx.invoked_subcommand is None:
        ctx.invoke(repl, project_path=project)
```

**Step 4: Re-run core CLI smoke tests**

Run: `python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -v`
Expected: PASS for `--help` and `project new`.

**Step 5: Commit**

```bash
git add agent-harness/cli_anything/cad/cad_cli.py agent-harness/cli_anything/cad/utils/repl_skin.py agent-harness/cli_anything/cad/tests/test_core.py
git commit -m "feat: add cad cli commands and repl"
```

### Task 5: Finish the test plan and expand unit coverage

**Files:**
- Modify: `agent-harness/cli_anything/cad/tests/TEST.md`
- Modify: `agent-harness/cli_anything/cad/tests/test_core.py`

**Step 1: Write the formal TEST.md plan before more tests**

Update `TEST.md` with:

- Test inventory plan
- Unit test plan by module
- End-to-end plan with Path A and Path B
- Realistic workflows

Use this section structure:

```markdown
## Test Inventory Plan
- test_core.py: 12 unit tests planned
- test_full_e2e.py: 6 E2E tests planned

## Unit Test Plan
- project.py
- session.py
- files.py
- pipeline.py
- tasks.py
```

**Step 2: Add missing unit tests**

Add tests for:

- invalid input file extensions
- saving and loading project files
- task deletion for missing task IDs
- JSON output formatting shape for success and failure

**Step 3: Run the full unit suite**

Run: `python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -v`
Expected: PASS with all unit tests green.

**Step 4: Commit**

```bash
git add agent-harness/cli_anything/cad/tests/TEST.md agent-harness/cli_anything/cad/tests/test_core.py
git commit -m "test: add cad cli unit test plan and coverage"
```

### Task 6: Implement end-to-end and subprocess tests

**Files:**
- Create: `agent-harness/cli_anything/cad/tests/test_full_e2e.py`
- Modify: `agent-harness/cli_anything/cad/tests/TEST.md`
- Test data: use existing sample DXF/DWG files already present in the repo or add minimal dedicated fixtures under `agent-harness/cli_anything/cad/tests/fixtures/`

**Step 1: Write the failing Path A test**

Create:

```python
from pathlib import Path

from cli_anything.cad.core.pipeline import run_apply, run_extract


def test_dxf_extract_apply_roundtrip(tmp_path: Path):
    source = Path("241217-11+小样图.dxf")
    extract = run_extract(input_file=str(source), output_dir=str(tmp_path))
    assert Path(extract["excel_file"]).exists()
```

**Step 2: Write the failing subprocess smoke test**

Add:

```python
class TestCLISubprocess:
    CLI_BASE = _resolve_cli("cli-anything-cad")

    def _run(self, args, check=True):
        return subprocess.run(self.CLI_BASE + args, capture_output=True, text=True, check=check)

    def test_help(self):
        result = self._run(["--help"])
        assert result.returncode == 0
```

**Step 3: Run the E2E file to verify failure**

Run: `python -m pytest agent-harness/cli_anything/cad/tests/test_full_e2e.py -v -s`
Expected: FAIL until the E2E helpers and fixtures are wired.

**Step 4: Implement Path A and Path B tests**

Cover:

- Path A: `DXF -> extract -> apply`
- Path B: `DWG -> convert -> extract -> apply`
- installed CLI `--help`
- installed CLI `project new --json`
- installed CLI `pipeline extract`

Validation rules:

- generated Excel exists
- generated translated DXF exists
- file sizes are non-zero
- task IDs and artifact paths are returned

Use `_resolve_cli` exactly as required by HARNESS:

```python
def _resolve_cli(name):
    import os
    import shutil
    import sys

    force = os.environ.get("CLI_ANYTHING_FORCE_INSTALLED", "").strip() == "1"
    path = shutil.which(name)
    if path:
        return [path]
    if force:
        raise RuntimeError(f"{name} not found in PATH. Install with: pip install -e .")
    return [sys.executable, "-m", "cli_anything.cad"]
```

**Step 5: Run the E2E suite**

Run: `python -m pytest agent-harness/cli_anything/cad/tests/test_full_e2e.py -v -s`
Expected: PASS for Path A. Path B should PASS on machines with a working converter backend and should otherwise fail clearly with a dependency message.

**Step 6: Commit**

```bash
git add agent-harness/cli_anything/cad/tests/test_full_e2e.py agent-harness/cli_anything/cad/tests/TEST.md
git commit -m "test: add cad cli e2e and subprocess coverage"
```

### Task 7: Verify installation, document results, and finish packaging

**Files:**
- Modify: `agent-harness/cli_anything/cad/README.md`
- Modify: `agent-harness/CAD.md`
- Modify: `agent-harness/cli_anything/cad/tests/TEST.md`

**Step 1: Install the package in editable mode**

Run: `cd agent-harness && pip install -e .`
Expected: `cli-anything-cad` becomes available in the environment.

**Step 2: Verify the installed command is on PATH**

Run: `where.exe cli-anything-cad`
Expected: a valid executable path or script shim is shown.

**Step 3: Run the installed CLI manually**

Run:

```bash
cli-anything-cad --help
cli-anything-cad --json project new --name demo
```

Expected: help text and valid JSON output.

**Step 4: Run the full required test command**

Run: `set CLI_ANYTHING_FORCE_INSTALLED=1 && python -m pytest agent-harness/cli_anything/cad/tests -v -s --tb=no`
Expected: the subprocess tests resolve the installed command and the test output prints artifact locations.

**Step 5: Append results to TEST.md**

Append:

- full pytest output
- total tests
- pass rate
- execution time
- coverage notes and known gaps

**Step 6: Final documentation sweep**

Ensure `README.md` and `CAD.md` clearly explain:

- local backend dependency
- when a real DWG converter backend is required
- how Path A and Path B differ
- how to run REPL and one-shot commands
- how to run tests

**Step 7: Commit**

```bash
git add agent-harness/cli_anything/cad/README.md agent-harness/CAD.md agent-harness/cli_anything/cad/tests/TEST.md
git commit -m "docs: finalize cad cli packaging and verification"
```

## Notes for Execution

- Prefer implementing Path A first because it is the stable baseline.
- Do not call backend HTTP endpoints. Import and call local backend Python modules through `backend_bridge.py`.
- Keep project state lightweight. Do not duplicate backend task metadata beyond what the CLI needs for convenience.
- When a converter backend is missing, fail with a `dependency_error` payload instead of silently degrading.
- Do not add a database or extra persistent store for the CLI.
