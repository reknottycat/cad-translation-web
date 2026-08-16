# CAD Translation System - CAD 图纸智能翻译系统

<p align="center">
  <b>基于 LLM 的 CAD 图纸批量翻译解决方案</b><br>
  DWG/DXF 转换 - 文字提取 - AI 翻译 - 智能回填
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Node.js-18%2B-green" alt="Node.js 18+">
  <img src="https://img.shields.io/badge/FastAPI-0.110%2B-teal" alt="FastAPI">
  <img src="https://img.shields.io/badge/React-18-blueviolet" alt="React 18">
  <img src="https://img.shields.io/badge/Platform-Windows-primary" alt="Windows">
</p>

<p align="center">
  <a href="README.zh-CN.md">中文</a> | <b>English</b>
</p>

## 项目简介

**CAD Translation System** 是一套面向工程图纸的端到端智能翻译系统。它能够将 **DWG/DXF** 格式 CAD 图纸中的文字内容自动提取、批量翻译，并以多种模式回填到图纸中。

本仓库只包含 Web 应用：FastAPI 后端 + React 前端。

## 核心功能

- **多格式支持**：DWG、DXF、XLSX、CSV 输入输出
- **智能转换**：DWG 转 DXF，支持 ACadSharp / ODA / COM / LibreDWG 多后端
- **文字提取**：基于 `ezdxf` 精准提取 MTEXT/TEXT 实体
- **多厂商翻译**：内置 10+ LLM 厂商预设（OpenAI、DeepSeek、通义、Kimi、OpenRouter 等）
- **自定义端点**：支持 OpenAI-compatible 自定义接口
- **术语表**：支持 CSV/XLSX 术语表，翻译前自动替换
- **翻译缓存**：相同文本不重复请求，降低成本
- **智能过滤**：自动跳过纯数字、纯符号等无需翻译内容
- **思维链过滤**：自动剥离模型 `<think>` 推理标签
- **回填模式**：替换原文、追加到下方、原文后换行
- **工程化能力**：断点续传、部分完成状态、实时任务日志、模型记忆

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- Windows 10/11
- 可选：AutoCAD、浩辰 CAD 或中望 CAD（COM 转换）

### 后端

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
python run_server.py
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

访问 `http://localhost:3000`，Vite 会将 `/api` 代理到 `http://localhost:8000`。

### 交付包

本地生成运行时交付包：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_scale.ps1
```

产物为 `scale_release/` 和 `scale_release.zip`。该目录由构建脚本生成，不入库。

## 项目结构

```
cad-code/
|-- backend/                     # FastAPI 后端（唯一可信源）
|   |-- app/
|   |   |-- main.py              # 应用入口
|   |   |-- config.py            # Pydantic 配置
|   |   |-- routers/             # API 路由
|   |   |-- schemas/             # Pydantic 模型
|   |   |-- services/            # 业务逻辑
|   |   |   |-- llm/translation_service.py
|   |   |   `-- cad_pipeline_service.py
|   |   `-- functions/           # DWG 转换、文字提取、回填
|   |-- requirements.txt
|   `-- run_server.py
|-- frontend/                    # React 前端
|   |-- src/
|   |   |-- pages/TranslationWorkbenchPage.tsx
|   |   `-- services/api.ts
|   `-- package.json
|-- docs/modern/                 # 架构与 API 文档
|-- scripts/                     # PowerShell 构建脚本
|-- .agents/skills/              # 项目 AI Skill
|-- cad-translation-skill/       # Skill 文档
|-- AGENTS.md                    # AI 助手开发指南
|-- README.md
|-- README.zh-CN.md
`-- LICENSE
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.10+, FastAPI, Celery, Redis, SQLAlchemy 2.0, Alembic, Pydantic v2 |
| 前端 | React 18, TypeScript, Vite 5, Tailwind CSS, TDesign React |
| CAD | ezdxf, pandas, openpyxl, pywin32（Windows COM） |
| LLM | OpenAI-compatible SDK，支持 10+ 厂商预设 |
| 打包 | PowerShell, PyInstaller, Nuitka |

## AI Skill

仓库内置 `.agents/skills/cad-translation-dev/` 和 `cad-translation-skill/`，用于辅助开发、构建发布和安全审计。

运行安全审计：

```powershell
. .agents/skills/cad-translation-dev/scripts/security-audit.ps1
```

## 文档索引

| 文档 | 内容 |
|------|------|
| [ARCHITECTURE.md](docs/modern/ARCHITECTURE.md) | 系统架构与数据流 |
| [BACKEND_API_SPEC.md](docs/modern/BACKEND_API_SPEC.md) | 后端 API 规范 |
| [FRONTEND_API_SPEC.md](docs/modern/FRONTEND_API_SPEC.md) | 前端接口规范 |
| [LLM_PROVIDERS.md](docs/modern/LLM_PROVIDERS.md) | LLM 厂商与配置 |
| [CAD_CONVERTER_BACKENDS.md](docs/modern/CAD_CONVERTER_BACKENDS.md) | DWG 转换后端 |
| [RELEASE_SCALE.md](docs/modern/RELEASE_SCALE.md) | 打包发布流程 |
| [PROJECT_NAVIGATION.md](docs/modern/PROJECT_NAVIGATION.md) | 项目目录导航 |
| [AGENTS.md](AGENTS.md) | AI 助手开发指南 |

## 构建与发布

生成运行时交付包：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_scale.ps1
```

生成独立 EXE：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_scale_exe.ps1
powershell -ExecutionPolicy Bypass -File scripts/build_scale_exe_nuitka.ps1
```

## CNB 自动发布流程

仓库内置 `.cnb.yml` 流水线配置，在 CNB 平台上自动执行校验与发版，与本地打包互补：

| 触发时机 | 流水线 | 作用 |
|----------|--------|------|
| `main` 推送 | `ci-backend` / `ci-frontend` | 后端编译检查 + 测试（有测试文件时）、前端 lint + build |
| Pull Request | `pr-check-*` | 预合并代码同样做后端测试 + 前端 lint/build 校验 |
| 打 `v*` Tag | `release` | 构建前端、打包跨平台源码交付包、自动发布 Release |
| 打 `v*` Tag | `release-exe` | 在 Windows 自托管 Runner 上生成便携 EXE 交付包并挂到 Release 附件 |
| Web 手动触发 | `manual-pack` / `manual-release` / `manual-exe` | 页面点击按钮即可打包、发版或生成 EXE（`.cnb/web_trigger.yml`） |
| 其它分支推送 | `ci-backend-syntax` | 后端语法校验 |

> **说明**：
> - Windows 完整交付包（`scale_release/`）依赖 CAD 软件 COM 自动化，仅能由本地 `scripts/build_scale.ps1` 生成；CNB 负责自动化校验与版本化制品分发，两者互补。
> - 便携 EXE（`release-exe` / `manual-exe`）需要**已接入 Windows 自托管 Runner**（节点标签含 `windows`）。接入方法见 CNB 官方文档「云原生构建 → 构建节点」。未接入时该流水线不会运行，本地仍可用 `scripts/build_scale_exe.ps1` 生成 EXE。
> - EXE 打包依赖 `release_exe/launcher.py`（PyInstaller 入口）与 `release_exe/pyinstaller_manifest.py`（依赖清单），两者已随仓库提供。

使用方法：

- **日常开发**：推送代码 / 提交 PR 即可获得自动校验结果。
- **发版**：打一个形如 `v1.0.0` 的 Tag，流水线会自动构建、打包源码交付包并发布 Release；若已接入 Windows 节点，同时生成便携 EXE 并挂到 Release。
- **手动打包**：在 CNB 仓库页面「流水线 → Web 触发」点击按钮手动打包、发版或生成 EXE。

## 安全注意事项

1. Admin Guard 默认关闭。如需保护危险端点，在 `backend/.env` 中设置 `ENABLE_ADMIN_GUARD=true` 和 `ADMIN_API_TOKEN`。
2. 打包脚本会自动对运行时配置中的 API Key 脱敏，但开发环境的 `.env` 仍需妥善保管。
3. 后端使用 `resolve_within_directory` 和 `get_safe_filename` 防止路径遍历。
4. 本地开发默认使用 HTTP；公网部署应在反向代理上配置 TLS。

## 贡献指南

1. Fork 本仓库。
2. 创建功能分支。
3. 提交修改。
4. 推送分支并创建 Pull Request。

开发规范：

- 单一模块不超过 800 行。
- Python 遵循 PEP 8，并使用类型注解。
- 前端组件使用 PascalCase，变量和函数使用 camelCase。
- 修改功能、接口或构建方式后同步更新相关文档。

## 许可证

本项目采用 [MIT License](LICENSE)。