#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""以编程方式运行 PyInstaller 打包 launcher（Windows 本地 / Wine CI 通用）。

参数与 scripts/build_scale_exe.ps1 保持一致：读取
release_exe/pyinstaller_manifest.py 声明的 hidden imports / collect-* 配置，
把 runtime_payload.zip 以 ``--add-data`` 的形式打进 launcher.exe（onedir）。

必须在仓库根目录下运行（相对路径 dist / build / spec / runtime_payload.zip
均相对当前工作目录解析）：

    python release_exe/run_pyinstaller.py [runtime_payload.zip]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from pyinstaller_manifest import (  # noqa: E402
    COLLECT_DATA,
    COLLECT_ALL,
    COLLECT_SUBMODULES,
    HIDDEN_IMPORTS,
)


def build_argv(payload: str) -> list:
    argv = [
        "--noconfirm",
        "--onedir",
        "--console",
        "--name",
        "launcher",
        "--distpath",
        "dist",
        "--workpath",
        "build",
        "--specpath",
        "spec",
        # Windows PyInstaller 使用 ";" 作为 --add-data 的路径分隔符。
        # 源路径必须用绝对路径：相对路径会相对于 --specpath(spec/) 解析，
        # 而非当前工作目录，导致 "Unable to find .../spec/runtime_payload.zip"。
        "--add-data",
        f"{os.path.abspath(payload)};.",
        # 使用相对路径（脚本约定在仓库根目录运行）。绝对路径在 Wine 下会被
        # Path.resolve() 解析成 Z:\... 反斜杠形式，PyInstaller(wrapper) 无法识别。
        "release_exe/launcher.py",
    ]
    for item in HIDDEN_IMPORTS:
        argv += ["--hidden-import", item]
    for item in COLLECT_SUBMODULES:
        argv += ["--collect-submodules", item]
    for item in COLLECT_DATA:
        argv += ["--collect-data", item]
    for item in COLLECT_ALL:
        argv += ["--collect-all", item]
    return argv


def main() -> int:
    payload = sys.argv[1] if len(sys.argv) > 1 else "runtime_payload.zip"
    import PyInstaller.__main__

    argv = build_argv(payload)
    print("[run_pyinstaller] PyInstaller argv:")
    print(" ".join(argv))
    PyInstaller.__main__.run(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
