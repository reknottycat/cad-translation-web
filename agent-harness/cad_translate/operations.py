#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CAD pipeline step operations for the ``cad-translate`` CLI.

Each ``run_*`` function performs one pipeline stage and records the outcome as
a task in the shared, concurrency-safe file store (:mod:`cad_translate.store`),
delegating the actual CAD / Excel / LLM work to the backend's trusted modules
(:mod:`app.functions.*` and :mod:`app.services.*`).

Tasks are identified by a system-generated 8-char hex id and each **managed
task directory** (under the configured output root's ``cad_tasks/``) is
protected by the same per-task lifecycle lock + atomic metadata writes used by
the Web backend, so a CLI task can be listed, shown, deleted or cleared without
ever racing a concurrent writer.

Locking contract
----------------
Every ``run_*`` stage creates its task and performs the **entire** stage while
holding that task's lifecycle lock (``_begin_task``), so the final ``task.json``
write-back (``_write_task_meta``) always happens inside the same per-task
lifecycle lock that ``tasks delete`` / ``tasks clear`` take before removing a
task directory.  A concurrent delete/clear therefore either waits for the
writer to finish and then removes the complete task, or the write is refused
with ``FileNotFoundError`` when the directory was genuinely removed — never an
orphan, partial or duplicate record.

Task-dir vs. product-dir contract
---------------------------------
A task's canonical metadata always lives in its managed directory under
``cad_tasks/<task_id>/task.json`` — that is the single record ``tasks
list/show/delete/clear`` operate on.  The *product* file (the generated Excel,
DXF, etc.) is written:

* into the same managed task directory when ``--output-dir`` is **not** given, or
* into the user-supplied ``--output-dir`` when it is, and that location is
  recorded in the task metadata (``output_dir`` / ``output_file``) so the task
  stays consistent and queryable even when its products live outside the tree.

A ``--output-dir`` therefore never creates a stray task.json outside the managed
tree nor leaves an orphan "created" task behind.
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from . import bridge, store


def build_context(
    project_data: dict[str, Any] | None,
    input_file: str,
    output_dir: str | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    project_data = project_data or {}
    settings = bridge.get_settings()
    cad_defaults = bridge.get_runtime_config_service().get_cad_defaults_summary()
    context = {
        "input_file": input_file,
        "output_dir": output_dir
        or project_data.get("default_output_dir")
        or cad_defaults.get("default_output_dir")
        or str(settings.get_output_path()),
        "target_language": project_data.get("target_language", cad_defaults.get("target_language", settings.DEFAULT_TARGET_LANGUAGE)),
        "converter_backend": project_data.get("converter_backend", cad_defaults.get("converter_backend", settings.DWG_CONVERTER_BACKEND)),
        "font_name": project_data.get("font_name", cad_defaults.get("font_name", settings.DEFAULT_FONT_NAME)),
        "font_size_reduction": project_data.get(
            "font_size_reduction", cad_defaults.get("font_size_reduction", settings.DEFAULT_FONT_SIZE_REDUCTION)
        ),
        "translation_mode": project_data.get("translation_mode", cad_defaults.get("translation_mode", settings.DEFAULT_TRANSLATION_MODE)),
    }
    context.update(overrides)
    return context


def _validate_input(input_file: str, allowed_suffixes: set[str]) -> Path:
    path = Path(input_file).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    if path.suffix.lower() not in allowed_suffixes:
        raise ValueError(f"Unsupported file type: {path.suffix}")
    return path


def _task_id_of(meta: dict[str, Any]) -> str:
    """Return the canonical task id carried by a metadata record."""
    task_id = meta.get("task_id")
    if not task_id:
        raise ValueError("task.json metadata must carry a task_id")
    return task_id


def _write_task_meta(task_dir: Path, meta: dict[str, Any]) -> None:
    """Write the final task.json into the *managed* task directory.

    This is the single, authoritative metadata write a stage performs when it
    finishes.  It runs **inside the per-task lifecycle lock** so a concurrent
    ``tasks delete`` / ``tasks clear`` on the same ``task_id`` can never
    interleave with the write (delete/clear only remove a directory while
    holding that lock; a write that outlives a delete would otherwise recreate
    an orphan "done" task under a cleared id).

    If the managed directory no longer exists (it was deleted/cleared while we
    were finishing the stage) the write is refused: ``create_parents=False``
    means atomic_write_json raises ``FileNotFoundError`` instead of silently
    recreating an orphan task.  Callers therefore surface a clean "task was
    removed" failure and no residual task.json/orphan directory is left behind.

    Timestamps are stamped here so a stage never drops ``created_at`` /
    ``last_activity_at`` when it overwrites the placeholder record written by
    ``_begin_task`` — ``tasks list`` sorts on those keys.
    """
    import time

    task_id = _task_id_of(meta)
    meta.setdefault("created_at", time.time())
    meta["last_activity_at"] = time.time()
    # Re-entrant in-process lock: safe even when already inside _begin_task's
    # outer lifecycle lock.  On the process level it serialises against a
    # concurrent delete/clear holding the same sidecar lock.
    with store.task_lifecycle_lock(task_id):
        if not task_dir.is_dir():
            raise FileNotFoundError(
                f"Task {task_id} was removed while its stage was finishing; "
                "not recreating an orphan task"
            )
        store.atomic_write_json(task_dir / "task.json", meta, create_parents=False)


class _RunningTask:
    """Handle handed to a stage inside ``_begin_task``.

    ``task_dir``/``task_id`` are the canonical managed locations a stage must
    report; ``product_dir`` is where the product file is written (either the
    managed task dir or the user-supplied ``--output-dir``).
    """

    def __init__(self, task_id: str, task_dir: Path, product_dir: Path) -> None:
        self.task_id = task_id
        self.task_dir = task_dir
        self.product_dir = product_dir


@contextlib.contextmanager
def _begin_task(output_dir: str | None = None) -> Iterator[_RunningTask]:
    """Create a managed task dir and hold its lifecycle lock for the WHOLE stage.

    The per-task lifecycle lock is acquired once here and held until the stage
    body finishes, so the entire create → run → final ``task.json`` write-back
    is serialised against ``tasks delete`` / ``tasks clear`` of the same id
    (which also take that lock).  A concurrent delete therefore either:

    * waits for the stage to finish and then removes the completed task (the
      writer still returned 0 with a complete, queryable task.json), or
    * if a clear is already sweeping when this stage starts, this creation is
      ordered after it by the create/clear coordination lock, so the new task
      survives as a normal complete task.

    In every interleaving the writer exits 0 and leaves either a fully complete
    task or, when the task dir was genuinely removed mid-write (a delete that
    began and released the lock between our dir-exists check and the write),
    a clean ``FileNotFoundError`` — never a partial/duplicate/orphan record.
    """
    import time

    task_id = store.new_task_id()
    created = time.time()
    with store.task_create_or_clear_lock():
        with store.task_lifecycle_lock(task_id):
            directory = store.task_dir(task_id)
            directory.mkdir(parents=True, exist_ok=True)
            product_dir = _resolve_product_dir(directory, output_dir)
            _write_task_meta(directory, {
                "task_id": task_id,
                "created_at": created,
                "last_activity_at": created,
                "status": "created",
                "stage": "created",
            })
            yield _RunningTask(task_id, directory, product_dir)


def _resolve_product_dir(task_dir: Path, output_dir: str | None) -> Path:
    """Return where this stage's product file should be written.

    A user-supplied ``--output-dir`` places products there (kept out of the
    managed task tree); otherwise products are written into the managed task
    directory itself.  The caller must still write ``task.json`` into
    ``task_dir``, never here.
    """
    if output_dir:
        product_dir = Path(output_dir).expanduser().resolve()
        product_dir.mkdir(parents=True, exist_ok=True)
        return product_dir
    return task_dir


def run_extract(input_file: str, output_dir: str | None = None) -> dict[str, Any]:
    """Extract DXF text into an Excel workbook (DXF input only)."""
    input_path = _validate_input(input_file, {".dxf"})
    with _begin_task(output_dir) as t:
        result = bridge.get_text_extractor().extract_to_excel(str(input_path), str(t.product_dir))
        excel_file = result.get("output_file")
        _write_task_meta(t.task_dir, {
            "task_id": t.task_id,
            "original_filename": input_path.name,
            "normalized_dxf_filename": input_path.name,
            "text_count": result.get("texts_count", 0),
            "translation_count": 0,
            "excel_filename": Path(excel_file).name if excel_file else None,
            "translated_cad_filename": None,
            "status": "done",
            "stage": "extract",
            "output_dir": str(t.product_dir),
            "output_file": str(excel_file) if excel_file else None,
        })
        return {
            "success": True,
            "task_id": t.task_id,
            "task_dir": str(t.task_dir),
            "output_dir": str(t.product_dir),
            "input_file": str(input_path),
            "excel_file": excel_file,
            "text_count": result.get("texts_count", 0),
            "texts": result.get("texts", []),
        }


def run_convert(input_file: str, output_dir: str | None = None, backend_override: str | None = None) -> dict[str, Any]:
    """Convert a DWG file to DXF."""
    input_path = _validate_input(input_file, {".dwg"})
    with _begin_task(output_dir) as t:
        output_file = bridge.get_dwg_converter().convert(
            str(input_path),
            t.product_dir,
            backend_override=backend_override,
        )
        _write_task_meta(t.task_dir, {
            "task_id": t.task_id,
            "original_filename": input_path.name,
            "normalized_dxf_filename": Path(output_file).name,
            "text_count": 0,
            "translation_count": 0,
            "excel_filename": None,
            "translated_cad_filename": None,
            "status": "done",
            "stage": "convert",
            "output_dir": str(t.product_dir),
            "output_file": str(output_file),
        })
        return {
            "success": True,
            "task_id": t.task_id,
            "task_dir": str(t.task_dir),
            "output_dir": str(t.product_dir),
            "input_file": str(input_path),
            "output_file": str(output_file),
        }


def load_translation_map(excel_file: str) -> dict[str, str]:
    return bridge.get_translator().build_translation_map_from_excel(excel_file)


def run_apply(
    input_file: str,
    translation_map: dict[str, str] | None = None,
    excel_file: str | None = None,
    output_dir: str | None = None,
    font_name: str | None = None,
    font_size_reduction: int | None = None,
    translation_mode: str | None = None,
) -> dict[str, Any]:
    """Apply a translation map to a DXF file (DXF input only)."""
    input_path = _validate_input(input_file, {".dxf"})

    if translation_map is None:
        if not excel_file:
            raise ValueError("Either translation_map or excel_file is required.")
        translation_map = load_translation_map(excel_file)
    if not translation_map:
        raise ValueError("Translation map is empty.")

    with _begin_task(output_dir) as t:
        settings = bridge.get_settings()
        cad_defaults = bridge.get_runtime_config_service().get_cad_defaults_summary()
        output_path = t.product_dir / f"translated_{input_path.name}"
        resolved_translation_mode = translation_mode or cad_defaults.get("translation_mode") or settings.DEFAULT_TRANSLATION_MODE
        resolved_font_name = font_name or cad_defaults.get("font_name") or settings.DEFAULT_FONT_NAME
        resolved_font_size_reduction = (
            font_size_reduction
            if font_size_reduction is not None
            else cad_defaults.get("font_size_reduction", settings.DEFAULT_FONT_SIZE_REDUCTION)
        )

        result = bridge.get_text_applier().apply(
            dxf_file_path=str(input_path),
            output_file_path=str(output_path),
            translation_map=translation_map,
            translation_mode=resolved_translation_mode,
            font_name=resolved_font_name,
            font_size_reduction=resolved_font_size_reduction,
        )
        _write_task_meta(t.task_dir, {
            "task_id": t.task_id,
            "original_filename": input_path.name,
            "normalized_dxf_filename": input_path.name,
            "text_count": 0,
            "translation_count": len(translation_map),
            "excel_filename": Path(excel_file).name if excel_file else None,
            "translated_cad_filename": output_path.name,
            "status": "done",
            "stage": "apply",
            "output_dir": str(t.product_dir),
            "output_file": str(output_path),
        })
        return {
            "success": True,
            "task_id": t.task_id,
            "task_dir": str(t.task_dir),
            "output_dir": str(t.product_dir),
            "input_file": str(input_path),
            "output_file": str(output_path),
            "translated_entities": result.get("translated_entities", 0),
            "translation_count": len(translation_map),
            "translation_mode": resolved_translation_mode,
        }


def run_translate_excel(
    input_file: str,
    output_dir: str | None = None,
    source_language: str = "auto",
    target_language: str | None = None,
    translation_mode: str | None = None,
) -> dict[str, Any]:
    """Translate an Excel workbook in-place with the configured LLM provider."""
    input_path = _validate_input(input_file, {".xlsx", ".xls"})
    settings = bridge.get_settings()
    cad_defaults = bridge.get_runtime_config_service().get_cad_defaults_summary()
    resolved_target_language = target_language or cad_defaults.get("target_language") or settings.DEFAULT_TARGET_LANGUAGE
    resolved_translation_mode = translation_mode or cad_defaults.get("translation_mode") or "add"

    with _begin_task(output_dir) as t:
        output_path = t.product_dir / f"{input_path.stem}_translated{input_path.suffix}"
        input_df = pd.read_excel(input_path)
        if {"原文", "译文"}.issubset(set(str(col) for col in input_df.columns)):
            texts = input_df["原文"].fillna("").astype(str).tolist()
            translated = bridge.get_llm_translation_service().translate_batch(
                texts,
                source_lang=source_language,
                target_lang=resolved_target_language,
            )
            input_df["译文"] = translated
            input_df.to_excel(output_path, index=False)
            translated_cells = sum(
                1
                for original, target in zip(texts, translated)
                if str(original).strip() and str(target).strip() and not str(target).startswith("[translation_error]")
            )
            stats = {"translated_cells": translated_cells, "total_rows": len(input_df)}
        else:
            stats = bridge.get_llm_excel_processor().translate_excel_file(
                input_file_path=str(input_path),
                output_file_path=str(output_path),
                source_lang=source_language,
                target_lang=resolved_target_language,
                translation_mode=resolved_translation_mode,
            )
        _write_task_meta(t.task_dir, {
            "task_id": t.task_id,
            "original_filename": input_path.name,
            "normalized_dxf_filename": None,
            "text_count": stats.get("translated_cells", 0),
            "translation_count": stats.get("translated_cells", 0),
            "excel_filename": output_path.name,
            "translated_cad_filename": None,
            "status": "done",
            "stage": "translate",
            "output_dir": str(t.product_dir),
            "output_file": str(output_path),
        })
        return {
            "success": True,
            "task_id": t.task_id,
            "task_dir": str(t.task_dir),
            "output_dir": str(t.product_dir),
            "input_file": str(input_path),
            "output_file": str(output_path),
            "target_language": resolved_target_language,
            "translation_mode": resolved_translation_mode,
            "translated_cells": stats.get("translated_cells", 0),
        }
