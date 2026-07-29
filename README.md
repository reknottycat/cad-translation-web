# CAD Translation System

<p align="center">
  <b>LLM-powered batch translation for CAD engineering drawings</b><br>
  DWG/DXF Conversion · Text Extraction · AI Translation · Smart Write-back
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Node.js-18%2B-green" alt="Node.js 18+">
  <img src="https://img.shields.io/badge/FastAPI-0.110%2B-teal" alt="FastAPI">
  <img src="https://img.shields.io/badge/React-18-blueviolet" alt="React 18">
  <img src="https://img.shields.io/badge/Platform-Windows-primary" alt="Windows">
</p>

<p align="center">
  <b>English</b> | <a href="README.zh-CN.md">中文</a>
</p>

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Features](#-features)
- [Quick Start](#-quick-start)
- [Installation](#-installation)
- [Usage](#-usage)
- [Project Structure](#-project-structure)
- [Tech Stack](#-tech-stack)
- [AI Skill](#-ai-skill)
- [Documentation](#-documentation)
- [Build & Release](#-build--release)
- [Security](#-security)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🎯 Overview

**CAD Translation System** is an end-to-end intelligent translation system for engineering drawings. It automatically extracts text from **DWG/DXF** CAD files, batch-translates them using LLMs, and writes translations back into the drawings — dramatically reducing the time needed to produce multilingual engineering drawings.

The system supports **10+ major LLM vendors** (OpenAI, DeepSeek, Alibaba Qwen, Kimi, OpenRouter, etc.) with built-in glossary support, translation caching, checkpoint/resume, and other production-grade features. Suitable for individual engineers and translation teams.

### Three Runtime Surfaces

| Surface | Best For | Launch |
|---------|----------|--------|
| **Web App** (recommended) | GUI-driven workflow for non-technical users | `npm run dev` + `python run_server.py` |
| **CLI Tool** | Batch processing and automation pipelines | `cli-anything-cad` |
| **Desktop GUI** (legacy) | Standalone EXE with no dependency installation | `trans_CAD_gui_V1.0/gui.py` |

---

## ✨ Features

### 1. CAD File Processing
- **Multi-format support**: DWG, DXF, XLSX, CSV input/output
- **Smart conversion**: DWG → DXF auto-conversion via ACadSharp / ODA / COM backends
- **Text extraction**: Precise MTEXT/TEXT extraction powered by `ezdxf`

### 2. AI Batch Translation
- **Multi-vendor engine**: 10+ built-in provider presets, custom OpenAI-compatible endpoints
- **Glossary support**: CSV/XLSX glossary pre-replacement before translation
- **Translation cache**: Identical texts are not re-translated, reducing costs
- **Smart filtering**: Auto-skip pure numbers, symbols, and non-translatable content
- **Reasoning tag stripping**: Auto-remove `<think>` reasoning blocks from model output

### 3. Translation Write-back Modes
- **Replace original**: Overwrite original text directly
- **Append below**: Create new translation entity below the original
- **Newline after original**: Append translation inside original entity (MTEXT uses `\\P`, TEXT uses `\\n`)

### 4. Production Features
- **Checkpoint & resume**: Resume failed entries after interruption
- **Partial completion**: Mark `partial` status on failure, one-click continue
- **Real-time logs**: Live process log panel in the Web UI
- **Model memory**: Remember custom model IDs per provider

---

## 🚀 Quick Start

### Option 1: Runtime Bundle (End Users)

Download `scale_release.zip`, extract, and double-click `start_delivery.bat`:

```bat
start_delivery.bat
```

Browser will automatically open `http://127.0.0.1:8000/`.

### Option 2: Source Development

```bash
# 1. Clone repository
git clone <repo-url>
cd "cad code"

# 2. One-click install all dependencies (backend + frontend + CLI)
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
cd agent-harness && pip install -e . && cd ..

# 3. Start backend (terminal 1)
cd backend && python run_server.py

# 4. Start frontend (terminal 2)
cd frontend && npm run dev
```

Visit `http://localhost:3000`。

---

## 📦 Installation

### Requirements

| Component | Minimum | Notes |
|-----------|---------|-------|
| Python | 3.10 | Required for backend runtime |
| Node.js | 18 | Required for frontend dev/build |
| Windows | 10/11 | Primary platform (COM dependency) |
| AutoCAD / GStarCAD | Any | Optional for DWG→DXF COM conversion |

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env          # Edit as needed
```

### Frontend

```bash
cd frontend
npm install
```

### CLI

```bash
cd agent-harness
pip install -e .
cli-anything-cad --help
```

### One-Click Install All

```bash
# Run from project root
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
cd agent-harness && pip install -e . && cd ..
```

---

## 📖 Usage

### Web App

1. Open browser and visit the frontend URL
2. In the "Translation Config" panel, select LLM provider, model, and target language
3. Drag and drop `.dwg` or `.dxf` files to upload
4. The system auto-runs: Extract → Translate → Apply
5. Download the translated drawing

### CLI

```bash
# Show current config
cli-anything-cad config show

# Extract CAD text
cli-anything-cad pipeline extract -i sample.dwg -o ./output

# Apply translations
cli-anything-cad pipeline apply -i sample.dwg -e ./output/sample_extracted_texts.xlsx -o ./output

# Full pipeline
cli-anything-cad pipeline full -i sample.dwg -o ./output --target-lang en
```

See [`agent-harness/cli_anything/cad/README.md`](agent-harness/cli_anything/cad/README.md) for detailed CLI docs.

---

## 🏗️ Project Structure

```
cad-code/
├── backend/                    # FastAPI backend (single source of truth)
│   ├── app/
│   │   ├── main.py             # FastAPI entry point
│   │   ├── config.py           # Pydantic settings
│   │   ├── routers/            # API routers
│   │   ├── services/           # Business logic
│   │   │   ├── llm/translation_service.py      # Unified LLM engine
│   │   │   └── cad_pipeline_service.py         # Full CAD pipeline orchestrator
│   │   ├── functions/          # Low-level CAD operations
│   │   └── schemas/            # Pydantic models
│   ├── requirements.txt
│   └── run_server.py
│
├── frontend/                   # React frontend
│   ├── src/pages/TranslationWorkbenchPage.tsx   # Main workbench UI
│   └── services/api.ts         # Axios wrapper
│
├── agent-harness/              # Installable CLI package
│   └── cli_anything/cad/       # CLI source code
│
├── .agents/skills/             # Project-level AI Skills
│   └── cad-translation-dev/    # Development assistant Skill
│
├── docs/modern/                # Modern documentation
│   ├── ARCHITECTURE.md         # System architecture
│   ├── BACKEND_API_SPEC.md     # Backend API specification (OpenAPI)
│   ├── LLM_PROVIDERS.md        # Multi-vendor configuration
│   └── RELEASE_SCALE.md        # Build & release guide
│
├── scripts/                    # Build scripts
│   └── build_scale.ps1         # Main build script
│
├── scale_release/              # Runtime delivery bundle (build artifact)
└── tools/libredwg/             # Bundled LibreDWG binaries
```

> ⚠️ **Note**: `scale_release/` is a build artifact. Never edit it directly. After modifying `backend/` or `frontend/`, run `scripts/build_scale.ps1` to regenerate.

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.10+, FastAPI, Celery, Redis, SQLAlchemy 2.0, Alembic, Pydantic v2 |
| Frontend | React 18, TypeScript, Vite 5, Tailwind CSS, TDesign React |
| CAD | ezdxf, pandas, openpyxl, pywin32 (Windows COM) |
| LLM | OpenAI-compatible SDK, 10+ vendor presets |
| CLI | click, prompt-toolkit, rich |
| Testing | pytest, pytest-asyncio, Playwright |
| Packaging | PowerShell, PyInstaller, Nuitka |

---

## 🤖 AI Skill

This project includes a built-in project-level AI Skill to assist with development, building, and security auditing.

### Auto-load (Recommended)

The Skill is located at `.agents/skills/cad-translation-dev/` and is automatically discovered by Kimi Code CLI. When using Kimi for any task related to this project, the Skill provides:

- **Code navigation**: Quickly locate backend/frontend key modules
- **Build & release**: Guide the `scale_release` packaging workflow
- **Security audit**: Automatically scan the release bundle for sensitive file leaks
- **API quick reference**: Backend routes and configuration quick lookup

### Manual Packaging & Distribution

To export the Skill as a standalone `.skill` file:

```powershell
cd .agents/skills
Compress-Archive -Path cad-translation-dev -DestinationPath cad-translation-dev.skill -Force
```

Install to another project:

```powershell
# Extract to the target project's .agents/skills/ directory
Expand-Archive -Path cad-translation-dev.skill -DestinationPath "target-project/.agents/skills/cad-translation-dev"
```

---

## 📚 Documentation

| Document | Content |
|----------|---------|
| [`docs/modern/ARCHITECTURE.md`](docs/modern/ARCHITECTURE.md) | System architecture and data flow |
| [`docs/modern/BACKEND_API_SPEC.md`](docs/modern/BACKEND_API_SPEC.md) | Backend API full specification (OpenAPI) |
| [`docs/modern/FRONTEND_API_SPEC.md`](docs/modern/FRONTEND_API_SPEC.md) | Frontend API specification |
| [`docs/modern/LLM_PROVIDERS.md`](docs/modern/LLM_PROVIDERS.md) | Supported LLM vendors and config templates |
| [`docs/modern/CAD_CONVERTER_BACKENDS.md`](docs/modern/CAD_CONVERTER_BACKENDS.md) | DWG converter backend comparison |
| [`docs/modern/RELEASE_SCALE.md`](docs/modern/RELEASE_SCALE.md) | Build and release workflow |
| [`docs/modern/PROJECT_NAVIGATION.md`](docs/modern/PROJECT_NAVIGATION.md) | Project directory navigation |
| [`AGENTS.md`](AGENTS.md) | AI agent development guide |

---

## 🔨 Build & Release

### Build Runtime Delivery Bundle

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_scale.ps1
```

Outputs:
- `scale_release/` — runtime directory
- `scale_release.zip` — compressed delivery package

### Build Standalone EXE

```powershell
# PyInstaller
powershell -ExecutionPolicy Bypass -File scripts/build_scale_exe.ps1

# Nuitka
powershell -ExecutionPolicy Bypass -File scripts/build_scale_exe_nuitka.ps1
```

### Security Audit

Run the security check before every release:

```powershell
. .agents/skills/cad-translation-dev/scripts/security-audit.ps1
```

---

## 🔒 Security

1. **Admin Guard is off by default**: To protect dangerous endpoints, set `ENABLE_ADMIN_GUARD=true` and `ADMIN_API_TOKEN` in `backend/.env`.
2. **API Key masking**: The build script automatically desensitizes `runtime_config.local.json`, but development `.env` files must still be kept secure.
3. **Path traversal protection**: Backend uses `resolve_within_directory` and `get_safe_filename` to prevent path traversal.
4. **No HTTPS in dev mode**: Development/local mode uses HTTP by default. For public deployment, configure TLS on a reverse proxy (Nginx/Caddy).

---

## 🤝 Contributing

1. Fork this repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit changes: `git commit -m "feat: add your feature"`
4. Push branch: `git push origin feature/your-feature`
5. Open a Pull Request

### Coding Standards

- **Module limit**: 800 lines max per file (hard rule)
- **Python**: PEP 8 + type annotations
- **Frontend**: PascalCase for components, camelCase for variables/functions
- **Docs**: Update relevant documentation after every change

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).

---

<p align="center">
  Made with ❤️ for CAD engineers worldwide.
</p>
