"""Provider presets and concurrency-safe custom-provider persistence."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import structlog

from app.config import get_settings
from app.utils.locking import atomic_write_json, file_lock

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    name: str
    api_format: str
    base_url: str
    default_model: str
    api_key_env: str
    notes: str
    free_tier_hint: bool = False


def _preset(
    provider_id: str,
    name: str,
    api_format: str,
    base_url: str,
    model: str,
    key_env: str,
    notes: str,
    free: bool = False,
) -> ProviderPreset:
    return ProviderPreset(
        provider_id, name, api_format, base_url, model, key_env, notes, free
    )


_BUILTINS: dict[str, ProviderPreset] = {
    "openai": _preset("openai", "OpenAI", "openai_compatible", "https://api.openai.com/v1", "gpt-4.1-mini", "OPENAI_API_KEY", "Official OpenAI endpoint"),
    "openrouter": _preset("openrouter", "OpenRouter", "openai_compatible", "https://openrouter.ai/api/v1", "stepfun/step-3.5-flash:free", "OPENROUTER_API_KEY", "Multi-vendor gateway, often has free/community models", True),
    "nvidia": _preset("nvidia", "NVIDIA API Catalog", "openai_compatible", "https://integrate.api.nvidia.com/v1", "moonshotai/kimi-k2.5", "NVIDIA_API_KEY", "Direct NVIDIA chat completions endpoint"),
    "dashscope": _preset("dashscope", "Alibaba DashScope", "openai_compatible", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-max", "LLM_API_KEY", "Qwen models via OpenAI-compatible endpoint"),
    "deepseek": _preset("deepseek", "DeepSeek", "openai_compatible", "https://api.deepseek.com/v1", "deepseek-chat", "DEEPSEEK_API_KEY", "DeepSeek official endpoint"),
    "groq": _preset("groq", "Groq", "openai_compatible", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "GROQ_API_KEY", "High-speed inference, some free tier quotas", True),
    "minimax": _preset("minimax", "MiniMax", "openai_compatible", "https://api.minimax.chat/v1", "MiniMax-Text-01", "MINIMAX_API_KEY", "MiniMax open platform"),
    "minimax-cn": _preset("minimax-cn", "MiniMax 国内版", "openai_compatible", "https://api.minimaxi.com/v1", "MiniMax-M2.5", "MINIMAX_API_KEY", "MiniMax 中国国内官方端点"),
    "zhipu": _preset("zhipu", "Zhipu GLM", "openai_compatible", "https://open.bigmodel.cn/api/paas/v4", "glm-4-plus", "ZHIPU_API_KEY", "GLM models"),
    "moonshot": _preset("moonshot", "Moonshot", "openai_compatible", "https://api.moonshot.cn/v1", "moonshot-v1-8k", "MOONSHOT_API_KEY", "Kimi models"),
    "siliconflow": _preset("siliconflow", "SiliconFlow", "openai_compatible", "https://api.siliconflow.cn/v1", "Qwen/Qwen2.5-7B-Instruct", "SILICONFLOW_API_KEY", "Open-model hosting provider", True),
    "together": _preset("together", "Together AI", "openai_compatible", "https://api.together.xyz/v1", "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo", "TOGETHER_API_KEY", "Open-model inference provider"),
    "anthropic": _preset("anthropic", "Anthropic", "anthropic", "https://api.anthropic.com/v1", "claude-3-5-haiku-latest", "ANTHROPIC_API_KEY", "Claude Messages API"),
    "google": _preset("google", "Google Gemini", "google", "https://generativelanguage.googleapis.com/v1beta", "gemini-2.0-flash", "GOOGLE_API_KEY", "Gemini API / AI Studio"),
    "ollama": _preset("ollama", "Ollama", "ollama", "http://127.0.0.1:11434", "qwen2.5:7b", "OLLAMA_API_KEY", "Local Ollama server", True),
    "lmstudio": _preset("lmstudio", "LM Studio", "lmstudio", "http://127.0.0.1:1234/v1", "local-model", "LMSTUDIO_API_KEY", "Local LM Studio OpenAI-compatible server", True),
    "custom": _preset("custom", "Custom OpenAI-Compatible", "openai_compatible", "https://your-endpoint/v1", "your-model", "LLM_API_KEY", "Bring your own OpenAI-compatible endpoint"),
}

BUILTIN_PROVIDER_IDS = frozenset(_BUILTINS)
SUPPORTED_API_FORMATS = frozenset(
    {"openai_compatible", "anthropic", "google", "ollama", "lmstudio"}
)
PROVIDER_PRESETS: dict[str, ProviderPreset] = dict(_BUILTINS)
_registry_lock = threading.RLock()


def _custom_path() -> Path:
    return get_settings().get_runtime_config_path().parent / "custom_providers.json"


def _normalized_slug(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", folded.casefold()).strip("-")


def normalize_provider_id(
    provider_id: str | None, *, name: str, base_url: str
) -> str:
    """Return a stable ASCII ID, including for names written only in Unicode."""
    slug = _normalized_slug(provider_id or name)
    if slug:
        return slug
    digest = hashlib.sha256(f"{name}\0{base_url}".encode("utf-8")).hexdigest()[:12]
    return f"custom-{digest}"


def _deserialize_customs(raw: Any) -> dict[str, ProviderPreset]:
    if not isinstance(raw, dict):
        raise ValueError("custom provider file must contain a JSON object")
    customs: dict[str, ProviderPreset] = {}
    for raw_id, data in raw.items():
        if not isinstance(data, dict):
            raise ValueError(f"custom provider {raw_id!r} must be an object")
        provider_id = normalize_provider_id(
            str(raw_id), name=str(data.get("name") or raw_id), base_url=str(data.get("base_url") or "")
        )
        if provider_id in BUILTIN_PROVIDER_IDS:
            logger.warning("custom_provider_builtin_collision_ignored", provider=provider_id)
            continue
        api_format = str(data.get("api_format") or "openai_compatible").strip().lower()
        if api_format not in SUPPORTED_API_FORMATS:
            logger.warning("custom_provider_invalid_format_ignored", provider=provider_id, api_format=api_format)
            continue
        customs[provider_id] = ProviderPreset(
            id=provider_id,
            name=str(data.get("name") or provider_id).strip(),
            api_format=api_format,
            base_url=str(data.get("base_url") or "").strip().rstrip("/"),
            default_model=str(data.get("default_model") or "").strip(),
            api_key_env="LLM_API_KEY",
            notes=str(data.get("notes") or "Custom provider").strip(),
        )
    return customs


def _read_customs(path: Path) -> dict[str, ProviderPreset]:
    if not path.exists():
        return {}
    return _deserialize_customs(json.loads(path.read_text(encoding="utf-8")))


def _replace_customs(customs: dict[str, ProviderPreset]) -> None:
    for provider_id in list(PROVIDER_PRESETS):
        if provider_id not in BUILTIN_PROVIDER_IDS:
            PROVIDER_PRESETS.pop(provider_id, None)
    PROVIDER_PRESETS.update(customs)


def refresh_custom_providers() -> None:
    """Refresh from disk without exposing a partially updated registry."""
    path = _custom_path()
    try:
        with _registry_lock, file_lock(path):
            customs = _read_customs(path)
            _replace_customs(customs)
    except Exception as exc:
        logger.error("failed_to_load_custom_providers", path=str(path), error=str(exc))


def load_custom_providers() -> None:
    refresh_custom_providers()


def _serialize(customs: dict[str, ProviderPreset]) -> dict[str, dict[str, Any]]:
    return {
        provider_id: {
            "name": preset.name,
            "api_format": preset.api_format,
            "base_url": preset.base_url,
            "default_model": preset.default_model,
            "notes": preset.notes,
        }
        for provider_id, preset in customs.items()
    }


def save_custom_providers() -> None:
    path = _custom_path()
    with _registry_lock, file_lock(path):
        disk = _read_customs(path)
        memory = {
            provider_id: preset
            for provider_id, preset in PROVIDER_PRESETS.items()
            if provider_id not in BUILTIN_PROVIDER_IDS
        }
        disk.update(memory)
        atomic_write_json(path, _serialize(disk))
        _replace_customs(disk)


def list_provider_presets() -> list[dict[str, Any]]:
    refresh_custom_providers()
    with _registry_lock:
        return [asdict(preset) for preset in PROVIDER_PRESETS.values()]


def add_custom_provider(
    provider_id: str | None,
    name: str,
    base_url: str,
    default_model: str,
    notes: str = "Custom provider",
    api_format: str | None = None,
) -> dict[str, Any]:
    path = _custom_path()
    normalized_id = normalize_provider_id(provider_id, name=name, base_url=base_url)
    normalized_format = str(api_format or "openai_compatible").strip().lower()
    if normalized_format not in SUPPORTED_API_FORMATS:
        raise ValueError(f"Unsupported LLM format: {normalized_format}")
    preset = ProviderPreset(
        id=normalized_id,
        name=name.strip(),
        api_format=normalized_format,
        base_url=base_url.strip().rstrip("/"),
        default_model=default_model.strip(),
        api_key_env="LLM_API_KEY",
        notes=(notes or "Custom provider").strip(),
    )
    with _registry_lock, file_lock(path):
        customs = _read_customs(path)
        if normalized_id in BUILTIN_PROVIDER_IDS or normalized_id in customs:
            raise ValueError(f"Provider ID already exists: {normalized_id}")
        customs[normalized_id] = preset
        atomic_write_json(path, _serialize(customs))
        _replace_customs(customs)
    return asdict(preset)


def delete_custom_provider(provider_id: str) -> bool:
    path = _custom_path()
    normalized_id = normalize_provider_id(provider_id, name=provider_id, base_url="")
    if normalized_id in BUILTIN_PROVIDER_IDS:
        return False
    with _registry_lock, file_lock(path):
        customs = _read_customs(path)
        if normalized_id not in customs:
            _replace_customs(customs)
            return False
        customs.pop(normalized_id)
        atomic_write_json(path, _serialize(customs))
        _replace_customs(customs)
    return True


load_custom_providers()
