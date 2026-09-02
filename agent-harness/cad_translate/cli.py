#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``cad-translate`` click command line interface.

This is the single supported package entry for the CLI.  All commands are thin
facades that delegate the actual work to :mod:`cad_translate.operations` /
:mod:`cad_translate.store`, which in turn reuse the backend's trusted
implementation (``backend/app``).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click
import structlog

from . import bridge, operations, store
from .bridge import get_settings
from .operations import (
    run_apply,
    run_convert,
    run_extract,
    run_translate_excel,
)
from .store import (
    clear_tasks,
    delete_task,
    list_tasks,
    load_project_file,
    load_task,
    save_task,
    write_project_file,
)


# ---------------------------------------------------------------------------
# Session (per-invocation mutable project state)
# ---------------------------------------------------------------------------
class _Session:
    project_path: str | None = None
    project_data: dict[str, Any] | None = None
    recent_task_id: str | None = None
    active_input_file: str | None = None
    _modified: bool = False

    def mark_modified(self) -> None:
        self._modified = True

    def mark_saved(self) -> None:
        self._modified = False

    def is_modified(self) -> bool:
        return self._modified

    def set_project(self, data: dict[str, Any], project_path: str | None = None) -> None:
        self.project_data = data
        self.project_path = project_path
        self.mark_saved()

    def get_status(self) -> dict[str, Any]:
        return {
            "project_path": self.project_path,
            "project_name": (self.project_data or {}).get("name"),
            "recent_task_id": self.recent_task_id,
            "active_input_file": self.active_input_file,
            "modified": self._modified,
        }


_session = _Session()


def _safe_console_text(value: Any) -> str:
    text = str(value)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def emit(data: Any, message: str = "") -> None:
    json_mode = _session_json_output.get()
    if json_mode:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return
    if message:
        click.echo(_safe_console_text(message))
    if isinstance(data, dict):
        for key, value in data.items():
            click.echo(_safe_console_text(f"{key}: {value}"))
    elif isinstance(data, list):
        for item in data:
            click.echo(_safe_console_text(item))
    elif data is not None:
        click.echo(_safe_console_text(data))


def _error_payload(error_type: str, message: str) -> dict[str, Any]:
    return {"success": False, "error_type": error_type, "message": message}


def _coerce_config_value(raw: str) -> Any:
    text = str(raw).strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        lowered = text.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered == "null":
            return None
        return raw


# ---------------------------------------------------------------------------
# Error handling decorator
# ---------------------------------------------------------------------------
def handle_error(func):
    """Catch expected errors and emit a structured result instead of a traceback."""

    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except click.ClickException:
            raise
        except (FileNotFoundError, ValueError, RuntimeError, OSError) as exc:
            if _session_json_output.get():
                click.echo(json.dumps(_error_payload(exc.__class__.__name__, str(exc)), ensure_ascii=False))
            else:
                click.echo(click.style(f"error: {exc}", fg="red"), err=True)
            raise SystemExit(1) from exc

    wrapper.__name__ = func.__name__
    return wrapper


# A contextvar-free simple flag (module global) for JSON mode.
class _JsonFlag:
    def __init__(self) -> None:
        self._value = False

    def set(self, value: bool) -> None:
        self._value = value

    def get(self) -> bool:
        return self._value


_session_json_output = _JsonFlag()


# ---------------------------------------------------------------------------
# Top-level command group
# ---------------------------------------------------------------------------
def _create_project_data(name: str) -> dict[str, Any]:
    cad_defaults = bridge.get_runtime_config_service().get_cad_defaults_summary()
    return {
        "name": name,
        "status": "idle",
        "source_files": [],
        "default_output_dir": cad_defaults.get("default_output_dir", ""),
        "target_language": cad_defaults.get("target_language", "en"),
        "converter_backend": cad_defaults.get("converter_backend", "auto"),
        "font_name": cad_defaults.get("font_name", "Times New Roman"),
        "font_size_reduction": cad_defaults.get("font_size_reduction", 2),
        "translation_mode": cad_defaults.get("translation_mode", "replace"),
        "recent_task_id": None,
        "recent_excel_file": None,
    }


def _scan_cad_files(path: str) -> dict[str, Any]:
    directory = Path(path).expanduser().resolve()
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")
    dwg_files = sorted(p.name for p in directory.glob("*.dwg"))
    dxf_files = sorted(p.name for p in directory.glob("*.dxf"))
    xlsx_files = sorted(p.name for p in directory.glob("*.xlsx"))
    return {
        "directory": str(directory),
        "dwg_files": dwg_files,
        "dxf_files": dxf_files,
        "xlsx_files": xlsx_files,
        "total_dwg": len(dwg_files),
        "total_dxf": len(dxf_files),
        "total_xlsx": len(xlsx_files),
    }


CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


@click.group(invoke_without_command=True, context_settings=CONTEXT_SETTINGS)
@click.option("--json", "json_mode", is_flag=True, help="Output as JSON.")
@click.option("--project", "project_path", type=click.Path(), default=None, help="Project file path.")
@click.version_option(version=bridge.get_version(), prog_name="cad-translate")
@click.pass_context
def cli(ctx: click.Context, json_mode: bool, project_path: str | None) -> None:
    """CAD drawing translation CLI (shares the backend trusted implementation)."""
    _session_json_output.set(bool(json_mode))
    if project_path:
        _session.set_project(load_project_file(project_path), project_path)
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ---------------------------------------------------------------------------
# project
# ---------------------------------------------------------------------------
@cli.group("project")
def project_group() -> None:
    """Project commands."""


@project_group.command("new")
@click.option("--name", default="untitled", help="Project name.")
@click.option("--output", "-o", type=click.Path(), default=None, help="Optional project file path.")
@handle_error
def project_new(name: str, output: str | None) -> None:
    data = _create_project_data(name)
    _session.set_project(data, output)
    if output:
        emit(write_project_file(data, output), f"Created project: {name}")
        return
    emit({"success": True, "project": name, "data": data}, f"Created project: {name}")


@project_group.command("open")
@click.argument("project_path", type=click.Path(exists=True))
@handle_error
def project_open(project_path: str) -> None:
    data = load_project_file(project_path)
    _session.set_project(data, project_path)
    emit({"success": True, "project": data.get("name"), "file": project_path}, f"Opened: {project_path}")


@project_group.command("save")
@click.argument("project_path", required=False, type=click.Path())
@handle_error
def project_save(project_path: str | None) -> None:
    if _session.project_data is None:
        raise ValueError("No active project loaded.")
    target = project_path or _session.project_path
    if not target:
        raise ValueError("No project path specified.")
    result = write_project_file(_session.project_data, target)
    _session.project_path = target
    _session.mark_saved()
    emit(result, f"Saved: {target}")


@project_group.command("info")
@handle_error
def project_info() -> None:
    emit(_session.get_status())


# ---------------------------------------------------------------------------
# files
# ---------------------------------------------------------------------------
@cli.group("files")
def files_group() -> None:
    """File inspection commands."""


@files_group.command("list")
@click.option("--path", default=".", type=click.Path(exists=True), help="Directory to scan.")
@handle_error
def files_list(path: str) -> None:
    emit(_scan_cad_files(path), f"Files in {path}")


@files_group.command("set-input")
@click.argument("input_file", type=click.Path(exists=True))
@handle_error
def files_set_input(input_file: str) -> None:
    _session.active_input_file = str(Path(input_file).expanduser().resolve())
    _session.mark_modified()
    emit({"success": True, "input_file": _session.active_input_file}, "Active input updated")


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------
@cli.group("pipeline")
def pipeline_group() -> None:
    """CAD pipeline commands."""


@pipeline_group.command("extract")
@click.option("--input", "input_file", "-i", type=click.Path(exists=True), required=True)
@click.option("--output-dir", "-o", type=click.Path(), default=None)
@handle_error
def pipeline_extract(input_file: str, output_dir: str | None) -> None:
    result = run_extract(input_file=input_file, output_dir=output_dir)
    _session.recent_task_id = result["task_id"]
    emit(result, f"Extracted text from {input_file}")


@pipeline_group.command("convert")
@click.option("--input", "input_file", "-i", type=click.Path(exists=True), required=True)
@click.option("--output-dir", "-o", type=click.Path(), default=None)
@click.option("--backend", type=str, default=None, help="Optional backend override.")
@handle_error
def pipeline_convert(input_file: str, output_dir: str | None, backend: str | None) -> None:
    result = run_convert(input_file=input_file, output_dir=output_dir, backend_override=backend)
    _session.recent_task_id = result["task_id"]
    emit(result, f"Converted {input_file}")


@pipeline_group.command("apply")
@click.option("--input", "input_file", "-i", type=click.Path(exists=True), required=True)
@click.option("--excel", "excel_file", "-e", type=click.Path(exists=True), required=True)
@click.option("--output-dir", "-o", type=click.Path(), default=None)
@click.option("--translation-mode", type=click.Choice(["add", "replace"], case_sensitive=False), default=None)
@click.option("--font-name", type=str, default=None)
@click.option("--font-size-reduction", type=int, default=None)
@handle_error
def pipeline_apply(
    input_file: str,
    excel_file: str,
    output_dir: str | None,
    translation_mode: str | None,
    font_name: str | None,
    font_size_reduction: int | None,
) -> None:
    result = run_apply(
        input_file=input_file,
        excel_file=excel_file,
        output_dir=output_dir,
        translation_mode=translation_mode,
        font_name=font_name,
        font_size_reduction=font_size_reduction,
    )
    _session.recent_task_id = result["task_id"]
    emit(result, f"Applied translations to {input_file}")


@pipeline_group.command("translate-excel")
@click.option("--input", "input_file", "-i", type=click.Path(exists=True), required=True)
@click.option("--output-dir", "-o", type=click.Path(), default=None)
@click.option("--source-language", type=str, default="auto")
@click.option("--target-language", type=str, default=None)
@click.option("--translation-mode", type=click.Choice(["add", "replace"], case_sensitive=False), default=None)
@handle_error
def pipeline_translate_excel(
    input_file: str,
    output_dir: str | None,
    source_language: str,
    target_language: str | None,
    translation_mode: str | None,
) -> None:
    result = run_translate_excel(
        input_file=input_file,
        output_dir=output_dir,
        source_language=source_language,
        target_language=target_language,
        translation_mode=translation_mode,
    )
    _session.recent_task_id = result["task_id"]
    emit(result, f"Translated Excel file {input_file}")


# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------
@cli.group("tasks")
def tasks_group() -> None:
    """Task management commands."""


@tasks_group.command("list")
@handle_error
def tasks_list() -> None:
    emit({"tasks": list_tasks()})


@tasks_group.command("show")
@click.argument("task_id")
@handle_error
def tasks_show(task_id: str) -> None:
    emit(load_task(task_id))


@tasks_group.command("delete")
@click.argument("task_id")
@handle_error
def tasks_delete(task_id: str) -> None:
    delete_task(task_id)
    emit({"success": True, "task_id": task_id}, f"Deleted task {task_id}")


@tasks_group.command("clear")
@handle_error
def tasks_clear() -> None:
    clear_tasks()
    emit({"success": True}, "Cleared all tasks")


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------
@cli.group("config")
def config_group() -> None:
    """Configuration commands."""


@config_group.command("show")
@handle_error
def config_show() -> None:
    settings = get_settings()
    runtime_service = bridge.get_runtime_config_service()
    cad_defaults = runtime_service.get_cad_defaults_summary()
    effective = runtime_service.get_effective_config_summary()
    emit(
        {
            "project_path": _session.project_path,
            "recent_task_id": _session.recent_task_id,
            "active_input_file": _session.active_input_file,
            "dwg_converter_backend": settings.DWG_CONVERTER_BACKEND,
            "dwg_auto_backends": settings.DWG_AUTO_BACKENDS,
            "dwg_disabled_backends": settings.DWG_DISABLED_BACKENDS,
            "target_language": cad_defaults.get("target_language"),
            "translation_mode": cad_defaults.get("translation_mode"),
            "font_name": cad_defaults.get("font_name"),
            "font_size_reduction": cad_defaults.get("font_size_reduction"),
            "default_output_dir": cad_defaults.get("default_output_dir"),
            "config_file": cad_defaults.get("config_file"),
            "global_config": effective.get("paths", {}).get("global_config"),
            "project_config": effective.get("paths", {}).get("project_config"),
            "sources": effective.get("sources", {}),
        }
    )


@config_group.command("get")
@click.argument("config_path", type=str)
@handle_error
def config_get(config_path: str) -> None:
    emit(bridge.get_runtime_config_service().get_config_value(config_path))


@config_group.command("set")
@click.argument("config_path", required=False, type=str)
@click.argument("config_value", required=False, type=str)
@click.option("--target-language", type=str, default=None)
@click.option("--translation-mode", type=click.Choice(["add", "replace"], case_sensitive=False), default=None)
@click.option("--font-name", type=str, default=None)
@click.option("--font-size-reduction", type=int, default=None)
@click.option("--default-output-dir", type=click.Path(), default=None)
@click.option("--converter-backend", type=str, default=None)
@handle_error
def config_set(
    config_path: str | None,
    config_value: str | None,
    target_language: str | None,
    translation_mode: str | None,
    font_name: str | None,
    font_size_reduction: int | None,
    default_output_dir: str | None,
    converter_backend: str | None,
) -> None:
    if config_path is not None:
        if any(
            option is not None
            for option in [
                target_language,
                translation_mode,
                font_name,
                font_size_reduction,
                default_output_dir,
                converter_backend,
            ]
        ):
            raise ValueError("Use either path/value arguments or explicit --options, not both.")
        if config_value is None:
            raise ValueError("config value is required when using a config path.")
        emit(
            bridge.get_runtime_config_service().set_config_value(config_path, _coerce_config_value(config_value)),
            "Config value saved",
        )
        return

    payload: dict[str, Any] = {}
    if target_language is not None:
        payload["target_language"] = target_language
    if translation_mode is not None:
        payload["translation_mode"] = translation_mode
    if font_name is not None:
        payload["font_name"] = font_name
    if font_size_reduction is not None:
        payload["font_size_reduction"] = font_size_reduction
    if default_output_dir is not None:
        payload["default_output_dir"] = default_output_dir
    if converter_backend is not None:
        payload["converter_backend"] = converter_backend
    if not payload:
        raise ValueError("At least one config option is required.")
    emit(bridge.get_runtime_config_service().update_cad_defaults(payload), "CAD runtime defaults saved")


@config_group.command("validate")
@handle_error
def config_validate() -> None:
    emit(bridge.get_runtime_config_service().validate_effective_config())


# ---------------------------------------------------------------------------
# config llm
# ---------------------------------------------------------------------------
@config_group.group("llm")
def config_llm_group() -> None:
    """LLM runtime setup commands."""


@config_llm_group.command("show")
@handle_error
def config_llm_show() -> None:
    emit(bridge.get_runtime_config_service().get_public_runtime_summary())


def _build_llm_payload(
    api_format: str | None,
    provider: str | None,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    system_prompt_mode: str | None,
    custom_system_prompt: str | None,
    glossary_file: str | None,
    reasoning_enabled: bool | None,
    timeout_seconds: int | None,
    temperature: float | None,
    max_tokens: int | None,
    batch_size: int | None,
    batch_json: bool | None,
    fallback_format: str | None,
    fallback_provider: str | None,
    fallback_model: str | None,
    fallback_api_key: str | None,
    fallback_base_url: str | None,
    fallback_reasoning_enabled: bool | None,
) -> dict[str, Any]:
    runtime_service = bridge.get_runtime_config_service()
    current = runtime_service.get_public_runtime_summary()
    payload: dict[str, Any] = {}
    if api_format:
        payload["format"] = api_format.strip().lower()
    if provider:
        payload["provider"] = provider.strip().lower()
    if model:
        payload["model"] = model.strip()
    if api_key:
        payload["api_key"] = api_key.strip()
    if base_url:
        payload["base_url"] = base_url.strip()
    if system_prompt_mode:
        payload["system_prompt_mode"] = system_prompt_mode.strip().lower()
    if custom_system_prompt:
        payload["custom_system_prompt"] = custom_system_prompt.strip()
    if glossary_file:
        payload["glossary_file"] = glossary_file.strip()
    if reasoning_enabled is not None:
        payload["reasoning_enabled"] = reasoning_enabled
    if timeout_seconds is not None:
        payload["timeout_seconds"] = timeout_seconds
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if batch_size is not None:
        payload["batch_size"] = batch_size
    if batch_json is not None:
        payload["batch_json"] = batch_json
    if any(
        value is not None and str(value).strip()
        for value in (fallback_format, fallback_provider, fallback_model, fallback_api_key, fallback_base_url)
    ) or fallback_reasoning_enabled is not None:
        fallback_entry: dict[str, Any] = {}
        if fallback_format:
            fallback_entry["format"] = fallback_format.strip().lower()
        if fallback_provider:
            fallback_entry["provider"] = fallback_provider.strip().lower()
        if fallback_model:
            fallback_entry["model"] = fallback_model.strip()
        if fallback_api_key:
            fallback_entry["api_key"] = fallback_api_key.strip()
        if fallback_base_url:
            fallback_entry["base_url"] = fallback_base_url.strip()
        if fallback_reasoning_enabled is not None:
            fallback_entry["reasoning_enabled"] = fallback_reasoning_enabled
        if not fallback_entry.get("provider"):
            raise ValueError("fallback_provider is required when fallback model options are provided")
        payload["fallback_models"] = [fallback_entry]
    return payload


@config_llm_group.command("test")
@click.option("--format", "api_format", type=str, default=None)
@click.option("--provider", type=str, default=None)
@click.option("--model", type=str, default=None)
@click.option("--api-key", type=str, default=None)
@click.option("--base-url", type=str, default=None)
@click.option("--system-prompt-mode", type=str, default=None)
@click.option("--custom-system-prompt", type=str, default=None)
@click.option("--glossary-file", type=str, default=None)
@click.option("--reasoning-enabled/--no-reasoning-enabled", default=None)
@click.option("--timeout-seconds", type=int, default=None)
@handle_error
def config_llm_test(
    api_format: str | None,
    provider: str | None,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    system_prompt_mode: str | None,
    custom_system_prompt: str | None,
    glossary_file: str | None,
    reasoning_enabled: bool | None,
    timeout_seconds: int | None,
) -> None:
    payload = _build_llm_payload(
        api_format=api_format,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        system_prompt_mode=system_prompt_mode,
        custom_system_prompt=custom_system_prompt,
        glossary_file=glossary_file,
        reasoning_enabled=reasoning_enabled,
        timeout_seconds=timeout_seconds,
        temperature=None,
        max_tokens=None,
        batch_size=None,
        batch_json=None,
        fallback_format=None,
        fallback_provider=None,
        fallback_model=None,
        fallback_api_key=None,
        fallback_base_url=None,
        fallback_reasoning_enabled=None,
    )
    emit(bridge.get_runtime_config_service().test_connection(payload), "LLM connection test completed")


@config_llm_group.command("init")
@click.option("--format", "api_format", type=str, default=None)
@click.option("--provider", type=str, default=None)
@click.option("--model", type=str, default=None)
@click.option("--api-key", type=str, default=None)
@click.option("--base-url", type=str, default=None)
@click.option("--system-prompt-mode", type=str, default=None)
@click.option("--custom-system-prompt", type=str, default=None)
@click.option("--glossary-file", type=str, default=None)
@click.option("--reasoning-enabled/--no-reasoning-enabled", default=None)
@click.option("--timeout-seconds", type=int, default=None)
@click.option("--temperature", type=float, default=None)
@click.option("--max-tokens", type=int, default=None)
@click.option("--batch-size", type=int, default=None)
@click.option("--batch-json/--no-batch-json", default=None)
@click.option("--non-interactive", is_flag=True, help="Do not prompt for missing values.")
@handle_error
def config_llm_init(
    api_format: str | None,
    provider: str | None,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    system_prompt_mode: str | None,
    custom_system_prompt: str | None,
    glossary_file: str | None,
    reasoning_enabled: bool | None,
    timeout_seconds: int | None,
    temperature: float | None,
    max_tokens: int | None,
    batch_size: int | None,
    batch_json: bool | None,
    non_interactive: bool,
) -> None:
    if not non_interactive:
        # Interactive prompts for the most important values only.
        if not base_url:
            base_url = click.prompt("LLM base URL")
        if not model:
            model = click.prompt("Model name")
    payload = _build_llm_payload(
        api_format=api_format,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        system_prompt_mode=system_prompt_mode,
        custom_system_prompt=custom_system_prompt,
        glossary_file=glossary_file,
        reasoning_enabled=reasoning_enabled,
        timeout_seconds=timeout_seconds,
        temperature=temperature,
        max_tokens=max_tokens,
        batch_size=batch_size,
        batch_json=batch_json,
        fallback_format=None,
        fallback_provider=None,
        fallback_model=None,
        fallback_api_key=None,
        fallback_base_url=None,
        fallback_reasoning_enabled=None,
    )
    runtime_service = bridge.get_runtime_config_service()
    test_result = runtime_service.test_connection(payload)
    if not test_result.get("success"):
        raise ValueError(test_result.get("message") or "LLM connection test failed")
    emit(runtime_service.update_runtime_config(payload), "LLM runtime config saved")


# ---------------------------------------------------------------------------
# version / env sanity
# ---------------------------------------------------------------------------
@cli.command("doctor")
@handle_error
def doctor() -> None:
    """Show environment sanity check (CAD backend availability, config paths)."""
    settings = get_settings()
    payload: dict[str, Any] = {
        "version": bridge.get_version(),
        "backend_dir": str(bridge.find_backend_dir()),
        "output_dir": str(settings.get_output_path()),
        "env_file": str(settings.get_env_file_path()),
        "runtime_config_file": str(settings.get_runtime_config_path()),
        "dwg_converter_backend": settings.DWG_CONVERTER_BACKEND,
    }
    try:
        runtime_service = bridge.get_runtime_config_service()
        payload["llm_configured"] = bool(runtime_service.get_public_runtime_summary().get("provider"))
    except Exception as exc:  # noqa: BLE001
        payload["llm_configured"] = False
        payload["llm_error"] = str(exc)
    emit(payload, "Environment check complete")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
