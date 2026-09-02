# cad-translate

Local CAD drawing translation CLI. It shares the trusted backend implementation
in `backend/app` (the single source of truth) instead of keeping a drifting
copy of the CAD pipeline.

## Install (development)

```bash
cd agent-harness
pip install -e .
```

## Requirements

- Python 3.10+
- DWG→DXF conversion requires one of: AutoCAD / GstarCAD / ZWCAD (COM), the ODA
  File Converter, or LibreDWG. DXF-only work needs none of these.
- Excel translation needs a configured LLM provider (see `cad-translate config llm init`).

## Usage

```bash
cad-translate --version
cad-translate --help
cad-translate doctor

# Configuration
cad-translate config show
cad-translate config set --target-language en
cad-translate config llm show
cad-translate config llm init --provider deepseek --base-url https://api.deepseek.com/v1 --model deepseek-chat --api-key SK-xxx

# Projects
cad-translate project new --name demo -o project.json
cad-translate project open project.json
cad-translate project info

# File inspection
cad-translate files list --path ./drawings

# Pipeline steps
cad-translate pipeline convert -i drawing.dwg
cad-translate pipeline extract -i drawing.dxf
cad-translate pipeline translate-excel -i texts.xlsx
cad-translate pipeline apply -i drawing.dxf -e texts_translated.xlsx

# Tasks
cad-translate tasks list
cad-translate tasks show <task_id>
cad-translate tasks delete <task_id>
cad-translate tasks clear

# JSON output
cad-translate --json tasks list
```

## Configuration & output locations

Runtime configuration and output paths follow the backend settings
(`backend/.env`): see `cad-translate doctor`. Task state is stored under the
configured output directory as `outputs/cad_tasks/`, with per-task lifecycle
locks in `outputs/cad_task_lifecycle/` — the same concurrency-safe layout used
by the Web backend.

## Single-user tool

`cad-translate` is a local, single-user tool. It never shares a global runtime
config across machines and never lets a project overwrite another project's
task state: each run resolves the same settings the backend would, and task
state is isolated per output root.
