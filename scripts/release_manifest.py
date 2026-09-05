#!/usr/bin/env python3
"""Canonical, secret-safe rules shared by release builders.

The release scripts run on both Windows and Linux.  Keeping the path filter and
archive audit here prevents the PowerShell and CI builders from drifting apart.
The functions intentionally report only paths and counts; they never print
configuration contents or secret values.
"""

from __future__ import annotations

import hashlib
import ast
import json
import os
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath

EXCLUDE_PATTERNS = (
    r"(^|/)(\.venv|venv|env|ENV)(/|$)",
    r"(^|/)(\.git|node_modules)(/|$)",
    r"-DESKTOP-[A-Z0-9]+\.py$",
    r"(^|/)[^/]+\.egg-info(/|$)",
    r"(^|/)(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache)(/|$)",
    r"\.pyc$",
    r"(^|/)(tests?|testing)(/|$)",
    r"(^|/)(test_.*|conftest)\.py$",
    r"(^|/)\.env$",
    r"(^|/)\.env\.(?!example$)",
    r"(^|/)runtime_config\.local\.json$",
    r"(^|/)local_settings\.py$",
    r"\.(?:db|sqlite|sqlite3|log)$",
    r"(^|/)(outputs|uploads|temp|logs|build|dist|\.egg-info)(/|$)",
    r"(^|/)(README_MODERN|simple_test|setup_and_test|quick_start|run_celery)\.py$",
    r"(^|/)(?:.*\.(?:pem|key|p12|pfx)|credentials?\.json)$",
)
_EXCLUDES = tuple(re.compile(item, re.IGNORECASE) for item in EXCLUDE_PATTERNS)
_SENSITIVE_KEYS = re.compile(
    r"(?:api[_-]?key|provider[_-]?api[_-]?keys?|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|password|secret)",
    re.IGNORECASE,
)


def validate_release_tag(tag: str, version_source: Path) -> None:
    number = r"(?:0|[1-9][0-9]*)"
    identifier = rf"(?:{number}|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    pattern = rf"v{number}\.{number}\.{number}(?:-{identifier}(?:\.{identifier})*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    if not re.fullmatch(pattern, tag):
        raise ValueError("release tag must be v-prefixed SemVer")
    tree = ast.parse(version_source.read_text(encoding="utf-8"))
    canonical = next((ast.literal_eval(node.value) for node in tree.body
                      if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "__version__"
                              for target in node.targets)), None)
    if tag != f"v{canonical}":
        raise ValueError("release tag does not match backend/app/version.py")


def normalized_relative(path: str | Path) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def is_excluded(relative: str | Path) -> bool:
    normalized = normalized_relative(relative)
    if normalized in {"_internal/certifi/cacert.pem", "certifi/cacert.pem"}:
        return False  # Public CA trust store required by HTTPS clients.
    if normalized == "frontend/dist" or normalized.startswith("frontend/dist/"):
        normalized = normalized.replace("frontend/dist", "frontend/built", 1)
    return any(pattern.search(normalized) for pattern in _EXCLUDES)


def scrub_secrets(value: object) -> object:
    """Return a JSON-safe copy with secret-bearing fields emptied."""
    if isinstance(value, dict):
        clean: dict[str, object] = {}
        for key, item in value.items():
            key_lower = str(key).lower()
            if key_lower == "api_key_configured":
                clean[str(key)] = False
            elif key_lower == "api_key_source":
                clean[str(key)] = "none"
            elif _SENSITIVE_KEYS.search(str(key)):
                clean[str(key)] = {} if isinstance(item, dict) else ""
            else:
                clean[str(key)] = scrub_secrets(item)
        return clean
    if isinstance(value, list):
        return [scrub_secrets(item) for item in value]
    return value


def sanitize_json_file(path: Path) -> None:
    if not path.is_file():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(
        json.dumps(scrub_secrets(data), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _contains_secret(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() == "api_key_source" and item == "none":
                continue
            if _SENSITIVE_KEYS.search(str(key)) and item not in (None, "", {}, [], False):
                return True
            if _contains_secret(item):
                return True
    elif isinstance(value, list):
        return any(_contains_secret(item) for item in value)
    return False


def _config_has_secret(path: Path) -> bool:
    if path.suffix.lower() not in {".json", ".yaml", ".yml"}:
        return False
    value = _read_config(path.name, path.read_bytes())
    return _contains_secret(value)


def _read_config(name: str, data: bytes) -> object:
    try:
        return json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        if name.lower().endswith((".yaml", ".yml")):
            try:
                import yaml
            except ImportError as exc:
                raise ValueError("PyYAML is required to audit YAML configuration") from exc
            try:
                return yaml.safe_load(data)
            except yaml.YAMLError:
                raise ValueError(f"invalid YAML configuration in release: {name}") from None
        raise ValueError(f"invalid JSON configuration in release: {name}") from None


def copy_tree_into(stage: Path, source: Path, target_name: str) -> int:
    """Copy a tree while pruning excluded directories before descending."""
    if not source.is_dir():
        return 0
    copied = 0
    target = stage / target_name
    for base, directories, filenames in os.walk(source, followlinks=False):
        base_path = Path(base)
        directories[:] = [name for name in sorted(directories)
                          if not (base_path / name).is_symlink()
                          and not is_excluded(f"{target_name}/{(base_path / name).relative_to(source).as_posix()}")]
        for name in sorted(filenames):
            item = base_path / name
            relative = item.relative_to(source).as_posix()
            if item.is_symlink() or is_excluded(f"{target_name}/{relative}"):
                continue
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, destination)
            copied += 1
    return copied


def write_tools_manifest(tools_dir: Path) -> None:
    """Describe only tools that are physically present in the bundle."""
    if not tools_dir.is_dir():
        return
    files = []
    for item in sorted(tools_dir.rglob("*")):
        if item.is_file() and item.name != "manifest.json":
            digest = hashlib.sha256(item.read_bytes()).hexdigest()
            files.append({"path": item.relative_to(tools_dir).as_posix(), "sha256": digest})
    (tools_dir / "manifest.json").write_text(
        json.dumps({"schema": 1, "files": files}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def audit_directory(root: Path, required: tuple[str, ...] = ()) -> None:
    problems: list[str] = []
    for required_path in required:
        if not (root / required_path).is_file():
            problems.append(f"missing required file: {required_path}")
    for item in root.rglob("*"):
        if is_excluded(item.relative_to(root)):
            problems.append(f"forbidden release path: {item.relative_to(root).as_posix()}")
        elif item.is_file() and _config_has_secret(item):
            problems.append(f"secret-bearing config: {item.relative_to(root).as_posix()}")
    if problems:
        raise ValueError("release audit failed: " + "; ".join(problems[:8]))


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    return not path.is_absolute() and ".." not in path.parts and not any(":" in part for part in path.parts)


def audit_zip(path: Path, max_nested_depth: int = 3) -> None:
    """Audit ZIP members, including nested ZIPs, before publication."""
    problems: list[str] = []
    remaining_bytes = 2 * 1024 ** 3

    def within_budget(info: zipfile.ZipInfo) -> bool:
        nonlocal remaining_bytes
        remaining_bytes -= info.file_size
        if info.file_size > 512 * 1024 ** 2 or remaining_bytes < 0:
            problems.append("archive exceeds 512 MiB per member or 2 GiB total audit budget")
            return False
        return True

    def inspect(blob: bytes, label: str, depth: int) -> None:
        try:
            from io import BytesIO

            with zipfile.ZipFile(BytesIO(blob)) as archive:
                for info in archive.infolist():
                    if not within_budget(info):
                        return
                    name = info.filename.replace("\\", "/")
                    # PyInstaller's standard library intentionally ships compiled
                    # modules in this archive; payload/backend caches stay banned.
                    audit_name = name
                    if label == "_internal/base_library.zip" and name.endswith(".pyc"):
                        audit_name = name[:-1]
                    if not _safe_member(name) or is_excluded(audit_name):
                        problems.append(f"forbidden archive member: {label}!{name}")
                    elif name.lower().endswith((".json", ".yaml", ".yml")):
                        try:
                            if _contains_secret(_read_config(name, archive.read(info))):
                                problems.append(f"secret-bearing config: {label}!{name}")
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            pass
                    if name.lower().endswith(".zip"):
                        if depth >= max_nested_depth:
                            problems.append(f"nested archive depth exceeded: {label}!{name}")
                        else:
                            inspect(archive.read(info), f"{label}!{name}", depth + 1)
        except (OSError, zipfile.BadZipFile):
            problems.append(f"invalid nested archive: {label}")

    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if not within_budget(info):
                break
            name = info.filename.replace("\\", "/")
            if not _safe_member(name) or is_excluded(name):
                problems.append(f"forbidden archive member: {name}")
            elif name.lower().endswith((".json", ".yaml", ".yml")):
                try:
                    if _contains_secret(_read_config(name, archive.read(info))):
                        problems.append(f"secret-bearing config: {name}")
                except (UnicodeDecodeError, json.JSONDecodeError):
                    pass
            if name.lower().endswith(".zip"):
                inspect(archive.read(info), name, 1)
    if problems:
        raise ValueError("release archive audit failed: " + "; ".join(problems[:8]))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--directory", type=Path)
    group.add_argument("--archive", type=Path)
    group.add_argument("--validate-tag")
    group.add_argument("--copy-tree", type=Path)
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--target-name")
    parser.add_argument("--version-source", type=Path,
                        default=Path(__file__).resolve().parents[1] / "backend/app/version.py")
    parser.add_argument("--write-tools-manifest", action="store_true")
    args = parser.parse_args()
    if args.copy_tree:
        if args.stage is None or not args.target_name or not _safe_member(args.target_name):
            parser.error("--copy-tree requires --stage and a safe relative --target-name")
        copy_tree_into(args.stage, args.copy_tree, args.target_name)
    elif args.validate_tag:
        validate_release_tag(args.validate_tag, args.version_source)
    elif args.directory:
        if args.write_tools_manifest:
            write_tools_manifest(args.directory / "tools")
        audit_directory(args.directory)
    else:
        audit_zip(args.archive)
    print("release audit passed")
