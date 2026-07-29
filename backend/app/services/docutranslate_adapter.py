from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Protocol, Sequence


DEFAULT_JSON_PATHS = ("$.records[*].source_text",)


class DocuTranslateAdapterError(RuntimeError):
    """Base error for the CAD -> DocuTranslate adapter."""


class DocuTranslateDependencyError(DocuTranslateAdapterError):
    """Raised when the local DocuTranslate source tree cannot be loaded."""


@dataclass(frozen=True)
class CadTextRecord:
    record_id: str
    source_text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CadTranslatedRecord:
    record_id: str
    source_text: str
    translated_text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocuTranslateConfig:
    source_root: Path
    base_url: str
    api_key: str
    model_id: str
    to_lang: str
    concurrent: int = 1
    timeout: int = 60
    retry: int = 2
    force_json: bool = True
    provider: str | None = None
    custom_prompt: str | None = None
    extra_body: str | None = None
    system_proxy_enable: bool = False
    temperature: float | None = None
    top_p: float | None = None

    @classmethod
    def from_runtime(
        cls,
        runtime: dict[str, Any],
        *,
        source_root: str | Path,
        to_lang: str,
    ) -> "DocuTranslateConfig":
        return cls(
            source_root=Path(source_root),
            base_url=str(runtime.get("base_url") or "").rstrip("/"),
            api_key=str(runtime.get("api_key") or ""),
            model_id=str(runtime.get("model") or runtime.get("model_id") or ""),
            to_lang=to_lang,
            concurrent=max(1, int(runtime.get("parallel_count") or 1)),
            timeout=max(1, int(runtime.get("timeout") or runtime.get("timeout_seconds") or 60)),
            retry=max(0, int(runtime.get("retry_count") or runtime.get("retry") or 2)),
            force_json=bool(runtime.get("force_json", True)),
            provider=str(runtime.get("provider") or "").strip() or None,
            custom_prompt=str(runtime.get("custom_system_prompt") or "").strip() or None,
            extra_body=str(runtime.get("extra_body") or "").strip() or None,
            system_proxy_enable=bool(runtime.get("use_system_proxy", False)),
            temperature=float(runtime["temperature"]) if runtime.get("temperature") is not None else None,
            top_p=float(runtime["top_p"]) if runtime.get("top_p") is not None else None,
        )


@dataclass
class CadTranslationBatchResult:
    records: list[CadTranslatedRecord]
    input_json_path: Path
    translated_json_path: Path
    input_payload: dict[str, Any]
    translated_payload: dict[str, Any]

    @property
    def backfill_rows(self) -> list[dict[str, str]]:
        return [
            {
                "record_id": record.record_id,
                "source_text": record.source_text,
                "translated_text": record.translated_text,
            }
            for record in self.records
        ]


class DocuTranslateWorkflowRunner(Protocol):
    def translate_json_file(
        self,
        *,
        input_path: Path,
        output_dir: Path,
        output_name: str,
        json_paths: Sequence[str],
        config: DocuTranslateConfig,
    ) -> Path:
        ...


@contextmanager
def _prepend_sys_path(path: Path) -> Iterator[None]:
    resolved = str(path.resolve())
    inserted = False
    if resolved not in sys.path:
        sys.path.insert(0, resolved)
        inserted = True
    try:
        yield
    finally:
        if inserted:
            try:
                sys.path.remove(resolved)
            except ValueError:
                pass


class DirectJsonWorkflowRunner:
    """Load DocuTranslate's JSON workflow directly from the source tree."""

    def _load_workflow_types(self, source_root: Path) -> tuple[type[Any], type[Any], type[Any], type[Any]]:
        if not source_root.exists():
            raise DocuTranslateDependencyError(f"DocuTranslate source root does not exist: {source_root}")

        try:
            with _prepend_sys_path(source_root):
                from docutranslate.exporter.js.json2html_exporter import Json2HTMLExporterConfig
                from docutranslate.translator.ai_translator.json_translator import JsonTranslatorConfig
                from docutranslate.workflow.json_workflow import JsonWorkflow, JsonWorkflowConfig
        except ModuleNotFoundError as exc:
            missing = exc.name or "unknown"
            raise DocuTranslateDependencyError(
                f"DocuTranslate JSON workflow dependency is missing: {missing}"
            ) from exc
        except Exception as exc:
            raise DocuTranslateDependencyError(
                f"Failed to load DocuTranslate JSON workflow from {source_root}: {exc}"
            ) from exc

        return JsonWorkflow, JsonWorkflowConfig, JsonTranslatorConfig, Json2HTMLExporterConfig

    def translate_json_file(
        self,
        *,
        input_path: Path,
        output_dir: Path,
        output_name: str,
        json_paths: Sequence[str],
        config: DocuTranslateConfig,
    ) -> Path:
        JsonWorkflow, JsonWorkflowConfig, JsonTranslatorConfig, Json2HTMLExporterConfig = self._load_workflow_types(
            config.source_root
        )

        translator_kwargs: dict[str, Any] = {
            "base_url": config.base_url.rstrip("/"),
            "api_key": config.api_key,
            "model_id": config.model_id,
            "to_lang": config.to_lang,
            "json_paths": list(json_paths),
            "concurrent": max(1, int(config.concurrent)),
            "timeout": max(1, int(config.timeout)),
            "retry": max(0, int(config.retry)),
            "system_proxy_enable": bool(config.system_proxy_enable),
            "force_json": bool(config.force_json),
        }
        if config.provider:
            translator_kwargs["provider"] = config.provider
        if config.custom_prompt:
            translator_kwargs["custom_prompt"] = config.custom_prompt
        if config.extra_body:
            translator_kwargs["extra_body"] = config.extra_body
        if config.temperature is not None:
            translator_kwargs["temperature"] = config.temperature
        if config.top_p is not None:
            translator_kwargs["top_p"] = config.top_p

        translator_config = JsonTranslatorConfig(**translator_kwargs)
        workflow_config = JsonWorkflowConfig(
            translator_config=translator_config,
            html_exporter_config=Json2HTMLExporterConfig(cdn=True),
        )
        workflow = JsonWorkflow(config=workflow_config)
        workflow.read_path(str(input_path))
        workflow.translate()

        output_dir.mkdir(parents=True, exist_ok=True)
        workflow.save_as_json(name=output_name, output_dir=output_dir)
        return output_dir / output_name


class DocuTranslateJsonAdapter:
    def __init__(
        self,
        *,
        config: DocuTranslateConfig,
        runner: DocuTranslateWorkflowRunner | None = None,
        json_paths: Sequence[str] = DEFAULT_JSON_PATHS,
    ) -> None:
        self.config = config
        self.runner = runner or DirectJsonWorkflowRunner()
        self.json_paths = tuple(json_paths) or DEFAULT_JSON_PATHS

    def build_payload(self, records: Iterable[CadTextRecord]) -> dict[str, Any]:
        materialized = list(records)
        self._validate_records(materialized)
        return {
            "records": [
                {
                    "record_id": record.record_id,
                    "source_text": record.source_text,
                }
                for record in materialized
            ]
        }

    def translate_records(
        self,
        records: Sequence[CadTextRecord],
        *,
        working_dir: str | Path,
        input_name: str = "cad_records.json",
        output_name: str = "cad_records.translated.json",
    ) -> CadTranslationBatchResult:
        original_records = list(records)
        payload = self.build_payload(original_records)
        working_path = Path(working_dir)
        working_path.mkdir(parents=True, exist_ok=True)

        input_path = working_path / input_name
        input_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        translated_path = self.runner.translate_json_file(
            input_path=input_path,
            output_dir=working_path,
            output_name=output_name,
            json_paths=self.json_paths,
            config=self.config,
        )

        translated_payload = json.loads(translated_path.read_text(encoding="utf-8"))
        translated_records = self.map_translated_payload(original_records, translated_payload)
        return CadTranslationBatchResult(
            records=translated_records,
            input_json_path=input_path,
            translated_json_path=translated_path,
            input_payload=payload,
            translated_payload=translated_payload,
        )

    def map_translated_payload(
        self,
        original_records: Sequence[CadTextRecord],
        translated_payload: dict[str, Any],
    ) -> list[CadTranslatedRecord]:
        translated_items = translated_payload.get("records")
        if not isinstance(translated_items, list):
            raise DocuTranslateAdapterError("DocuTranslate translated payload is missing a 'records' list")

        translated_by_id: dict[str, dict[str, Any]] = {}
        for item in translated_items:
            if not isinstance(item, dict):
                raise DocuTranslateAdapterError("DocuTranslate translated payload contains a non-object record")
            record_id = str(item.get("record_id") or "")
            if not record_id:
                raise DocuTranslateAdapterError("DocuTranslate translated payload contains a record without record_id")
            translated_by_id[record_id] = item

        results: list[CadTranslatedRecord] = []
        for original in original_records:
            translated_item = translated_by_id.get(original.record_id)
            if translated_item is None:
                raise DocuTranslateAdapterError(
                    f"DocuTranslate translated payload is missing record_id={original.record_id}"
                )
            translated_text = translated_item.get("source_text")
            if not isinstance(translated_text, str):
                raise DocuTranslateAdapterError(
                    f"DocuTranslate translated payload has no translated source_text for record_id={original.record_id}"
                )
            results.append(
                CadTranslatedRecord(
                    record_id=original.record_id,
                    source_text=original.source_text,
                    translated_text=translated_text,
                    metadata=dict(original.metadata),
                )
            )
        return results

    @staticmethod
    def _validate_records(records: Sequence[CadTextRecord]) -> None:
        seen_ids: set[str] = set()
        for record in records:
            if not record.record_id:
                raise DocuTranslateAdapterError("CAD record_id must not be empty")
            if record.record_id in seen_ids:
                raise DocuTranslateAdapterError(f"Duplicate CAD record_id detected: {record.record_id}")
            seen_ids.add(record.record_id)
            if not isinstance(record.source_text, str):
                raise DocuTranslateAdapterError(
                    f"CAD source_text must be a string for record_id={record.record_id}"
                )
