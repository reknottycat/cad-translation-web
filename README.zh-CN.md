# CAD Translation System — CAD 图纸智能翻译系统

<p align="center">
  <b>基于 LLM 的 CAD 图纸批量翻译解决方案</b><br>
  DWG/DXF 转换 · 文字提取 · AI 翻译 · 智能回填
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Node.js-18%2B-green" alt="Node.js 18+">
  <img src="https://img.shields.io/badge/FastAPI-0.110%2B-teal" alt="FastAPI">
  <img src="https://img.shields.io/badge/React-18-blueviolet" alt="React 18">
  <img src="https://img.shields.io/badge/Platform-Windows-primary" alt="Windows">
</p>

<p align="center">
  <a href="README.md">English</a> | <b>中文</b>
</p>

---

## 📋 目录

- [项目简介](#-项目简介)
- [核心功能](#-核心功能)
- [快速开始](#-快速开始)
- [安装指南](#-安装指南)
- [使用说明](#-使用说明)
- [项目结构](#-项目结构)
- [技术栈](#-技术栈)
- [AI Skill](#-ai-skill)
- [文档索引](#-文档索引)
- [构建与发布](#-构建与发布)
- [安全注意事项](#-安全注意事项)
- [贡献指南](#-贡献指南)
- [许可证](#-许可证)

---

## 🎯 项目简介

**CAD Translation System** 是一套面向工程图纸的端到端智能翻译系统。它能够将 **DWG/DXF** 格式 CAD 图纸中的文字内容自动提取、批量翻译，并以多种模式回填到图纸中，大幅缩短多语言工程图纸的制作周期。

系统支持 **10+ 主流 LLM 厂商**（OpenAI、DeepSeek、阿里通义、Kimi、OpenRouter 等），内置术语表、翻译缓存、断点续传等工程化特性，适合个人工程师和翻译团队使用。

### 三种使用形态

| 形态 | 定位 | 启动方式 |
|------|------|----------|
| **Web 应用**（推荐） | 图形化操作，适合非技术用户 | `npm run dev` + `python run_server.py` |
| **CLI 工具** | 命令行批处理，适合自动化流水线 | `cli-anything-cad` |
| **桌面 GUI**（遗留） | 独立 exe，无需安装依赖 | `trans_CAD_gui_V1.0/gui.py` |

---

## ✨ 核心功能

### 1. CAD 文件处理
- **多格式支持**：DWG、DXF、XLSX、CSV 输入输出
- **智能转换**：DWG → DXF 自动转换，支持 ACadSharp / ODA / COM 多后端
- **文字提取**：基于 `ezdxf` 精准提取 MTEXT/TEXT 实体

### 2. AI 批量翻译
- **多厂商引擎**：内置 10+ 厂商预设，支持自定义 OpenAI-compatible 端点
- **术语表**：支持 CSV/XLSX 术语表，翻译前自动替换
- **翻译缓存**：相同文本不重复请求，降低成本
- **智能过滤**：自动跳过纯数字、纯符号等无需翻译内容
- **思维链过滤**：自动剥离模型 `<think>` 推理标签

### 3. 翻译回填模式
- **替换原文**：直接替换原文字内容
- **追加到下方**：在原文字下方创建新的翻译实体
- **原文后换行**：在原文字内部追加翻译（MTEXT 用 `\\P`，TEXT 用 `\\n`）

### 4. 工程化特性
- **断点续传**：任务中断后可继续翻译失败条目
- **部分完成**：失败后标记 `partial` 状态，支持一键继续
- **实时日志**：Web 端实时查看翻译进程日志
- **模型记忆**：按厂商记住用户自定义的模型 ID

---

## 🚀 快速开始

### 方式一：交付包（最终用户）

下载 `scale_release.zip` 并解压，双击 `start_delivery.bat`：

```bat
start_delivery.bat
```

浏览器将自动打开 `http://127.0.0.1:8000/`。

### 方式二：源码开发

```bash
# 1. 克隆仓库
git clone <repo-url>
cd "cad code"

# 2. 一键安装全部依赖（后端 + 前端 + CLI）
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
cd agent-harness && pip install -e . && cd ..

# 3. 启动后端（终端 1）
cd backend && python run_server.py

# 4. 启动前端（终端 2）
cd frontend && npm run dev
```

访问 `http://localhost:3000`。

---

## 📦 安装指南

### 环境要求

| 组件 | 最低版本 | 说明 |
|------|----------|------|
| Python | 3.10 | 后端运行时必须 |
| Node.js | 18 | 前端开发/构建必须 |
| Windows | 10/11 | 主要支持平台（COM 依赖） |
| AutoCAD / 浩辰 CAD | 任意 | DWG→DXF COM 转换可选 |

### 后端安装

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env          # 按需编辑配置
```

### 前端安装

```bash
cd frontend
npm install
```

### CLI 安装

```bash
cd agent-harness
pip install -e .
cli-anything-cad --help
```

### 一键安装全部

```bash
# 从项目根目录执行
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
cd agent-harness && pip install -e . && cd ..
```

---

## 📖 使用说明

### Web 应用

1. 打开浏览器访问前端地址
2. 在「翻译配置」面板选择 LLM 厂商、模型、目标语言
3. 拖拽上传 `.dwg` 或 `.dxf` 文件
4. 系统自动执行：提取 → 翻译 → 回填
5. 下载翻译后的图纸

### CLI 工具

```bash
# 查看配置
cli-anything-cad config show

# 提取 CAD 文字
cli-anything-cad pipeline extract -i sample.dwg -o ./output

# 应用翻译
cli-anything-cad pipeline apply -i sample.dwg -e ./output/sample_extracted_texts.xlsx -o ./output

# 完整流水线
cli-anything-cad pipeline full -i sample.dwg -o ./output --target-lang en
```

详细 CLI 文档见 [`agent-harness/cli_anything/cad/README.md`](agent-harness/cli_anything/cad/README.md)。

---

## 🏗️ 项目结构

```
cad-code/
├── backend/                    # FastAPI 后端（唯一可信源）
│   ├── app/
│   │   ├── main.py             # FastAPI 入口
│   │   ├── config.py           # Pydantic 配置
│   │   ├── routers/            # API 路由
│   │   ├── services/           # 业务逻辑
│   │   │   ├── llm/translation_service.py      # 统一翻译引擎
│   │   │   └── cad_pipeline_service.py         # CAD 全流程编排
│   │   ├── functions/          # 底层 CAD 功能
│   │   └── schemas/            # Pydantic 模型
│   ├── requirements.txt
│   └── run_server.py
│
├── frontend/                   # React 前端
│   ├── src/pages/TranslationWorkbenchPage.tsx   # 主工作台
│   └── services/api.ts         # Axios 封装
│
├── agent-harness/              # 可安装 CLI 包
│   └── cli_anything/cad/       # CLI 源码
│
├── .agents/skills/             # 本项目 AI Skill
│   └── cad-translation-dev/    # 项目级开发助手 Skill
│
├── docs/modern/                # 现代化文档
│   ├── ARCHITECTURE.md         # 架构说明
│   ├── BACKEND_API_SPEC.md     # 后端 API 规范
│   ├── LLM_PROVIDERS.md        # 多厂商配置
│   └── RELEASE_SCALE.md        # 打包发布说明
│
├── scripts/                    # 构建脚本
│   └── build_scale.ps1         # 主构建脚本
│
├── scale_release/              # 运行时交付包（构建产物）
└── tools/libredwg/             # LibreDWG 二进制工具
```

> ⚠️ **注意**：`scale_release/` 是构建产物，不要直接修改其中的文件。修改 `backend/` 和 `frontend/` 后，运行 `scripts/build_scale.ps1` 重新生成。

---

## 🛠️ 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.10+, FastAPI, Celery, Redis, SQLAlchemy 2.0, Alembic, Pydantic v2 |
| 前端 | React 18, TypeScript, Vite 5, Tailwind CSS, TDesign React |
| CAD | ezdxf, pandas, openpyxl, pywin32 (Windows COM) |
| LLM | OpenAI-compatible SDK，支持 10+ 厂商 |
| CLI | click, prompt-toolkit, rich |
| 测试 | pytest, pytest-asyncio, Playwright |
| 打包 | PowerShell, PyInstaller, Nuitka |

---

## 🤖 AI Skill

本项目内置项目级 AI Skill，用于辅助开发、构建和安全审计。

### 自动加载（推荐）

Skill 位于 `.agents/skills/cad-translation-dev/`，由 Kimi Code CLI 自动识别加载。当使用 Kimi 处理本项目相关任务时，Skill 会自动提供以下能力：

- **代码定位**：快速定位后端/前端关键模块
- **构建发布**：指导 `scale_release` 打包流程
- **安全审计**：自动扫描发行版中的敏感文件泄露
- **API 速查**：后端路由和配置项快速参考

### 手动打包分发

如需将 Skill 导出为独立 `.skill` 文件：

```powershell
cd .agents/skills
Compress-Archive -Path cad-translation-dev -DestinationPath cad-translation-dev.skill -Force
```

安装到其他项目：

```powershell
# 解压到目标项目的 .agents/skills/ 目录
Expand-Archive -Path cad-translation-dev.skill -DestinationPath "目标项目/.agents/skills/cad-translation-dev"
```

---

## 📚 文档索引

| 文档 | 内容 |
|------|------|
| [`docs/modern/ARCHITECTURE.md`](docs/modern/ARCHITECTURE.md) | 系统架构与数据流 |
| [`docs/modern/BACKEND_API_SPEC.md`](docs/modern/BACKEND_API_SPEC.md) | 后端 API 完整规范（OpenAPI） |
| [`docs/modern/FRONTEND_API_SPEC.md`](docs/modern/FRONTEND_API_SPEC.md) | 前端接口规范 |
| [`docs/modern/LLM_PROVIDERS.md`](docs/modern/LLM_PROVIDERS.md) | 支持的 LLM 厂商与配置模板 |
| [`docs/modern/CAD_CONVERTER_BACKENDS.md`](docs/modern/CAD_CONVERTER_BACKENDS.md) | DWG 转换后端对比与配置 |
| [`docs/modern/RELEASE_SCALE.md`](docs/modern/RELEASE_SCALE.md) | 打包与发布流程 |
| [`docs/modern/PROJECT_NAVIGATION.md`](docs/modern/PROJECT_NAVIGATION.md) | 项目目录导航 |
| [`AGENTS.md`](AGENTS.md) | 面向 AI 助手的开发指南 |

---

## 🔨 构建与发布

### 构建运行时交付包

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_scale.ps1
```

产物：
- `scale_release/` — 运行时目录
- `scale_release.zip` — 压缩交付包

### 构建独立 EXE

```powershell
# PyInstaller
powershell -ExecutionPolicy Bypass -File scripts/build_scale_exe.ps1

# Nuitka
powershell -ExecutionPolicy Bypass -File scripts/build_scale_exe_nuitka.ps1
```

### 安全审计

发布前必须运行安全检查：

```powershell
. .agents/skills/cad-translation-dev/scripts/security-audit.ps1
```

---

## 🔒 安全注意事项

1. **Admin Guard 默认关闭**：如需保护危险端点，在 `backend/.env` 中设置 `ENABLE_ADMIN_GUARD=true` 和 `ADMIN_API_TOKEN`。
2. **API Key 脱敏**：打包脚本会自动对 `runtime_config.local.json` 脱敏，但开发环境的 `.env` 仍需妥善保管。
3. **文件路径安全**：后端使用 `resolve_within_directory` 和 `get_safe_filename` 防止路径遍历。
4. **无 HTTPS**：开发/本地模式默认使用 HTTP，公网部署请在前置代理上配置 TLS。

---

## 🤝 贡献指南

1. Fork 本仓库
2. 创建功能分支：`git checkout -b feature/your-feature`
3. 提交更改：`git commit -m "feat: add your feature"`
4. 推送分支：`git push origin feature/your-feature`
5. 创建 Pull Request

### 开发规范

- 单一模块不超过 **800 行**（硬性规则）
- Python 遵循 **PEP 8**，使用类型注解
- 前端组件使用 **PascalCase**，变量/函数使用 **camelCase**
- 每次修改后同步更新相关文档

---

## 📄 许可证

本项目采用 [MIT License](LICENSE)。

---

<p align="center">
  Made with ❤️ for CAD engineers worldwide.
</p>
