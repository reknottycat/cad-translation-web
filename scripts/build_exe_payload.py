#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""组装 Windows 便携 EXE 的 runtime_payload.zip（Linux CI 可运行）。

移植自 scripts/build_scale_exe.ps1 的 staging 逻辑，供 CNB 云端流水线在
Linux 容器中调用（也可在本地任何有 Python 3.9+ 的环境使用）：

- 复制 backend/（排除开发/缓存/密钥/测试文件）
- 复制 frontend/dist/（需先完成前端构建）
- 复制 tools/（如存在）
- 清洗 backend/config/runtime_config.local.json 中的 API Key
- 打包为 runtime_payload.zip（zip 根目录即 backend/ frontend/ tools/）

用法：
    python scripts/build_exe_payload.py [--root .] [--output runtime_payload.zip]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

# 与 scripts/build_scale_exe.ps1 中的排除规则保持一致（posix 风格路径）
EXCLUDE_PATTERNS = [
    r"(^|/)__pycache__(/|$)",
    r"(^|/)\.pytest_cache(/|$)",
    r"(^|/)tests(/|$)",
    r"(^|/)outputs(/|$)",
    r"(^|/)uploads(/|$)",
    r"(^|/)temp(/|$)",
    r"(^|/)\.env$",
    r"(^|/)\.env\.(?!example$)",
    r"\.db$",
    r"(^|/)README_MODERN\.md$",
    r"(^|/)test_.*\.py$",
    r"(^|/)simple_test\.py$",
    r"(^|/)setup_and_test\.py$",
    r"(^|/)quick_start\.py$",
    r"(^|/)run_celery\.py$",
]
_COMPILED = [re.compile(pattern) for pattern in EXCLUDE_PATTERNS]


def _excluded(rel_posix: str) -> bool:
    return any(pattern.search(rel_posix) for pattern in _COMPILED)


def copy_tree_into(stage_dir: Path, source: Path, target_name: str) -> int:
    """把 source 目录内容复制到 stage_dir/target_name，途中应用排除规则。"""
    if not source.is_dir():
        return 0
    copied = 0
    for item in sorted(source.rglob("*")):
        rel = item.relative_to(source).as_posix()
        if not rel or _excluded(f"{target_name}/{rel}"):
            continue
        dest = stage_dir / target_name / rel
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, dest)
            copied += 1
    return copied


def sanitize_runtime_config(config_path: Path) -> None:
    """抹掉 runtime_config.local.json 中的敏感字段（与 ps1 版本一致）。"""
    if not config_path.is_file():
        return

    data = json.loads(config_path.read_text(encoding="utf-8"))

    def scrub(obj):
        if isinstance(obj, dict):
            for key, value in list(obj.items()):
                key_lower = key.lower()
                if key_lower == "api_key" and isinstance(value, str):
                    obj[key] = ""
                elif key_lower == "api_key_source":
                    obj[key] = "none"
                elif key_lower == "api_key_configured":
                    obj[key] = False
                else:
                    scrub(value)
        elif isinstance(obj, list):
            for item in obj:
                scrub(item)

    scrub(data)
    config_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


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
        sanitize_runtime_config(stage / "backend" / "config" / "runtime_config.local.json")

        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(stage).as_posix())

    print(
        f"runtime payload ready: {output} "
        f"(backend files: {n_backend}, frontend files: {n_frontend}, tools files: {n_tools})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
