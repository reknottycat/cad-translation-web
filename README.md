# CAD Translation System

A web-based CAD drawing translation system. It extracts text from DWG/DXF drawings, translates it in batches with LLM providers, and writes the translated text back into the drawings.

This repository contains the Web application: FastAPI backend + React frontend.

## Features

- DWG/DXF conversion with multiple backends (ACadSharp, ODA, COM, LibreDWG)
- Precise MTEXT/TEXT extraction with ezdxf
- Batch translation through 10+ LLM providers (OpenAI, DeepSeek, Qwen, Kimi, OpenRouter, and more)
- Custom OpenAI-compatible endpoints
- CSV/XLSX glossary auto-replacement
- Legacy .xls glossary support (xlrd)
- Translation cache, smart filtering, and think-tag stripping
- Rate limiting (RPM/TPM), custom request body (extra_body), proxy control, and configurable retries
- Replace, append, and line-break backfill modes
- Resume failed items, partial completion state, real-time task logs
- Provider-aware model memory

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- Windows 10/11
- Optional: AutoCAD, GstarCAD, or ZWCAD for COM conversion

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
python run_server.py
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. The Vite dev server proxies `/api` to `http://localhost:8000`.

### Delivery Bundle

Build a runtime bundle locally:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_scale.ps1
```

Output: `scale_release/` and `scale_release.zip`. The folder is generated locally and is not tracked in this repository.

## Project Structure

```
cad-code/
|-- backend/                     # FastAPI backend (source of truth)
|   |-- app/
|   |   |-- main.py              # Application entry
|   |   |-- config.py            # Pydantic settings
|   |   |-- routers/             # API routes
|   |   |-- schemas/             # Pydantic models
|   |   |-- services/            # Business logic
|   |   |   |-- llm/translation_service.py
|   |   |   `-- cad_pipeline_service.py
|   |   `-- functions/           # DWG conversion, extraction, backfill
|   |-- requirements.txt
|   `-- run_server.py
|-- frontend/                    # React frontend
|   |-- src/
|   |   |-- pages/TranslationWorkbenchPage.tsx
|   |   `-- services/api.ts
|   `-- package.json
|-- docs/modern/                 # Architecture and API documentation
|-- scripts/                     # PowerShell build scripts
|-- .agents/skills/              # Project AI skill
|-- cad-translation-skill/       # Skill documentation
|-- AGENTS.md                    # AI assistant guide
|-- README.md
|-- README.zh-CN.md
`-- LICENSE
```

## Technology Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.10+, FastAPI, Celery, Redis, SQLAlchemy 2.0, Alembic, Pydantic v2 |
| Frontend | React 18, TypeScript, Vite 5, Tailwind CSS, TDesign React |
| CAD | ezdxf, pandas, openpyxl, xlrd, pywin32 (Windows COM) |
| LLM | OpenAI-compatible SDK with 10+ provider presets |
| Packaging | PowerShell, PyInstaller, Nuitka |

## AI Skill

The repository includes `.agents/skills/cad-translation-dev/` and `cad-translation-skill/` to assist with development, build/release guidance, and security review.

Run the security audit with:

```powershell
. .agents/skills/cad-translation-dev/scripts/security-audit.ps1
```

## Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](docs/modern/ARCHITECTURE.md) | System architecture and data flow |
| [BACKEND_API_SPEC.md](docs/modern/BACKEND_API_SPEC.md) | Backend API specification |
| [FRONTEND_API_SPEC.md](docs/modern/FRONTEND_API_SPEC.md) | Frontend API integration guide |
| [LLM_PROVIDERS.md](docs/modern/LLM_PROVIDERS.md) | Supported LLM providers and configuration |
| [CAD_CONVERTER_BACKENDS.md](docs/modern/CAD_CONVERTER_BACKENDS.md) | DWG conversion backends |
| [RELEASE_SCALE.md](docs/modern/RELEASE_SCALE.md) | Packaging and release flow |
| [PROJECT_NAVIGATION.md](docs/modern/PROJECT_NAVIGATION.md) | Project directory navigation |
| [AGENTS.md](AGENTS.md) | Development guide for AI assistants |

## Build & Release

Build the runtime delivery bundle:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_scale.ps1
```

Build standalone EXE variants:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_scale_exe.ps1
powershell -ExecutionPolicy Bypass -File scripts/build_scale_exe_nuitka.ps1
```

## Security Notes

1. Admin guard is **on by default and fail-closed**. When `ENABLE_ADMIN_GUARD=true`, sensitive task/project/file/config/translation endpoints require `ADMIN_API_TOKEN` (via `X-Admin-Token` or `Authorization: Bearer`). If the token is **not** configured while the guard is enabled, all guarded routes return `503 Service Unavailable` rather than silently opening access. Only set `ENABLE_ADMIN_GUARD=false` explicitly to run in trusted-network open mode.
2. Packaging scripts sanitize API keys from runtime configuration, but development `.env` files must still be kept private.
3. Backend file handling uses `resolve_within_directory` and `get_safe_filename` to prevent path traversal.
4. Local development uses HTTP. For public deployment, terminate TLS at a reverse proxy.

## Contributing

1. Fork this repository.
2. Create a feature branch.
3. Commit changes.
4. Push the branch and open a pull request.

Development conventions:

- Keep single modules under 800 lines.
- Python code follows PEP 8 with type annotations.
- Frontend components use PascalCase; variables and functions use camelCase.
- Update related documentation when behavior, APIs, or build steps change.

## License

This project is licensed under the [MIT License](LICENSE).

## Multi-User Concurrency Notes

The system is designed to support multiple users processing CAD tasks concurrently on an internal Windows deployment. Key behaviors:

- **Task isolation**: Each CAD task gets a unique UUID-based task ID and an isolated directory under `outputs/cad_tasks/{task_id}/`. Source files, Excel extractions, translated CAD files, and logs never mix across tasks.
- **Cross-process file locking**: Task metadata (`task.json`), translation checkpoints, and runtime config files are protected by atomic writes (temp + rename) plus **cross-process file locks** using a stable sidecar `.lock` file. The lock is acquired on `<target>.lock`, which is never renamed or replaced, so the lock identity is stable even when the target file is atomically replaced inside the critical section. This works on both POSIX (`fcntl.flock`) and Windows (`msvcrt.locking`).
- **SQLite concurrency**: A 30-second busy timeout is set so concurrent readers/writers wait instead of failing with "database is locked".
- **Config file safety**: Concurrent saves to the runtime config JSON are serialized through the same file-lock mechanism, preventing corruption or lost updates.
- **Excel output uniqueness**: The `/api/translation/excel` endpoint generates UUID-prefixed output filenames, preventing same-name uploads from overwriting each other's results.
- **COM converter serialization**: DWG-to-DXF conversions via COM are limited to one at a time per process (`CAD_COM_CONCURRENCY` env var, default 1) to avoid COM instance races.
- **LLM rate limiting**: RPM/TPM buckets are per-process. When deploying multiple workers, each process maintains its own rate-limit state; consider allocating limits accordingly.

### Security & Authorization Model

**Single-tenant model**: This system is a single-tenant web application for internal deployment. It has **no per-user accounts** and does **not** attempt to provide per-user data isolation between different individuals on the same instance. All projects/tasks/files on one instance belong to the same logical tenant.

- **`ENABLE_ADMIN_GUARD` is ON by default and fail-closed.** Set `ADMIN_API_TOKEN` in `backend/.env` to require a token for every sensitive task/project/file/config/translation endpoint. Callers authenticate with `X-Admin-Token: <token>` or `Authorization: Bearer <token>`.
- **Fail-closed behavior**: If `ENABLE_ADMIN_GUARD=true` but `ADMIN_API_TOKEN` is left empty, every guarded endpoint returns `503 Service Unavailable`. This prevents accidental open access when protection is intended but not properly configured. There is **no silent fail-open path**.
- Only explicitly set `ENABLE_ADMIN_GUARD=false` to run all endpoints open (trusted-network single-user deployment). This is not recommended for shared environments.
- A `task_id` / `project_id` / `file_id` alone is **not** an access credential — it only identifies a resource once the caller has passed the admin guard.
- Cross-tenant isolation would require adding a user authentication system (login, session/JWT, per-user ownership columns on projects/tasks/files, per-user data-scoped queries), which is **out of scope** for this codebase. To serve multiple independent tenants from one host, deploy one instance per tenant or place a reverse proxy / SSO in front of separate deployments.

### Global Runtime Configuration

The LLM/CAD runtime configuration (stored in `~/.config/cli-anything-cad/config.json`) is deliberately designed as **server-global configuration** shared by all users and tasks.

- Each task **captures a sanitized config snapshot** in its `task.json` at creation/resume time. The **actual LLM translation calls** (`translate_batch` / `translate_text` / `_chat`) use the snapshot's frozen `llm` config section through a thread-local context manager, so an admin changing the global config mid-flight cannot alter a running task's provider/model/parameters. Live API keys are still resolved at call time from env/config (the snapshot has them redacted for safety).
- Concurrent updates to the runtime config are protected by the same file-lock mechanism, so writes are serialized and JSON is never corrupted.
- Config writes are guarded by `require_admin_access` (admin token). Non-admin users cannot change the global config.
- To serve per-user or per-project configuration, extend the workflow engine to snapshot the effective config into each task's context at start.

### Known limitations in multi-process mode

- Cross-process file locks protect task metadata and config writes.
- **Per-task lifecycle + global creation/clear coordination locks**: each task
  has a stable lifecycle lock file in `outputs/cad_task_lifecycle/{task_id}.lifecycle`
  (a sibling of `cad_tasks/`, never removed by delete/clear so lock identity —
  the inode — stays constant across processes). Writers (`_save_task` /
  `_update_task` / `_append_log` / `_save_checkpoint`), the batch stopper
  (`stop_all_tasks`) and deleters (`delete_task` / `clear_all_tasks`) hold this
  per-task lock for their whole exists→lock→write/delete sequence, closing
  delete-vs-writer TOCTOU. **Lock order is unified everywhere as
  lifecycle-lock → task.json/task-file lock**: a writer or `stop_all_tasks`
  acquires the per-task lifecycle lock *first* and only then takes the
  task-file lock (nested via `_load_task`/`_save_task`/`_append_log`/
  `_save_checkpoint`). `delete_task` / `clear_all_tasks` likewise hold the
  lifecycle lock while reading or removing the task tree. This single ordering
  (never task-file lock → lifecycle lock) is what prevents the cross-process
  deadlock that would otherwise arise when two processes hold opposite locks
  (one holds the task-file lock and wants the lifecycle lock while the other
  holds the lifecycle lock and wants the task-file lock). A single
  **global** coordination lock
  (`outputs/cad_task_lifecycle/_task_create_or_clear.coord`) additionally
  serializes the *registration* critical region of `extract_upload`
  (mkdir → upload → convert/extract → first `task.json`) with the *whole*
  `clear_all_tasks` (cancel-marking + enumeration/deletion + marker cleanup), so
  a task created concurrently with a clear can neither escape the clear nor be
  deleted while it is being written. Normal per-task processing (translation)
  uses only per-task locks and is not serialized by the global lock.
- **Cross-process cancellation is file-based**: stop/cancel operations write a `.cancel` marker in a **stable external directory** (`outputs/cad_cancel_marks/`), never inside the task directory. Any worker process running a task checks the marker before/after each chunk and aborts cleanly. The marker is removed when the task reaches a terminal state. Because markers live outside task directories, `delete_task` / `clear_all_tasks` never race with a running worker's cleanup path to recreate the task directory.
- **Config snapshot per task**: each task stores a sanitized snapshot of the effective LLM/CAD runtime config in `task.json` at creation time. The actual LLM translation calls use the frozen `llm` section from this snapshot via a thread-local context manager (`LLMTranslationService.frozen_config`), so a mid-flight global config change cannot alter a task's actual provider/model/batch_size/parameters. API keys are resolved live at call time (not stored in the snapshot).
- LLM rate-limit buckets are per-process. Under multi-worker Celery, RPM/TPM quotas may be exceeded by the aggregate of all workers.
- `CADPipelineService` module exceeds the 800-line guideline; splitting into submodules is tracked as a follow-up task.
