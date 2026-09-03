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

本仓库包含 Web 应用（FastAPI 后端 + React 前端）以及持续维护的
`cad-translate` CLI。

## 核心功能

- **多格式支持**：DWG、DXF、XLSX、CSV 输入输出
- **智能转换**：DWG 转 DXF，支持 ACadSharp / ODA / COM / LibreDWG 多后端
- **文字提取**：基于 `ezdxf` 精准提取 MTEXT/TEXT 实体
- **多厂商翻译**：内置 10+ LLM 厂商预设（OpenAI、DeepSeek、通义、Kimi、OpenRouter 等）
- **自定义端点**：支持 OpenAI-compatible 自定义接口
- **术语表**：支持 CSV/XLSX 术语表，翻译前自动替换
- **旧格式术语表**：支持 .xls 格式（通过 xlrd 解析）
- **翻译缓存**：相同文本不重复请求，降低成本
- **智能过滤**：自动跳过纯数字、纯符号等无需翻译内容
- **思维链过滤**：自动剥离模型 `<think>` 推理标签
- **速率与请求控制**：RPM/TPM 限速、自定义 extra_body、系统代理开关、可配置重试次数
- **回填模式**：替换原文、追加到下方、原文后换行
- **工程化能力**：断点续传、部分完成状态、实时任务日志、模型记忆

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- Windows 10/11
- 可选：AutoCAD、浩辰 CAD 或中望 CAD（COM 转换）

> **DWG 文件建议：** ODA File Converter 和 LibreDWG 可以作为备用转换后端，
> 但不建议作为复杂或生产 DWG 文件的首选。为了获得更好的兼容性，建议在
> 运行后端的 Windows 主机安装 AutoCAD、浩辰 CAD 或中望 CAD，并优先使用其
> COM 转换能力。转换完成后先检查 DXF，再进入翻译流程；仅处理 DXF 时不需要
> 安装 CAD 软件。

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

产物为 `scale_release/` 和 `scale_release.zip`。该目录由构建脚本生成，
不入库。交付包还内置 `cad-translate` CLI（位于包内 `cli/`，详见 `CLI.md`）。

### CLI

`cad-translate` CLI 是本仓库明确维护的组件（见 `agent-harness/`）。它是对 `backend/app` 可信实现的薄封装——与 Web 应用共享同一套代码，绝不携带容易漂移的重复 `lib/` 快照。

```powershell
cd agent-harness
pip install -e .
cad-translate --version
cad-translate --help
cad-translate doctor         # 环境自检
```

典型流程（仅处理 DXF 时无需 AutoCAD）：

```bash
cad-translate config set --target-language en
cad-translate project new --name demo -o project.json
cad-translate files list --path ./drawings
cad-translate pipeline extract -i drawing.dxf            # -> Excel
cad-translate pipeline translate-excel -i texts.xlsx     # 需配置 LLM
cad-translate pipeline apply -i drawing.dxf -e texts_translated.xlsx
cad-translate tasks list
```

任意命令加 `--json` 即可输出 JSON。配置与输出位置与后端保持一致；可用 `cad-translate doctor` 查看。

## 给 Agent 的安装与推荐使用方式

推荐直接让 WorkBuddy、Codex 或其他具备本地文件和终端权限的 Agent 帮你
安装、配置并执行翻译。这样 Agent 可以先检查当前 Windows 主机上的 CAD
转换能力，按实际生效配置运行流程，并返回准确的输出位置。

### 给 Agent 的安装命令

在 Windows 的全新目录中执行：

```powershell
git clone https://github.com/reknottycat/cad-translation-web.git
cd cad-translation-web
python -m pip install -r backend\requirements.txt
python -m pip install -e agent-harness
cad-translate --help
cad-translate doctor
```

如果 GitHub 无法访问或下载失败，改用 [CNB 镜像](https://cnb.cool/star_fu/cad-translation-web)：

```powershell
git clone https://cnb.cool/star_fu/cad-translation-web.git
```

如果使用已经生成的交付包，则在包内安装 CLI：

```powershell
cd cli
python -m pip install -e .
```

`cad-translate doctor` 用于查看运行时路径和配置状态，**不等于**实时
激活 AutoCAD。处理 DWG 时，转换后端必须安装或存在于运行后端的 Windows
主机上。复杂或生产图纸建议优先使用 AutoCAD、浩辰 CAD 或中望 CAD 的 COM
转换；ODA File Converter 和 LibreDWG 只作为备用，并应在使用前检查转换
结果。浏览器客户端不能替主机安装或探测 CAD 软件。

### 推荐直接发给 Agent 的提示词

下面的内容可以直接复制给 WorkBuddy、Codex 或其他具备本地文件操作权限
的 Agent，再把 `<文件完整路径>` 换成实际文件：

```text
请先在本机准备 CAD Translation System：
1. 优先从 GitHub 下载 https://github.com/reknottycat/cad-translation-web.git；
   如果 GitHub 访问或下载失败，改用 CNB 镜像
   https://cnb.cool/star_fu/cad-translation-web.git。
2. 安装项目依赖和 cad-translate CLI，检查 Python、项目配置以及本机可用
   的 AutoCAD / 浩辰 CAD / 中望 CAD / ODA / LibreDWG 转换后端。处理 DWG 时
   优先使用 AutoCAD、浩辰 CAD 或中望 CAD 的 COM 转换；ODA/LibreDWG 只作为
   没有厂商 CAD 时的备用，并在翻译前检查转换出的 DXF。不要修改或覆盖仓库
   中的源文件。
3. 先说明当前生效的配置、输入文件、输出目录和是否需要外部 LLM API Key。
   如果项目的 LLM 提供商需要 API Key，请提示我配置；不要把 Key 写入 Git
   仓库、日志或交付包。若你当前具备可直接调用的翻译能力且能安全读写本地
   文件，可以使用你的能力完成文本翻译，不必虚构或提交一个项目 API Key。
4. 帮我翻译“<文件完整路径>”，目标语言为俄文（Russian），翻译模式使用
   “替换文本”（replace）：用俄文替换原文，不要使用追加（add）模式。
   先保留原始文件，再把结果写入新的输出文件。
5. 运行完成后检查翻译条数、未翻译条目、输出文件路径和是否存在异常；如果
   DWG 转换或 API Key 不可用，请先停在可恢复的阶段并明确告诉我原因和下一步。
```

对应的 CLI 翻译与回填命令为：

```powershell
cad-translate pipeline translate-excel -i texts.xlsx --target-language ru --translation-mode replace
cad-translate pipeline apply -i drawing.dxf -e texts_translated.xlsx --translation-mode replace
```

如果输入是 `.dwg`，先执行转换和文字提取：

```powershell
cad-translate pipeline convert -i drawing.dwg
cad-translate pipeline extract -i drawing.dxf
```

Agent 应根据命令的 JSON 结果或任务元数据定位实际输出，不要自行假设带有
时间戳的文件名。项目 API Key 与 Agent 自身可调用的模型能力是两套独立
能力：Agent 不会静默替项目写入 API Key。

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
|-- agent-harness/               # cad-translate CLI 包（明确维护）
|   |-- cad_translate/           # click 门面 -> 委托 backend/app
|   `-- setup.py                 # 单一 SemVer 版本，读取 backend/app/version.py
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
| CAD | ezdxf, pandas, openpyxl, xlrd, pywin32（Windows COM） |
| LLM | OpenAI-compatible SDK，支持 10+ 厂商预设 |
| 打包 | PowerShell, PyInstaller, Nuitka |

## AI Skill

仓库内置 `.agents/skills/cad-translation-dev/` 和 `cad-translation-skill/`，用于辅助开发、构建发布和安全审计。

运行安全审计：

```powershell
& .\.agents\skills\cad-translation-dev\scripts\security-audit.ps1 -ReleaseDir scale_release
```

## 文档索引

| 文档 | 内容 |
|------|------|
| [ARCHITECTURE.md](docs/modern/ARCHITECTURE.md) | 系统架构与数据流 |
| [BACKEND_API_SPEC.md](docs/modern/BACKEND_API_SPEC.md) | 后端 API 规范 |
| [FRONTEND_API_SPEC.md](docs/modern/FRONTEND_API_SPEC.md) | 前端接口规范 |
| [LLM_PROVIDERS.md](docs/modern/LLM_PROVIDERS.md) | LLM 厂商与配置 |
| [CAD_CONVERTER_BACKENDS.md](docs/modern/CAD_CONVERTER_BACKENDS.md) | DWG 转换后端 |
| [AUTOCAD_COM_DETECTION.md](docs/modern/AUTOCAD_COM_DETECTION.md) | AutoCAD COM 自动检测与部署前置条件 |
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

1. Admin Guard **默认开启且 fail-closed**。当 `ENABLE_ADMIN_GUARD=true` 时，敏感的任务/项目/文件/配置/翻译端点都需要 `ADMIN_API_TOKEN`（通过 `X-Admin-Token` 头或 `Authorization: Bearer` 提交）。若 Guard 开启但 **未配置** Token，所有受保护路由返回 `503 Service Unavailable`，而不会静默放行。**仅**在受信网络的单用户部署中才显式设置 `ENABLE_ADMIN_GUARD=false` 开放访问。
2. 打包脚本会自动对运行时配置中的 API Key 脱敏，但开发环境的 `.env` 仍需妥善保管。
3. 后端使用 `resolve_within_directory` 和 `get_safe_filename` 防止路径遍历。
4. 本地开发默认使用 HTTP；公网部署应在反向代理上配置 TLS。

### 多用户并发与安全/授权模型

系统支持内网部署下多操作者并发处理 CAD 任务，行为要点：

- **任务隔离**：每个 CAD 任务有独立 UUID 任务目录（`outputs/cad_tasks/{task_id}/`），源文件、Excel、译文 CAD 与日志互不混用。
- **跨进程文件锁**：任务元数据、翻译 checkpoint 与运行时配置通过原子写 + 稳定 `.lock` 侧车文件的跨进程文件锁保护，POSIX 用 `fcntl.flock`，Windows 用 `msvcrt.locking`。Windows 上原子改名 （`os.replace`）可能在并发读方短暂占用目标文件时抛出 `PermissionError [WinError 5]`；写入端会对这种瞬时共享冲突做有上限的退避重试，保证原子写不会偶发失败。
- **集中式 `task_id` 校验**：凡接受 `task_id` 的任务端点与服务方法，都会在其拼接进任意文件系统路径前校验其是否符合系统生成的形态（8 位小写十六进制，`uuid4().hex[:8]`）。含 `../`、`.`、路径分隔符或任何非十六进制文本的取值会被以 `400` 拒绝，调用方无法读取/下载/删除/回填任务树之外的路径。

**单租户模型**：本系统是面向内部部署的**单租户** Web 应用，**没有 per-user 账户体系**，不提供同一实例上不同用户间的数据隔离；一台实例上的所有项目/任务/文件同属同一逻辑租户。

**AutoCAD COM 自动检测与部署边界**：

- 后端通过**枚举已注册的版本化 ProgID**（`AutoCAD.Application.<主版本>[.<次版本>]`，兼容 32/64 位注册表视图）并结合**进程表**来探测 AutoCAD；代码不把版本号写死到 2022，未来新版本无需改代码即可识别。详细探测逻辑位于 `backend/app/functions/autocad_discovery.py`，通过 mock `winreg` / 进程表 / `win32com` 即可运行单测，无需真实 AutoCAD。
- 仅当 **COM 桥接脚本存在** 且 **应用程序已注册或正在运行** 时才判定为可用；**仅有 Python 脚本不代表 AutoCAD 已安装**。
- 连接层（`backend/app/services/autocad_converter.py`）在子进程超时内运行，按探测到的版本化 ProgID 由新到旧尝试，连接失败会记录具体原因（`activation_failed` / `not_detected` 等）而非静默吞掉异常，也不会泄漏进程或文档。
- 自动模式会按探测结果筛除确定不可用的 COM 后端，同时保留 `haochen_com` → `autocad_com` → ODA/LibreDWG 的回退链；COM 转换仍默认单实例串行（`CAD_COM_CONCURRENCY=1`）。
- **有界 COM 激活**：**注册 ≠ 一定可激活**。浩辰（GStarCAD）/ 中望（ZWCAD）/ AutoCAD 的激活统一由单一环境变量 `CAD_COM_ACTIVATION_TIMEOUT` 约束（默认 **30s**，真实 AutoCAD 2026 冷启动约 6.5s，留足余量）。探测阶段为**仅分类**：COM 对象在 worker 线程自己的 apartment 内完成激活/读取 `Version`/`Documents`/释放，**绝不跨线程交给调用方**；真实转换在专用 COM 子进程内**同步**激活，激活/打开文档/转换/释放保持在同一 COM 线程/进程，父进程子进程超时可做进程级回收，避免遗留 `acad.exe`。对「已注册但激活超时/失败（挂起、位宽/权限/损坏）」的 COM 后端归类为 `activation_timeout` / `activation_failed` 并跳过，避免长时间卡住；自动模式不把「仅注册但不可激活」的浩辰/中望误判为可用并排在回退链最前。ProgID 列表做**大小写不敏感去重**，避免重复尝试与诊断噪声。
- **探测后紧接连接的陈旧 proxy 韧性**：探测可能启动并立即 `Quit` 一个 CAD 实例，其 ROT 条目会短暂残留；紧接着的连接若用 `GetActiveObject` 可能拿到指向正在退出的实例的**陈旧 active proxy**。现在探测在 `Quit` 后会等待该实例离开 ROT（有界，`DEFAULT_QUIT_CONFIRM_TIMEOUT`），连接层则校验 `Version`/`Documents`，遇到不可用的陈旧 active proxy 自动改用 `Dispatch` 重新启动一个可用实例，从而避免探测/转换留下 `acad.exe` / ROT 残留。
- **AutoCAD 安装与 COM 能力属于运行后端的 Windows 主机，不属于任何浏览器客户端**；本系统仍为**单租户**，不提供 per-user 任务隔离。所谓「自动检测」仅指后端能在自身主机上找到所调用的 AutoCAD。后端**不会自动安装 AutoCAD**；缺失时可以暂用 ODA / LibreDWG 作为备用，但复杂或生产 DWG 仍建议安装并注册 AutoCAD、浩辰 CAD 或中望 CAD，并检查转换结果。
- 参见 [AUTOCAD_COM_DETECTION.md](docs/modern/AUTOCAD_COM_DETECTION.md)。

- **`ENABLE_ADMIN_GUARD` 默认开启且 fail-closed**。在 `backend/.env` 设置 `ADMIN_API_TOKEN` 后，所有敏感任务/项目/文件/配置/翻译端点都要求 Token；调用方以 `X-Admin-Token: <token>` 或 `Authorization: Bearer <token>` 认证。
- **fail-closed 行为**：若 `ENABLE_ADMIN_GUARD=true` 但 `ADMIN_API_TOKEN` 留空，所有受保护端点返回 `503 Service Unavailable`，避免「想开启保护却忘记配置凭证」导致敏感端点被静默暴露；不存在静默 fail-open 路径。
- 仅显式设置 `ENABLE_ADMIN_GUARD=false` 才开放全部端点（受信网络的单用户部署），不推荐用于共享环境。
- `task_id` / `project_id` / `file_id` 单独 **不是** 访问凭证——它只在调用方通过 admin guard 后标识某个资源。
- 跨租户数据隔离需要引入账户体系（登录/会话/JWT、项目/任务/文件上的 per-user 归属字段、按用户过滤查询），**超出本仓库范围**。若需在同一主机服务多个相互独立的租户，应每个租户部署一个实例，或在前置部署反向代理 / SSO。

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
