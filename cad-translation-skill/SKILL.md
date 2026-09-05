---
name: cad-translation
description: CAD 图纸翻译系统的 Web、CLI 与 Agent 协作指南，覆盖 DWG/DXF 文本提取、LLM 翻译、Excel 协作、DXF 回填、Windows COM 探测和交付包使用。
license: MIT
compatibility: opencode
metadata:
  audience: developers and agents
  workflow: cad-processing
  tags: [cad, dxf, dwg, translation, python, fastapi, cli, agent]
---

## 系统定位

项目主线是 FastAPI + React Web 应用，同时维护命令行入口
cad-translate。Web、CLI 和 Agent 辅助流程应共享 backend/app/ 的实现；
不要把根目录历史脚本当成当前主流程。

## Agent 调用 Skill 时的 API Key 规则

Skill 本身不需要 API Key。用户在当前对话中让 Agent 使用本 Skill 时，
Agent 可以使用当前会话已经具备的模型和工具能力完成检查、文本提取后的
有限翻译、结果整理或文件编排；不应仅因为启用 Skill 就要求用户配置项目
provider/API Key。

这和项目运行时的 LLM 鉴权是两个边界：

1. **Agent 辅助模式**：由当前 Agent 在已授权会话中完成推理或翻译，使用
   Agent 本身的运行能力，不会替项目保存可复用的 provider 凭据。仍要遵守
   会话上下文、文件大小、模型额度和数据隐私限制。
2. **项目运行时模式**：Web、cad-translate pipeline translate-excel、
   Celery 和无人值守批处理会调用项目配置的 LLM provider。除非选择本地或
   免 Key 的后端，否则仍需在运行时配置 API Key/其他认证。

使用 Agent 或远程 provider 发送图纸文本前，要确认用户授权和数据边界。
不要把 API Key 写进 Skill、项目 JSON、任务日志、Git 或发布包。Agent 没有
所需模型/工具，或输入超过上下文容量时，应说明限制；只有用户明确提供并
授权后，才切换到项目 LLM 运行时。

## 处理流程

1. **DWG → DXF**：优先使用已安装的 AutoCAD COM、浩辰/GStarCAD 或中望/ZWCAD；
   ODA File Converter 和 LibreDWG 作为备用，复杂或生产图纸使用前要检查转换
   结果。DXF-only 工作不需要 CAD 软件。
2. **DXF → Excel**：使用 backend/app/functions/text_extractor.py 提取
   TEXT、MTEXT、ATTDEF 等文本，生成任务隔离的 Excel。
3. **Excel 翻译**：可在 Agent 会话中处理有限结果，也可由 Web/CLI 使用
   已配置的 LLM provider 批量处理。
4. **Excel → DXF**：使用 replace 或 add 模式回填，保留原始文件和任务日志。

**交付约定（Agent 直接处理时）**：翻译回填完成后，最终交付的就是 DXF
文件。**不要**再把翻译后的 DXF 转回 DWG——DWG → DXF 只是为了便于 ezdxf
读取和编辑文字；翻译完成后直接交给用户 DXF 即可。除非用户明确要求 DWG
输出，否则不要额外执行 COM / ODA / LibreDWG 的 DWG 回转，也不要把这种
多余转换写进交付结果。

**双语自动判断指引（图纸本地语言 + 通用英文标识混排，翻成用户指定的目标语言
T）**：目标语言 T 以**用户要求**为准（俄文/英文/日文/法文等，**不要假设固定为
某一种**），对每条文本按推荐逻辑判断保留还是翻译，不要盲目全译：

~~~
目标语言 = T（用户指定，不预设默认）

IF 文本已是目标语言 T:          KEEP
ELIF 文本是中文:                TRANSLATE_TO_T
ELIF 文本是英文且英文 ≠ T:
    IF 用户要求保留 英文+T 双语:  KEEP
    ELSE:
        IF 是人名/型号/位号/标准/编码/单位:  KEEP
        ELSE:                                TRANSLATE_TO_T
ELIF 文本是其它语言:            按用户意图处理，拿不准默认 KEEP
ELSE:                            KEEP
~~~

**混合字符串**如 `XV-101 Solenoid Valve`：保护型号/位号 `XV-101`，只把描述
部分按目标语言 T 翻译（T=俄文 → `Электромагнитный клапан`、T=中文 → `电磁阀`），
得到 `XV-101 Электромагнитный клапан`（T=俄文）等。人名、型号、位号、标准、
编码、单位一律不译。

**Agent 标准双语工作流**：DWG → DWG→DXF → 提取全部 TEXT/MTEXT/ATTRIB/ATTDEF/BLOCK
→ 语言识别 → 建立已有术语表 → 确认目标语言 T（用户要求）→ 识别需翻译的源语文本
（中文等）→ 源语→T → 回填 → 验证源语残留=0 → 判断用户是否要求把通用英文也统一成 T
（否→完成；是→提取英文-only、排除人名/型号/位号/标准/编码/单位、英文→T、回填、
英文残留分类检查、CAD 版式检查）→ 最终交付 DXF。详见 rules/06-bilingual-translation.md。

Web 全流程接口是 /api/cad/upload；分步接口是 /api/cad/extract 和
/api/cad/apply-translation。接口以 /api/docs 和仓库中的 API 路由参考为准。

## 当前代码入口

~~~text
backend/                         活跃后端和共享实现
frontend/                        React/Vite 前端
agent-harness/cad_translate/     cad-translate CLI 源码
scripts/build_scale.ps1          运行时交付包构建
docs/modern/                     架构、API、COM 探测和发布文档
trans_CAD_gui_V1.0/              遗留 GUI，仅兼容维护
命令行专用/                       遗留脚本，仅兼容维护
~~~

scale_release/、scale_release.zip 和 scale_release_exe/ 都是生成物，不能
直接编辑或提交。应修改源代码或构建脚本后重新生成。

## 常用命令

~~~powershell
# Web
cd backend
python run_server.py

# 另一个终端
cd frontend
npm run dev

# CLI 开发安装
cd agent-harness
python -m pip install -e .
cad-translate --version
cad-translate --help
cad-translate doctor
~~~

CLI 分步流程：

~~~powershell
cad-translate project new --name demo -o project.json
cad-translate pipeline convert -i drawing.dwg
cad-translate pipeline extract -i drawing.dxf
cad-translate pipeline translate-excel -i texts.xlsx
cad-translate pipeline apply -i drawing.dxf -e texts_translated.xlsx
~~~

所有命令的机器可读输出可在顶层命令加入 --json，例如
cad-translate --json tasks list。运行时配置默认位于
Path.home()/.config/cli-anything-cad/config.json，可由
XDG_CONFIG_HOME 或 CAD_TRANSLATION_RUNTIME_CONFIG_FILE 覆盖。

## Windows CAD 与多用户边界

AutoCAD、浩辰和中望的 COM 只存在于运行后端的 Windows 主机，浏览器客户
端的本地安装不会被服务器自动发现，系统也不会自动安装 CAD。探测结合
注册的版本化 ProgID、CAD 进程和 COM bridge；注册不等于激活成功，实际
COM 转换有超时、专用进程和默认串行限制（CAD_COM_CONCURRENCY=1）。

Web 可以接收多个客户端任务，任务目录、原子写入、跨进程锁和 UUID 文件名
用于避免常见覆盖；系统仍是单租户，没有按用户的数据隔离。内网部署应
配置持久化存储、合适的数据库和 worker、明确 CORS，并用
ADMIN_API_TOKEN 保护整个实例。

## 开发约束

- 单文件不超过 800 行；Python 新代码使用类型注解和 PEP 8。
- 版本只从 backend/app/version.py 的 __version__ 维护，并遵循 SemVer；
  验证 backend 与 cad-translate --version 一致。
- 行为、接口、配置或构建变化后同步更新帮助文本、错误、README 和现代文档。
- 写特征或指标必须做时序 shift，明确可见时间并防止 look-ahead leakage。
- 修改 backend/、frontend/ 或 agent-harness/ 源码，不要修改
  scale_release/backend/ 镜像。
