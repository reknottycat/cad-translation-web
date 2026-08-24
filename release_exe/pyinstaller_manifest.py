#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PyInstaller 清单 — 供 scripts/build_scale_exe.ps1 读取。

该脚本以 JSON 形式输出打包后端 Web 应用所需的 hidden imports 与
collect-* 参数，避免把整条依赖树硬编码在 PowerShell 脚本里。

输出结构：
    {
      "hidden_imports": [...],        -> --hidden-import <item>
      "collect_submodules": [...],    -> --collect-submodules <item>
      "collect_data": [...],          -> --collect-data <item>
      "collect_all": [...],           -> --collect-all <item>
    }
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List


# 后端运行期直接/间接依赖，但 PyInstaller 静态分析可能漏掉的模块
HIDDEN_IMPORTS: List[str] = [
    # FastAPI / Pydantic 动态 import 的包
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # pydantic v2 的编译核心
    "pydantic_core",
    "pydantic_settings",
    # SQLAlchemy 方言
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.ext.asyncio",
    # Celery + 可选 broker
    "celery.apps",
    "celery.backends",
    "celery.fixups",
    # Windows COM (pywin32) —— 平台相关，缺少时不应导致打包失败
    "win32api",
    "win32com",
    "win32com.client",
    "pythoncom",
    "pywintypes",
    # 配置与日志
    "structlog",
    "dotenv",
    "dotenv.main",
]

# 需要递归收集所有子模块的包
COLLECT_SUBMODULES: List[str] = [
    "uvicorn",
    "fastapi",
    "pydantic",
    "sqlalchemy",
    "multipart",
    "email_validator",
    "anyio",
]

# 需要把包内的数据文件一并收集的包
COLLECT_DATA: List[str] = [
    "certifi",
    "passlib",
    "structlog",
]

# 需要整包收集（模块 + 数据 + 子模块）的包
COLLECT_ALL: List[str] = [
    "celery",
    "pandas",
    "openpyxl",
    "ezdxf",
    "cryptography",
]


def main() -> int:
    manifest: Dict[str, Any] = {
        "hidden_imports": HIDDEN_IMPORTS,
        "collect_submodules": COLLECT_SUBMODULES,
        "collect_data": COLLECT_DATA,
        "collect_all": COLLECT_ALL,
    }
    json.dump(manifest, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
