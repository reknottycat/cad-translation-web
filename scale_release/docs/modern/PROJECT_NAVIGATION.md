# 项目导航（现代化整理）

本文件用于快速定位“这个目录里每个模块是干什么的”。

## 1) 核心目录

- `backend/`: 后端 API、任务队列、翻译引擎。
- `frontend/`: Web 前端页面与组件。
- `docs/`: 说明文档、分析报告与现代化设计文档。
- `cad-translation-skill/`: 本项目技能定义与规则。
- `命令行专用/`: CLI 批处理入口（传统流程）。

## 2) 根目录关键文件

- `gui.py`: 传统桌面 GUI 入口。
- `extract_texts.py`: DXF 文本提取核心脚本（传统流程）。
- `回填.py`: DXF 回填核心脚本（传统流程）。
- `haochen_optimized_converter.py`: COM 路径 DWG->DXF 转换（浩辰/GStar/ZWCAD/AutoCAD）。
- `autocad_converter.py`: AutoCAD COM 方案。
- `README.md`: 项目总说明（历史版本）。

## 3) 后端关键路径

- `backend/app/main.py`: FastAPI 启动入口。
- `backend/app/config.py`: 全局配置（含统一 LLM 配置中心）。
- `backend/app/routers/translation.py`: 翻译相关 API（文本、批量、Excel、配置、providers）。
- `backend/app/api/routes/cad.py`: CAD 处理 API（提取、应用翻译、下载等）。
- `backend/app/services/llm/translation_service.py`: 新增统一翻译引擎（OpenAI-compatible + 多厂商预设）。
- `backend/app/services/alibaba_ai_translation_service.py`: 兼容包装层（已转发到统一引擎）。

## 4) 前端关键路径

- `frontend/src/components/CADWorkflow.tsx`: 三步 CAD 翻译工作流。
- `frontend/src/components/TranslationConfig.tsx`: 翻译配置 UI。
- `frontend/src/pages/HomePage.tsx`: 首页与能力展示。

## 5) 建议忽略目录（非源码）

- `node_modules/`
- `frontend/node_modules/`
- `backend/outputs/`
- `logs/`
- `__pycache__/`

## 6) 当前工程分层建议

- `legacy-flow`: 根目录脚本 + GUI（兼容保留）。
- `modern-web-flow`: `backend` + `frontend`（主线开发）。
- `docs-and-ops`: `docs` + `scripts`（文档、打包、运维）。
