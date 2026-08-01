# CAD Translation System

A web-based CAD drawing translation system. It extracts text from DWG/DXF drawings, translates it in batches with LLM providers, and writes the translated text back into the drawings.

This repository contains the Web application: FastAPI backend + React frontend.

## Features

- DWG/DXF conversion with multiple backends (ACadSharp, ODA, COM, LibreDWG)
- Precise MTEXT/TEXT extraction with ezdxf
- Batch translation through 10+ LLM providers (OpenAI, DeepSeek, Qwen, Kimi, OpenRouter, and more)
- Custom OpenAI-compatible endpoints
- CSV/XLSX glossary auto-replacement
- Translation cache, smart filtering, and think-tag stripping
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
| CAD | ezdxf, pandas, openpyxl, pywin32 (Windows COM) |
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

1. Admin guard is off by default. Enable `ENABLE_ADMIN_GUARD=true` and set `ADMIN_API_TOKEN` in `backend/.env` before exposing dangerous endpoints.
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