#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""组装 Windows 便携 EXE 的 runtime_payload.zip（Linux CI 可运行）。

供本地 PowerShell、Nuitka 和 CNB 云端流水线共享的 staging 逻辑，在
Linux 容器中调用（也可在本地任何有 Python 3.9+ 的环境使用）：

- 复制 backend/（使用统一发布过滤器排除开发/缓存/密钥/测试文件）
- 复制 frontend/dist/（需先完成前端构建）
- 复制 tools/（如存在）
- 排除 runtime_config.local.json 和 provider/API 凭据
- 打包为 runtime_payload.zip（zip 根目录即 backend/ frontend/ tools/）

用法：
    python scripts/build_exe_payload.py [--root .] [--output runtime_payload.zip]
"""

from __future__ import annotations

import argparse
import tempfile
import zipfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_manifest import (  # noqa: E402
    audit_directory,
    audit_zip,
    copy_tree_into,
    sanitize_json_file,
    write_tools_manifest,
)


def sanitize_runtime_config(config_path: Path) -> None:
    """Compatibility wrapper for callers that explicitly sanitize a JSON file."""
    sanitize_json_file(config_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="仓库根目录")
    parser.add_argument("--output", default="runtime_payload.zip", help="输出 zip 路径")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output = Path(args.output).resolve()

    backend = root / "backend"
    frontend_dist = root / "frontend" / "dist"
    tools = root / "tools"
    launcher = root / "release_exe" / "launcher.py"

    if not backend.is_dir():
        raise SystemExit(f"backend directory not found at {backend}")
    if not frontend_dist.is_dir():
        raise SystemExit(
            f"frontend/dist not found at {frontend_dist}; build the frontend first"
        )
    if not launcher.is_file():
        raise SystemExit(f"launcher source not found at {launcher}")

    with tempfile.TemporaryDirectory(prefix="cad_payload_") as tmp:
        stage = Path(tmp)
        n_backend = copy_tree_into(stage, backend, "backend")
        n_frontend = copy_tree_into(stage, frontend_dist, "frontend/dist")
        n_tools = copy_tree_into(stage, tools, "tools")
        write_tools_manifest(stage / "tools")
        audit_directory(
            stage,
            required=("backend/app/main.py", "frontend/dist/index.html"),
        )

        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(stage).as_posix())
    audit_zip(output)

    print(
        f"runtime payload ready: {output} "
        f"(backend files: {n_backend}, frontend files: {n_frontend}, tools files: {n_tools})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
