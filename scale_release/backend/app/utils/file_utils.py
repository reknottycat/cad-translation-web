#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File processing utility functions.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

import structlog
from fastapi import UploadFile

logger = structlog.get_logger(__name__)


def ensure_directory(directory: Path) -> None:
    """Ensure a directory exists."""
    directory.mkdir(parents=True, exist_ok=True)


def get_file_hash(file_path: Path) -> str:
    """Calculate an MD5 hash for a file."""
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        logger.error("file_hash_failed", file_path=str(file_path), error=str(e))
        return ""


async def validate_file(file: UploadFile, settings) -> Dict[str, Any]:
    """Validate an uploaded file."""
    try:
        if not file.filename:
            return {"valid": False, "error": "File name is required"}

        file_extension = Path(file.filename).suffix.lower()
        allowed_extensions = [".dwg", ".dxf"]

        if file_extension not in allowed_extensions:
            return {
                "valid": False,
                "error": f"Unsupported file type: {file_extension}, supported types: {', '.join(allowed_extensions)}",
            }

        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)

        if file_size == 0:
            return {"valid": False, "error": "File is empty"}

        if file_size > settings.MAX_FILE_SIZE:
            return {
                "valid": False,
                "error": (
                    f"File size exceeds limit: {file_size / 1024 / 1024:.1f}MB "
                    f"> {settings.MAX_FILE_SIZE / 1024 / 1024:.1f}MB"
                ),
            }

        mime_type, _ = mimetypes.guess_type(file.filename)

        return {
            "valid": True,
            "file_size": file_size,
            "file_type": file_extension.replace(".", ""),
            "mime_type": mime_type,
        }
    except Exception as e:
        logger.error("file_validation_failed", filename=file.filename, error=str(e))
        return {"valid": False, "error": f"File validation failed: {str(e)}"}


def get_safe_filename(filename: str) -> str:
    """Return a filename safe for local filesystem use."""
    raw_name = Path(str(filename or "")).name
    safe_filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw_name).strip()
    safe_filename = safe_filename.lstrip(".")

    if not safe_filename:
        safe_filename = "file"

    if len(safe_filename) > 255:
        name, ext = os.path.splitext(safe_filename)
        safe_filename = name[: 255 - len(ext)] + ext

    return safe_filename


def resolve_within_directory(base_dir: Path, relative_path: str | Path) -> Path:
    """Resolve a path and ensure it stays inside base_dir."""
    base_dir = Path(base_dir).resolve()
    candidate = Path(relative_path)
    resolved = (candidate if candidate.is_absolute() else base_dir / candidate).resolve(strict=False)

    try:
        resolved.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError("Path escapes outside the allowed directory") from exc

    return resolved


def get_file_info(file_path: Path) -> Dict[str, Any]:
    """Get file metadata."""
    try:
        if not file_path.exists():
            return {"exists": False}

        stat = file_path.stat()
        return {
            "exists": True,
            "size": stat.st_size,
            "created": stat.st_ctime,
            "modified": stat.st_mtime,
            "extension": file_path.suffix.lower(),
            "name": file_path.name,
            "stem": file_path.stem,
        }
    except Exception as e:
        logger.error("file_info_failed", file_path=str(file_path), error=str(e))
        return {"exists": False, "error": str(e)}


def cleanup_temp_files(directory: Path, max_age_hours: int = 24) -> int:
    """Remove old temporary files."""
    if not directory.exists():
        return 0

    current_time = time.time()
    max_age_seconds = max_age_hours * 3600
    cleaned_count = 0

    try:
        for file_path in directory.rglob("*"):
            if file_path.is_file():
                file_age = current_time - file_path.stat().st_mtime
                if file_age > max_age_seconds:
                    try:
                        file_path.unlink()
                        cleaned_count += 1
                        logger.debug("temp_file_cleaned", file_path=str(file_path))
                    except Exception as e:
                        logger.warning("temp_file_cleanup_failed", file_path=str(file_path), error=str(e))

        logger.info("temp_files_cleaned", directory=str(directory), cleaned_count=cleaned_count)
        return cleaned_count
    except Exception as e:
        logger.error("temp_file_cleanup_failed", directory=str(directory), error=str(e))
        return 0


def format_file_size(size_bytes: int) -> str:
    """Format bytes as a human-readable size."""
    if size_bytes == 0:
        return "0 B"

    size_names = ["B", "KB", "MB", "GB", "TB"]
    import math

    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_names[i]}"


def is_valid_cad_file(file_path: Path) -> bool:
    """Check whether a file looks like a CAD file."""
    try:
        if not file_path.exists():
            return False

        extension = file_path.suffix.lower()
        if extension not in [".dwg", ".dxf"]:
            return False

        with open(file_path, "rb") as f:
            header = f.read(16)

            if extension == ".dwg":
                return header.startswith(b"AC")
            if extension == ".dxf":
                f.seek(0)
                first_line = f.readline(100).decode("utf-8", errors="ignore")
                return "999" in first_line or "DXF" in first_line.upper()

        return True
    except Exception as e:
        logger.error("cad_validation_failed", file_path=str(file_path), error=str(e))
        return False


def create_backup(file_path: Path, backup_dir: Optional[Path] = None) -> Optional[Path]:
    """Create a backup of a file."""
    try:
        if not file_path.exists():
            return None

        if backup_dir is None:
            backup_dir = file_path.parent / "backups"

        ensure_directory(backup_dir)

        from datetime import datetime
        import shutil

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{file_path.stem}_{timestamp}{file_path.suffix}"
        backup_path = backup_dir / backup_name
        shutil.copy2(file_path, backup_path)

        logger.info("backup_created", original=str(file_path), backup=str(backup_path))
        return backup_path
    except Exception as e:
        logger.error("backup_failed", file_path=str(file_path), error=str(e))
        return None
