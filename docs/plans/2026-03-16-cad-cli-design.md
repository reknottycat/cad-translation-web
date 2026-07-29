# CAD CLI-Anything Harness Design

**Date:** 2026-03-16

**Goal**

Build a complete 7-phase `CLI-Anything` harness for the CAD backend as an independently installable package named `cli-anything-cad`, while reusing the existing local backend Python engine instead of calling HTTP APIs.

**Design Summary**

The CLI will follow the `CLI-Anything` harness structure under `agent-harness/`, including package metadata, REPL support, JSON output, test documentation, unit tests, end-to-end tests, and install verification. The business layer will not reimplement CAD processing. Instead, it will adapt the existing backend engine in `backend/app/functions`, `backend/app/services`, and `backend/app/workflow` into CLI-friendly core modules.

This design uses a "full-harness + backend-core" approach:

- Full harness on the outside: package structure, commands, REPL, tests, docs, install flow
- Existing backend as the inside engine: DWG conversion, DXF extraction, translation map generation, and translation apply

## Why This Approach

Three implementation directions were considered:

1. Thin CLI wrapper over backend modules
2. Fully new CAD project model and state engine inside the CLI
3. Full CLI-Anything harness with a thin adaptation layer over the backend engine

Option 3 is the chosen design because it satisfies the user's requirement for a full 7-phase CLI harness without forking the CAD processing logic into a second implementation.

## Source Analysis

The local source of truth for CAD processing already exists in the backend:

- `backend/app/functions/dwg_converter.py`
- `backend/app/functions/text_extractor.py`
- `backend/app/functions/text_applier.py`
- `backend/app/functions/translator.py`
- `backend/app/services/cad_pipeline_service.py`
- `backend/app/workflow/pipeline.py`

These modules already expose the core workflow:

1. Convert DWG to DXF
2. Extract DXF text to Excel
3. Build or load translation mappings
4. Apply translations back into DXF

The CLI harness should wrap these capabilities into a command-oriented and stateful interface suitable for agents and interactive use.

## CLI Package Layout

The generated package will live under `agent-harness/` and follow the `CLI-Anything` namespace package rules:

```text
agent-harness/
├── CAD.md
├── setup.py
└── cli_anything/
    └── cad/
        ├── __init__.py
        ├── __main__.py
        ├── README.md
        ├── cad_cli.py
        ├── core/
        │   ├── __init__.py
        │   ├── project.py
        │   ├── session.py
        │   ├── files.py
        │   ├── pipeline.py
        │   └── tasks.py
        ├── utils/
        │   ├── __init__.py
        │   ├── backend_bridge.py
        │   └── repl_skin.py
        └── tests/
            ├── TEST.md
            ├── test_core.py
            └── test_full_e2e.py
```

`cli_anything/` must remain a namespace package with no `__init__.py` at that level.

## Command Structure

The CLI will support both one-shot commands and a default REPL. Invoking `cli-anything-cad` with no subcommand enters REPL mode.

Primary command groups:

- `project`
- `files`
- `pipeline`
- `tasks`
- `config`
- `repl`

### `project`

Purpose: manage lightweight CLI project files.

Planned commands:

- `project new`
- `project open`
- `project save`
- `project info`

### `files`

Purpose: inspect and bind local CAD-related files for the current session or project.

Planned commands:

- `files list`
- `files add`
- `files set-input`

### `pipeline`

Purpose: run actual CAD processing.

Planned commands:

- `pipeline inspect`
- `pipeline convert`
- `pipeline extract`
- `pipeline translate-excel`
- `pipeline apply`
- `pipeline run`

### `tasks`

Purpose: inspect and manage generated task artifacts backed by `task.json` and task directories.

Planned commands:

- `tasks list`
- `tasks show`
- `tasks delete`
- `tasks clear`

### `config`

Purpose: inspect or set CLI defaults.

Planned commands:

- `config show`
- `config set`

### `repl`

Purpose: interactive agent-friendly command execution with persistent session state.

## State Model

The design intentionally separates two types of state.

### Project State

Stored in a lightweight project JSON managed by the CLI.

Responsibilities:

- remember current source files
- remember default output directory
- remember default target language
- remember default converter backend
- remember font settings
- remember recent task IDs and recent output references

Example shape:

```json
{
  "name": "demo",
  "status": "idle",
  "source_files": ["samples/a.dwg"],
  "default_output_dir": "backend/outputs/cad_tasks",
  "target_language": "en",
  "converter_backend": "acadsharp",
  "font_name": "Times New Roman",
  "font_size_reduction": 2,
  "recent_task_id": "abcd1234",
  "recent_excel_file": "backend/outputs/cad_tasks/abcd1234/a_extracted_texts.xlsx"
}
```

### Task State

Stored in backend-generated task directories and `task.json`.

Responsibilities:

- track real processing artifacts
- track normalized DXF filename
- track text counts and translation counts
- track actual generated Excel and translated CAD outputs
- remain the source of truth for workflow results

This avoids duplicating backend task logic inside the CLI.

## Core Module Responsibilities

### `core/project.py`

- create, load, validate, save project JSON
- update project metadata after pipeline runs
- provide project summaries for CLI and REPL

### `core/session.py`

- hold in-memory REPL state
- track current project path and dirty state
- track current input file, active translations, and recent task
- expose session status for REPL prompts and `project info`

### `core/files.py`

- scan directories for `.dwg`, `.dxf`, `.xlsx`
- validate input files
- normalize path handling
- support selecting active input files

### `core/pipeline.py`

- convert CLI arguments into backend-friendly execution context
- call the backend bridge for convert, extract, translate, apply, and run
- return normalized result payloads suitable for text or JSON output

### `core/tasks.py`

- discover task directories
- read and summarize `task.json`
- delete individual tasks
- clear all tasks

### `utils/backend_bridge.py`

- make backend modules importable from the CLI package
- initialize and reuse backend services safely
- expose stable wrapper functions for:
  - DWG conversion
  - DXF extraction
  - translation map loading/building
  - translation apply
  - full pipeline run

### `utils/repl_skin.py`

- copied from the `CLI-Anything` plugin as required by the harness
- used for the branded REPL, prompt history, and structured terminal output

## Data Flow

### Path A: Stable DXF Flow

This is the required end-to-end test baseline because it has the fewest external dependencies.

1. User selects an input `.dxf`
2. `pipeline extract` calls the backend extractor
3. Excel is generated
4. Translation mapping is loaded from Excel or edited input
5. `pipeline apply` generates a translated DXF
6. CLI updates project references and recent task metadata

### Path B: Full DWG Flow

This is the complete real-world workflow.

1. User selects an input `.dwg`
2. `pipeline convert` calls the configured converter backend
3. A normalized DXF is generated
4. `pipeline extract` creates Excel
5. Translation map is prepared
6. `pipeline apply` writes translated DXF
7. CLI updates task and project references

Path B depends on a real converter backend being available. Path A does not.

## Dependency Model

The CLI is independent as a Python package, but not independent from the local CAD engine.

Required runtime dependencies include:

- Python dependencies declared in `setup.py`
- backend source tree present in the local workspace
- converter backend when DWG conversion is requested

Important distinction:

- DXF extract/apply must work with only Python dependencies
- DWG conversion must clearly fail with actionable instructions when the converter backend is unavailable

## Output Model

Every command should support:

- human-readable output by default
- machine-readable output with `--json`

Normalized JSON error shape:

```json
{
  "success": false,
  "error_type": "dependency_error",
  "message": "ODA converter is not configured",
  "details": {}
}
```

Normalized success responses should include enough fields for agent use:

- input path
- output path
- task ID where applicable
- generated artifact paths
- counts such as extracted texts or translated entities

## Error Handling

Errors should be grouped into four categories:

- `usage_error`
- `dependency_error`
- `processing_error`
- `artifact_error`

Examples:

- missing input path: `usage_error`
- missing converter backend: `dependency_error`
- DXF parse failure: `processing_error`
- missing generated Excel file after success path: `artifact_error`

This categorization keeps human output readable and JSON output stable for agents.

## Testing Strategy

The harness must include all required testing artifacts from `CLI-Anything`.

### Unit Tests

File: `agent-harness/cli_anything/cad/tests/test_core.py`

Covers:

- project file creation and persistence
- session state handling
- file scanning and input validation
- task discovery and deletion logic
- pipeline argument normalization
- JSON result formatting helpers

These tests use synthetic inputs and should not require converter software.

### End-to-End Tests

File: `agent-harness/cli_anything/cad/tests/test_full_e2e.py`

Two required paths:

- Path A: `DXF -> extract -> apply`
- Path B: `DWG -> convert -> extract -> apply`

Path A is the mandatory stable path and should be considered the required baseline.

Path B is required for full harness coverage but should be documented as depending on an installed converter backend.

### CLI Subprocess Tests

The test suite must use `_resolve_cli("cli-anything-cad")` and run the installed CLI command through subprocess, covering:

- `--help`
- `--json`
- `project new`
- `pipeline extract`
- `pipeline apply`
- at least one full workflow

### Test Documentation

`TEST.md` must contain:

- pre-implementation test plan
- planned unit and E2E coverage
- realistic workflows
- final test execution results appended after test runs

## REPL Design

The REPL is required and should be the default behavior when the CLI is run without a subcommand.

The REPL should support:

- banner and prompt via `ReplSkin`
- `help`
- `status`
- project load/create workflow
- current file inspection
- running pipeline steps interactively
- safe error reporting without terminating the REPL

The REPL is a productivity surface, not a second execution engine. It should call the same core modules as one-shot commands.

## Documentation Deliverables

The full harness should produce:

- `CAD.md` for CAD-specific SOP and backend mapping
- package `README.md` for install and usage
- `TEST.md` for test plan and results

The README must clearly explain:

- software dependencies
- package installation
- how to run the REPL
- how to run one-shot commands
- how to run the tests

## Out of Scope

The first implementation should not:

- introduce a second independent CAD processing engine
- call backend HTTP APIs
- implement undo/redo over CAD document mutations
- support unsupported translation providers beyond what backend already exposes
- invent a new persistent database for CLI state

## Success Criteria

The design is considered successful when the implementation produces:

1. a valid `cli-anything-cad` package under the `cli_anything.cad` namespace
2. a default REPL mode with `ReplSkin`
3. `--json` support across commands
4. a stable Path A end-to-end test using DXF input
5. a full Path B end-to-end test using a real DWG converter backend
6. subprocess tests targeting the installed CLI binary
7. installation and usage documentation
8. `TEST.md` with both plan and results
