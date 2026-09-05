---
title: 依赖配置规则
impact: HIGH
impactDescription: 正确配置依赖是运行的前提
tags: [dependencies, installation, requirements]
---

## 依赖配置规则

### Python 与项目依赖

项目主线要求 Python 3.10+。从仓库根目录安装后端和维护中的 CLI：

~~~powershell
python -m pip install -i https://mirrors.aliyun.com/pypi/simple -r backend\requirements.txt
python -m pip install -e agent-harness
cad-translate --help
cad-translate doctor
~~~

前端开发另需 Node.js 18+：

~~~powershell
cd frontend
npm install
~~~

> **国内镜像加速：** `frontend/.npmrc` 已将 npm 源指向淘宝 npmmirror
> （`https://registry.npmmirror.com`）。若 pip 安装 PyPI 官方源过慢，
> 可使用阿里云镜像（如上方所示，添加 `-i https://mirrors.aliyun.com/pypi/simple`
> 参数，或设置环境变量 `PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple`）。

CLI 的 `pyproject.toml` 声明了 `click`、`ezdxf`、`pandas`、`openpyxl`、
`pydantic-settings` 等运行依赖；不要再从根目录历史脚本推导安装入口。

### CAD 系统依赖

- DXF-only 工作不需要安装 CAD 软件。
- DWG 转 DXF 建议优先安装 AutoCAD、浩辰 CAD/GStarCAD 或中望 CAD/ZWCAD，
  并使用运行后端 Windows 主机上的 COM 能力。
- ODA File Converter 和 LibreDWG 是备用转换后端，不建议作为复杂或生产
  DWG 的首选；使用备用后端时必须检查输出 DXF。
- AutoCAD/GStarCAD/ZWCAD 的安装与注册不会由本项目自动完成，也不会由浏览器
  客户端代为探测。

### 配置检查

静态环境配置位于 `backend/.env`（模板为 `backend/.env.example`）；LLM
运行时配置默认位于 `Path.home()/.config/cli-anything-cad/config.json`，
可用 `CAD_TRANSLATION_ENV_FILE`、`XDG_CONFIG_HOME` 或
`CAD_TRANSLATION_RUNTIME_CONFIG_FILE` 覆盖。API Key 只放在受保护的运行时
配置或环境变量中，不得写入 Git、Skill、task.json、日志或交付包。
