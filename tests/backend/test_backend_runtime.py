from __future__ import annotations

import importlib
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Iterator

import ezdxf
import pytest
from fastapi.testclient import TestClient


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"


def _clear_app_modules() -> None:
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            sys.modules.pop(module_name, None)


def _write_env_file(env_path: Path, db_path: Path) -> None:
    env_path.write_text(
        "\n".join(
            [
                "APP_ENV=test",
                "DEBUG=false",
                f"DATABASE_URL=sqlite:///{db_path.as_posix()}",
                "REDIS_URL=redis://127.0.0.1:6399/0",
                "UPLOAD_DIR=uploads",
                "OUTPUT_DIR=outputs",
                "TEMP_DIR=temp",
                "TRANSLATION_PROVIDER=custom",
                "LLM_BASE_URL=https://example.com/v1",
                "LLM_API_KEY=",
                "LLM_MODEL=baseline-model",
                "LLM_TIMEOUT_SECONDS=33",
                "LLM_TEMPERATURE=0.15",
                "LLM_MAX_TOKENS=2222",
                "LLM_BATCH_SIZE=7",
            ]
        ),
        encoding="utf-8",
    )


@pytest.fixture()
def loaded_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[tuple[ModuleType, TestClient]]:
    env_path = tmp_path / ".env"
    db_path = tmp_path / "runtime.db"
    runtime_config_path = tmp_path / "runtime_config.local.json"
    _write_env_file(env_path, db_path)

    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    monkeypatch.setenv("CAD_TRANSLATION_ENV_FILE", str(env_path))
    monkeypatch.setenv("CAD_TRANSLATION_RUNTIME_CONFIG_FILE", str(runtime_config_path))
    monkeypatch.chdir(ROOT_DIR)
    _clear_app_modules()

    module = importlib.import_module("app.main")
    with TestClient(module.app) as client:
        yield module, client
    _clear_app_modules()


def test_backend_imports_from_repo_root_and_serves_root(loaded_backend: tuple[ModuleType, TestClient]) -> None:
    module, client = loaded_backend

    response = client.get("/")

    assert response.status_code == 200
    assert module.settings.BASE_DIR == BACKEND_DIR

    if module.frontend_index_file.exists():
        assert "text/html" in response.headers["content-type"]
        assert '<div id="root"></div>' in response.text
    else:
        assert response.json()["status"] == "running"


def test_health_uses_local_async_mode_when_redis_is_unavailable(
    loaded_backend: tuple[ModuleType, TestClient],
) -> None:
    _, client = loaded_backend

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["celery"] == "local_eager"


def test_translation_config_can_be_updated_and_read_back(
    loaded_backend: tuple[ModuleType, TestClient],
) -> None:
    _, client = loaded_backend

    update_payload = {
        "provider": "custom",
        "format": "openai_compatible",
        "base_url": "https://gateway.example.com/v1/",
        "api_key": "sk-runtime-secret",
        "model": "qwen-cad",
        "timeout_seconds": 45,
        "temperature": 0.25,
        "max_tokens": 4096,
        "batch_size": 9,
        "batch_json": False,
        "system_prompt_mode": "cad_specialized",
        "glossary_file": str(BACKEND_DIR / "DocuTranslate.csv"),
        "reasoning_enabled": True,
    }

    save_response = client.post("/api/translation/config", json=update_payload)

    assert save_response.status_code == 200

    saved = save_response.json()
    assert saved["runtime"]["provider"] == "custom"
    assert saved["runtime"]["format"] == "openai_compatible"
    assert saved["runtime"]["base_url"] == "https://gateway.example.com/v1"
    assert saved["runtime"]["model"] == "qwen-cad"
    assert saved["runtime"]["api_key_configured"] is True
    assert saved["runtime"]["masked_api_key"].endswith("cret")
    assert saved["runtime"]["batch_json"] is False
    assert saved["runtime"]["system_prompt_mode"] == "cad_specialized"
    assert saved["runtime"]["glossary_configured"] is True
    assert saved["runtime"]["glossary_file"].endswith("DocuTranslate.csv")
    assert saved["runtime"]["reasoning_enabled"] is True

    get_response = client.get("/api/translation/config")

    assert get_response.status_code == 200
    fetched = get_response.json()
    assert fetched["runtime"]["provider"] == "custom"
    assert fetched["runtime"]["format"] == "openai_compatible"
    assert fetched["runtime"]["model"] == "qwen-cad"
    assert fetched["runtime"]["masked_api_key"].endswith("cret")
    assert fetched["runtime"]["batch_json"] is False
    assert fetched["runtime"]["system_prompt_mode"] == "cad_specialized"
    assert fetched["runtime"]["glossary_configured"] is True
    assert fetched["runtime"]["reasoning_enabled"] is True


def test_translation_test_connection_uses_models_endpoint(
    loaded_backend: tuple[ModuleType, TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = loaded_backend
    service_module = importlib.import_module("app.services.runtime_config_service")
    captured: dict[str, str] = {}

    class DummyResponse:
        status_code = 200

        @staticmethod
        def json() -> dict[str, list[dict[str, str]]]:
            return {"data": [{"id": "demo-model"}]}

        text = "ok"

    def fake_get(url: str, headers: dict[str, str], timeout: int) -> DummyResponse:
        captured["url"] = url
        captured["auth"] = headers.get("Authorization", "")
        captured["timeout"] = str(timeout)
        return DummyResponse()

    monkeypatch.setattr(service_module.requests, "get", fake_get)

    response = client.post(
        "/api/translation/test-connection",
        json={
            "provider": "custom",
            "format": "openai_compatible",
            "base_url": "https://gateway.example.com/v1",
            "api_key": "sk-live-secret",
            "model": "demo-model",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["reachable"] is True
    assert body["format"] == "openai_compatible"
    assert captured["url"] == "https://gateway.example.com/v1/models"
    assert captured["auth"] == "Bearer sk-live-secret"


def test_translation_test_connection_supports_ollama_without_api_key(
    loaded_backend: tuple[ModuleType, TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = loaded_backend
    service_module = importlib.import_module("app.services.runtime_config_service")
    captured: dict[str, str] = {}

    class DummyResponse:
        status_code = 200
        text = "ok"

    def fake_get(url: str, headers: dict[str, str], timeout: int) -> DummyResponse:
        captured["url"] = url
        captured["auth"] = headers.get("Authorization", "")
        captured["timeout"] = str(timeout)
        return DummyResponse()

    monkeypatch.setattr(service_module.requests, "get", fake_get)

    response = client.post(
        "/api/translation/test-connection",
        json={
            "provider": "ollama",
            "format": "ollama",
            "base_url": "http://127.0.0.1:11434",
            "model": "qwen2.5:7b",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["format"] == "ollama"
    assert captured["url"] == "http://127.0.0.1:11434/api/tags"
    assert captured["auth"] == ""


def test_openai_provider_uses_provider_specific_env_key(
    loaded_backend: tuple[ModuleType, TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = loaded_backend

    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-secret-1234")

    save_response = client.post(
        "/api/translation/config",
        json={
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "timeout_seconds": 45,
        },
    )

    assert save_response.status_code == 200
    saved = save_response.json()
    assert saved["runtime"]["provider"] == "openai"
    assert saved["runtime"]["api_key_configured"] is True
    assert saved["runtime"]["masked_api_key"].endswith("1234")


def test_openrouter_provider_uses_process_env_key_and_stepfun_default_model(
    loaded_backend: tuple[ModuleType, TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = loaded_backend

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-secret-5678")

    save_response = client.post(
        "/api/translation/config",
        json={
            "provider": "openrouter",
            "timeout_seconds": 45,
        },
    )

    assert save_response.status_code == 200
    saved = save_response.json()
    assert saved["runtime"]["provider"] == "openrouter"
    assert saved["runtime"]["model"] == "stepfun/step-3.5-flash:free"
    assert saved["runtime"]["base_url"] == "https://openrouter.ai/api/v1"
    assert saved["runtime"]["api_key_configured"] is True
    assert saved["runtime"]["masked_api_key"].endswith("5678")


def test_nvidia_provider_uses_provider_specific_env_key_and_kimi_default_model(
    loaded_backend: tuple[ModuleType, TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = loaded_backend

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-demo-secret-1234")

    save_response = client.post(
        "/api/translation/config",
        json={
            "provider": "nvidia",
            "timeout_seconds": 45,
        },
    )

    assert save_response.status_code == 200
    saved = save_response.json()
    assert saved["runtime"]["provider"] == "nvidia"
    assert saved["runtime"]["model"] == "moonshotai/kimi-k2.5"
    assert saved["runtime"]["base_url"] == "https://integrate.api.nvidia.com/v1"
    assert saved["runtime"]["api_key_configured"] is True
    assert saved["runtime"]["masked_api_key"].endswith("1234")


def test_translation_runtime_prefers_global_config_file_and_persists_updates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    db_path = tmp_path / "runtime.db"
    runtime_config_path = tmp_path / "runtime_config.local.json"
    _write_env_file(env_path, db_path)
    runtime_config_path.write_text(
        json.dumps(
            {
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "sk-or-file-secret-4321",
                "model": "stepfun/step-3.5-flash:free",
                "timeout_seconds": 50,
                "temperature": 0.05,
                "max_tokens": 3000,
                "batch_size": 11,
            }
        ),
        encoding="utf-8",
    )

    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    monkeypatch.setenv("CAD_TRANSLATION_ENV_FILE", str(env_path))
    monkeypatch.setenv("CAD_TRANSLATION_RUNTIME_CONFIG_FILE", str(runtime_config_path))
    monkeypatch.chdir(ROOT_DIR)
    _clear_app_modules()

    module = importlib.import_module("app.main")
    with TestClient(module.app) as client:
        get_response = client.get("/api/translation/config")

        assert get_response.status_code == 200
        fetched = get_response.json()
        assert fetched["runtime"]["provider"] == "openrouter"
        assert fetched["runtime"]["model"] == "stepfun/step-3.5-flash:free"
        assert fetched["runtime"]["api_key_configured"] is True
        assert fetched["runtime"]["masked_api_key"].endswith("4321")

        save_response = client.post(
            "/api/translation/config",
            json={
                "provider": "custom",
                "base_url": "https://gateway.example.com/v1",
                "model": "cad-custom",
                "timeout_seconds": 41,
                "temperature": 0.2,
                "max_tokens": 2048,
                "batch_size": 5,
            },
        )

        assert save_response.status_code == 200

    persisted = json.loads(runtime_config_path.read_text(encoding="utf-8"))
    assert persisted["llm"]["primary"]["provider"] == "custom"
    assert persisted["llm"]["primary"]["base_url"] == "https://gateway.example.com/v1"
    assert persisted["llm"]["primary"]["model"] == "cad-custom"
    assert persisted["llm"]["primary"]["api_key"] == "sk-or-file-secret-4321"
    assert persisted["llm"]["batch_size"] == 5
    _clear_app_modules()


def test_cad_defaults_can_be_updated_and_read_back(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    db_path = tmp_path / "runtime.db"
    runtime_config_path = tmp_path / "runtime_config.local.json"
    _write_env_file(env_path, db_path)

    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    monkeypatch.setenv("CAD_TRANSLATION_ENV_FILE", str(env_path))
    monkeypatch.setenv("CAD_TRANSLATION_RUNTIME_CONFIG_FILE", str(runtime_config_path))
    monkeypatch.chdir(ROOT_DIR)
    _clear_app_modules()

    service_module = importlib.import_module("app.services.runtime_config_service")
    service = service_module.RuntimeConfigService()

    updated = service.update_cad_defaults(
        {
            "target_language": "ru",
            "translation_mode": "add",
            "font_name": "Arial",
            "font_size_reduction": 3,
            "default_output_dir": "outputs/custom",
            "converter_backend": "autocad_com",
        }
    )

    assert updated["runtime"]["target_language"] == "ru"
    assert updated["runtime"]["translation_mode"] == "add"
    assert updated["runtime"]["font_name"] == "Arial"
    assert updated["runtime"]["font_size_reduction"] == 3
    assert updated["runtime"]["converter_backend"] == "autocad_com"

    persisted = json.loads(runtime_config_path.read_text(encoding="utf-8"))
    assert persisted["cad"]["target_language"] == "ru"
    assert persisted["cad"]["translation_mode"] == "add"
    assert persisted["cad"]["font_name"] == "Arial"
    assert persisted["cad"]["font_size_reduction"] == 3


def test_config_manager_resolves_precedence_and_deep_merge(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    global_config_dir = tmp_path / ".config" / "cli-anything-cad"
    global_config_path = global_config_dir / "config.json"
    fragment_path = global_config_dir / "llm-fragment.json"
    project_config_path = tmp_path / ".cli-anything-cadrc"

    global_config_dir.mkdir(parents=True, exist_ok=True)
    fragment_path.write_text(
        json.dumps(
            {
                "llm": {
                    "fallback_models": [
                        {
                            "provider": "nvidia",
                            "model": "moonshotai/kimi-k2.5",
                            "base_url": "https://integrate.api.nvidia.com/v1",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    global_config_path.write_text(
        json.dumps(
            {
                "include": [str(fragment_path)],
                "cad": {
                    "target_language": "en",
                    "translation_mode": "replace",
                    "font_name": "Arial",
                },
                "llm": {
                    "primary": {
                        "provider": "openrouter",
                        "model": "stepfun/step-3.5-flash:free",
                        "base_url": "https://openrouter.ai/api/v1",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    project_config_path.write_text(
        json.dumps(
            {
                "cad": {
                    "target_language": "ru",
                },
                "llm": {
                    "primary": {
                        "model": "project-model",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.chdir(tmp_path)
    _clear_app_modules()

    manager_module = importlib.import_module("app.services.config_manager")
    manager = manager_module.ConfigManager(
        cli_overrides={"cad": {"target_language": "ko"}}
    )
    resolved = manager.get_effective_config()

    assert resolved["cad"]["target_language"] == "ko"
    assert resolved["cad"]["translation_mode"] == "replace"
    assert resolved["cad"]["font_name"] == "Arial"
    assert resolved["llm"]["primary"]["model"] == "project-model"
    assert resolved["llm"]["fallback_models"][0]["provider"] == "nvidia"
    assert manager.paths.global_config == global_config_path
    assert manager.paths.project_config == project_config_path


def test_config_manager_rejects_invalid_translation_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    global_config_dir = tmp_path / ".config" / "cli-anything-cad"
    global_config_path = global_config_dir / "config.json"
    global_config_dir.mkdir(parents=True, exist_ok=True)
    global_config_path.write_text(
        json.dumps(
            {
                "cad": {
                    "translation_mode": "append",
                }
            }
        ),
        encoding="utf-8",
    )

    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.chdir(tmp_path)
    _clear_app_modules()

    manager_module = importlib.import_module("app.services.config_manager")
    manager = manager_module.ConfigManager()

    with pytest.raises(ValueError, match="translation_mode"):
        manager.get_effective_config()


def test_config_manager_can_write_project_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    global_config_dir = tmp_path / ".config" / "cli-anything-cad"
    global_config_path = global_config_dir / "config.json"
    project_config_path = tmp_path / ".cli-anything-cadrc"
    global_config_dir.mkdir(parents=True, exist_ok=True)
    global_config_path.write_text(
        json.dumps(
            {
                "cad": {
                    "target_language": "en",
                    "translation_mode": "replace",
                    "converter_backend": "auto",
                }
            }
        ),
        encoding="utf-8",
    )

    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.chdir(tmp_path)
    _clear_app_modules()

    manager_module = importlib.import_module("app.services.config_manager")
    manager = manager_module.ConfigManager()

    rendered = manager.update_project_config(
        {
            "cad": {
                "target_language": "ru",
                "translation_mode": "add",
                "converter_backend": "oda",
            }
        }
    )

    assert rendered["cad"]["target_language"] == "ru"
    assert rendered["cad"]["translation_mode"] == "add"
    assert rendered["cad"]["converter_backend"] == "oda"
    assert project_config_path.exists()
    persisted = json.loads(project_config_path.read_text(encoding="utf-8"))
    assert persisted["cad"]["target_language"] == "ru"
    assert persisted["cad"]["translation_mode"] == "add"


def test_translation_config_persists_fallback_models(
    loaded_backend: tuple[ModuleType, TestClient],
) -> None:
    _, client = loaded_backend

    response = client.post(
        "/api/translation/config",
        json={
            "provider": "openrouter",
            "format": "openai_compatible",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "sk-primary-secret",
            "model": "primary-model",
            "fallback_models": [
                {
                    "provider": "nvidia",
                    "format": "openai_compatible",
                    "base_url": "https://integrate.api.nvidia.com/v1",
                    "api_key": "nvapi-fallback-secret",
                    "model": "moonshotai/kimi-k2.5",
                    "reasoning_enabled": True,
                }
            ],
        },
    )

    assert response.status_code == 200
    runtime = response.json()["runtime"]
    assert runtime["provider"] == "openrouter"
    assert runtime["fallback_count"] == 1
    assert runtime["fallback_models"][0]["provider"] == "nvidia"
    assert runtime["fallback_models"][0]["model"] == "moonshotai/kimi-k2.5"
    assert runtime["fallback_models"][0]["reasoning_enabled"] is True
    assert runtime["fallback_models"][0]["api_key_configured"] is True


def test_llm_chat_skips_unhealthy_primary_and_uses_fallback(
    loaded_backend: tuple[ModuleType, TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_module = importlib.import_module("app.services.llm.translation_service")
    service = service_module.LLMTranslationService()

    monkeypatch.setattr(
        service,
        "_active_config",
        lambda: {
            "provider": "openrouter",
            "format": "openai_compatible",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "primary-model",
            "api_key": "sk-primary-secret",
            "timeout": 30,
            "temperature": 0.1,
            "max_tokens": 1000,
            "system_prompt": "base",
            "system_prompt_mode": "default",
            "custom_system_prompt": "",
            "glossary_file": "",
            "default_glossary_used": False,
            "reasoning_enabled": False,
            "batch_size": 4,
            "batch_json": True,
            "fallback_models": [
                {
                    "provider": "nvidia",
                    "format": "openai_compatible",
                    "base_url": "https://integrate.api.nvidia.com/v1",
                    "model": "fallback-model",
                    "api_key": "nvapi-fallback-secret",
                    "timeout": 30,
                    "temperature": 0.1,
                    "max_tokens": 1000,
                    "reasoning_enabled": True,
                }
            ],
        },
    )

    probe_calls: list[str] = []
    chat_calls: list[str] = []

    def fake_probe(cfg: dict[str, object]) -> dict[str, object]:
        probe_calls.append(str(cfg["provider"]))
        success = cfg["provider"] == "nvidia"
        return {
            "success": success,
            "reachable": success,
            "status_code": 200 if success else 503,
            "provider": cfg["provider"],
            "format": cfg["format"],
            "endpoint": "demo",
            "model": cfg["model"],
            "message": "ok" if success else "down",
        }

    def fake_dispatch(cfg: dict[str, object], _messages: list[dict[str, str]]) -> str:
        chat_calls.append(str(cfg["provider"]))
        return "Valve DN50"

    monkeypatch.setattr(service, "_probe_candidate", fake_probe)
    monkeypatch.setattr(service, "_dispatch_chat", fake_dispatch)

    translated = service.translate_text("阀门 DN50", source_lang="zh", target_lang="en")

    assert translated == "Valve DN50"
    assert probe_calls == ["openrouter", "nvidia"]
    assert chat_calls == ["nvidia"]


def test_llm_chat_falls_back_after_primary_rate_limit(
    loaded_backend: tuple[ModuleType, TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_module = importlib.import_module("app.services.llm.translation_service")
    service = service_module.LLMTranslationService()

    monkeypatch.setattr(
        service,
        "_active_config",
        lambda: {
            "provider": "openrouter",
            "format": "openai_compatible",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "primary-model",
            "api_key": "sk-primary-secret",
            "timeout": 30,
            "temperature": 0.1,
            "max_tokens": 1000,
            "system_prompt": "base",
            "system_prompt_mode": "default",
            "custom_system_prompt": "",
            "glossary_file": "",
            "default_glossary_used": False,
            "reasoning_enabled": False,
            "batch_size": 4,
            "batch_json": True,
            "fallback_models": [
                {
                    "provider": "nvidia",
                    "format": "openai_compatible",
                    "base_url": "https://integrate.api.nvidia.com/v1",
                    "model": "fallback-model",
                    "api_key": "nvapi-fallback-secret",
                    "timeout": 30,
                    "temperature": 0.1,
                    "max_tokens": 1000,
                    "reasoning_enabled": True,
                }
            ],
        },
    )

    call_order: list[str] = []

    def fake_probe(_cfg: dict[str, object]) -> dict[str, object]:
        return {
            "success": True,
            "reachable": True,
            "status_code": 200,
            "provider": "ok",
            "format": "openai_compatible",
            "endpoint": "demo",
            "model": "demo",
            "message": "ok",
        }

    def fake_dispatch(cfg: dict[str, object], _messages: list[dict[str, str]]) -> str:
        call_order.append(str(cfg["provider"]))
        if cfg["provider"] == "openrouter":
            raise ValueError("LLM request failed: 429 temporarily rate-limited upstream")
        return "Valve DN50"

    monkeypatch.setattr(service, "_probe_candidate", fake_probe)
    monkeypatch.setattr(service, "_dispatch_chat", fake_dispatch)
    monkeypatch.setattr(service_module.time, "sleep", lambda *_args, **_kwargs: None)

    translated = service.translate_text("阀门 DN50", source_lang="zh", target_lang="en")

    assert translated == "Valve DN50"
    assert call_order[:3] == ["openrouter", "openrouter", "openrouter"]
    assert call_order[-1] == "nvidia"


def test_llm_chat_retries_transient_transport_errors(
    loaded_backend: tuple[ModuleType, TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_module = importlib.import_module("app.services.llm.translation_service")
    service = service_module.LLMTranslationService()
    service.settings.TRANSLATION_PROVIDER = "custom"
    service.settings.LLM_BASE_URL = "https://gateway.example.com/v1"
    service.settings.LLM_MODEL = "demo-model"
    service.settings.LLM_API_KEY = "sk-demo-secret"

    calls = {"count": 0}

    class DummyResponse:
        status_code = 200
        text = "ok"

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "клапан",
                        }
                    }
                ]
            }

    def fake_post(*_args, **_kwargs) -> DummyResponse:
        calls["count"] += 1
        if calls["count"] < 3:
            raise service_module.requests.exceptions.SSLError("eof")
        return DummyResponse()

    monkeypatch.setattr(service_module.requests, "post", fake_post)
    monkeypatch.setattr(service_module.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        service,
        "_probe_candidate",
        lambda _cfg: {
            "success": True,
            "reachable": True,
            "status_code": 200,
            "provider": "custom",
            "format": "openai_compatible",
            "endpoint": "demo",
            "model": "demo-model",
            "message": "ok",
        },
    )

    translated = service.translate_text("阀门", source_lang="zh", target_lang="ru")

    assert translated == "клапан"
    assert calls["count"] == 3


def test_llm_chat_raises_clear_error_when_content_is_missing(
    loaded_backend: tuple[ModuleType, TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_module = importlib.import_module("app.services.llm.translation_service")
    service = service_module.LLMTranslationService()
    service.settings.TRANSLATION_PROVIDER = "custom"
    service.settings.LLM_BASE_URL = "https://gateway.example.com/v1"
    service.settings.LLM_MODEL = "demo-model"
    service.settings.LLM_API_KEY = "sk-demo-secret"

    class DummyResponse:
        status_code = 200
        text = "{}"

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": None,
                        }
                    }
                ]
            }

    monkeypatch.setattr(service_module.requests, "post", lambda *_args, **_kwargs: DummyResponse())
    monkeypatch.setattr(
        service,
        "_probe_candidate",
        lambda _cfg: {
            "success": True,
            "reachable": True,
            "status_code": 200,
            "provider": "custom",
            "format": "openai_compatible",
            "endpoint": "demo",
            "model": "demo-model",
            "message": "ok",
        },
    )

    with pytest.raises(ValueError, match="did not include text content"):
        service._chat([{"role": "user", "content": "Translate 阀门"}])


def test_llm_translate_text_applies_cad_prompt_and_glossary(
    loaded_backend: tuple[ModuleType, TestClient],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service_module = importlib.import_module("app.services.llm.translation_service")
    service = service_module.LLMTranslationService()

    glossary_path = tmp_path / "terms.csv"
    glossary_path.write_text("source,target\nvalve,клапан\npump,насос\n", encoding="utf-8")

    class DummyConfigManager:
        def get_effective_config(self):
            return {
                "llm": {
                    "primary": {
                        "provider": "custom",
                        "format": "openai_compatible",
                        "base_url": "https://gateway.example.com/v1",
                        "api_key": "sk-demo-secret",
                        "model": "demo-model",
                    },
                    "system_prompt_mode": "cad_specialized",
                    "glossary_file": str(glossary_path),
                }
            }

    monkeypatch.setattr(service_module, "ConfigManager", DummyConfigManager)

    captured: dict[str, object] = {}

    def fake_chat(messages):
        captured["messages"] = messages
        return "клапан"

    monkeypatch.setattr(service, "_chat", fake_chat)

    translated = service.translate_text("valve DN50", source_lang="en", target_lang="ru")

    assert translated == "клапан"
    system_message = str(captured["messages"][0]["content"])
    assert "CAD" in system_message
    assert "valve => клапан" in system_message


def test_llm_translate_text_supports_excel_glossary(
    loaded_backend: tuple[ModuleType, TestClient],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service_module = importlib.import_module("app.services.llm.translation_service")
    service = service_module.LLMTranslationService()

    glossary_path = tmp_path / "terms.xlsx"
    import pandas as pd

    pd.DataFrame(
        [
            {"source": "gate valve", "target": "задвижка"},
            {"source": "pump", "target": "насос"},
        ]
    ).to_excel(glossary_path, index=False)

    class DummyConfigManager:
        def get_effective_config(self):
            return {
                "llm": {
                    "primary": {
                        "provider": "custom",
                        "format": "openai_compatible",
                        "base_url": "https://gateway.example.com/v1",
                        "api_key": "sk-demo-secret",
                        "model": "demo-model",
                    },
                    "system_prompt_mode": "cad_specialized",
                    "glossary_file": str(glossary_path),
                }
            }

    monkeypatch.setattr(service_module, "ConfigManager", DummyConfigManager)

    captured: dict[str, object] = {}

    def fake_chat(messages):
        captured["messages"] = messages
        return "задвижка"

    monkeypatch.setattr(service, "_chat", fake_chat)

    translated = service.translate_text("gate valve", source_lang="en", target_lang="ru")

    assert translated == "задвижка"
    system_message = str(captured["messages"][0]["content"])
    assert "gate valve => задвижка" in system_message


def test_llm_translate_batch_uses_inferred_preferences_in_default_mode(
    loaded_backend: tuple[ModuleType, TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_module = importlib.import_module("app.services.llm.translation_service")
    service = service_module.LLMTranslationService()

    class DummyConfigManager:
        def get_effective_config(self):
            return {
                "llm": {
                    "primary": {
                        "provider": "custom",
                        "format": "openai_compatible",
                        "base_url": "https://gateway.example.com/v1",
                        "api_key": "sk-demo-secret",
                        "model": "demo-model",
                    },
                    "system_prompt_mode": "default",
                    "batch_json": True,
                    "batch_size": 8,
                }
            }

    monkeypatch.setattr(service_module, "ConfigManager", DummyConfigManager)
    monkeypatch.setattr(service, "_infer_terminology_preferences", lambda *args, **kwargs: "Prefer Russian valve terminology.")

    captured: dict[str, object] = {}

    def fake_chat(messages):
        captured["messages"] = messages
        return '{"text_0":"клапан","text_1":"задвижка"}'

    monkeypatch.setattr(service, "_chat", fake_chat)

    translated = service.translate_batch(["valve", "gate valve"], source_lang="en", target_lang="ru")

    assert translated == ["клапан", "задвижка"]
    system_message = str(captured["messages"][0]["content"])
    assert "Prefer Russian valve terminology." in system_message


def test_llm_openai_request_includes_reasoning_when_enabled(
    loaded_backend: tuple[ModuleType, TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_module = importlib.import_module("app.services.llm.translation_service")
    service = service_module.LLMTranslationService()

    class DummyConfigManager:
        def get_effective_config(self):
            return {
                "llm": {
                    "primary": {
                        "provider": "openrouter",
                        "format": "openai_compatible",
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key": "sk-demo-secret",
                        "model": "nvidia/nemotron-3-super-120b-a12b:free",
                        "reasoning_enabled": True,
                    }
                }
            }

    monkeypatch.setattr(service_module, "ConfigManager", DummyConfigManager)

    captured: dict[str, object] = {}

    class DummyResponse:
        status_code = 200
        text = "ok"

        @staticmethod
        def json() -> dict[str, object]:
            return {"choices": [{"message": {"content": "done"}}]}

    def fake_post(url: str, headers: dict[str, str], json: dict[str, object], timeout: int) -> DummyResponse:
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr(service_module.requests, "post", fake_post)

    translated = service.translate_text("valve", source_lang="en", target_lang="ru")

    assert translated == "done"
    assert captured["json"]["model"] == "nvidia/nemotron-3-super-120b-a12b:free"
    assert captured["json"]["reasoning"] == {"enabled": True}


def test_llm_nvidia_request_uses_chat_template_kwargs_when_reasoning_enabled(
    loaded_backend: tuple[ModuleType, TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_module = importlib.import_module("app.services.llm.translation_service")
    service = service_module.LLMTranslationService()

    class DummyConfigManager:
        def get_effective_config(self):
            return {
                "llm": {
                    "primary": {
                        "provider": "nvidia",
                        "format": "openai_compatible",
                        "base_url": "https://integrate.api.nvidia.com/v1",
                        "api_key": "nvapi-demo-secret",
                        "model": "moonshotai/kimi-k2.5",
                        "reasoning_enabled": True,
                    }
                }
            }

    monkeypatch.setattr(service_module, "ConfigManager", DummyConfigManager)

    captured: dict[str, object] = {}

    class DummyResponse:
        status_code = 200
        text = "ok"

        @staticmethod
        def json() -> dict[str, object]:
            return {"choices": [{"message": {"content": "done"}}]}

    def fake_post(url: str, headers: dict[str, str], json: dict[str, object], timeout: int) -> DummyResponse:
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr(service_module.requests, "post", fake_post)

    translated = service.translate_text("valve", source_lang="en", target_lang="ru")

    assert translated == "done"
    assert captured["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert captured["json"]["model"] == "moonshotai/kimi-k2.5"
    assert captured["json"]["chat_template_kwargs"] == {"thinking": True}


def test_projects_summary_aggregates_counts(loaded_backend: tuple[ModuleType, TestClient]) -> None:
    module, client = loaded_backend
    database_module = importlib.import_module("app.database")

    with database_module.SessionLocal() as db:
        project = database_module.Project(
            name="Pump Room Layout",
            description="CAD summary test",
            source_language="en",
            target_language="zh",
            status="processing",
            total_files=3,
            processed_files=1,
            total_texts=12,
            translated_texts=4,
        )
        db.add(project)
        db.flush()
        db.add(
            database_module.ProcessingTask(
                project_id=project.id,
                task_id="task-001",
                task_type="translate",
                status="failure",
                progress=0.5,
                message="provider timeout",
            )
        )
        db.commit()

    response = client.get("/api/projects/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["total_projects"] == 1
    assert body["counts"]["active_projects"] == 1
    assert body["counts"]["total_files"] == 3
    assert body["counts"]["translated_texts"] == 4
    assert body["alerts"]["failed_tasks"] == 1
    assert body["recent_tasks"][0]["task_id"] == "task-001"


def test_com_backend_routes_through_shared_converter(
    loaded_backend: tuple[ModuleType, TestClient],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import app.services.cad_text_processor as cad_text_processor_module
    import app.functions.dwg_converter as dwg_converter_module

    processor = cad_text_processor_module.CADTextProcessor()
    processor.settings.DWG_CONVERTER_BACKEND = "com"

    input_dwg = tmp_path / "sample.dwg"
    input_dwg.write_text("dwg", encoding="utf-8")

    expected_output = tmp_path / "converted" / "sample.dxf"
    expected_output.parent.mkdir(parents=True, exist_ok=True)
    expected_output.write_text("dxf", encoding="utf-8")

    calls: dict[str, str] = {}

    def fake_convert(self, dwg_file_path: str, output_dir: Path, backend_override: str | None = None) -> str:
        calls["dwg"] = dwg_file_path
        calls["output_dir"] = str(output_dir)
        calls["backend_override"] = backend_override or ""
        return str(expected_output)

    monkeypatch.setattr(
        dwg_converter_module.DWGConverter,
        "convert",
        fake_convert,
    )

    result = processor._convert_dwg_to_dxf(str(input_dwg), tmp_path / "converted")

    assert result == str(expected_output)
    assert calls["dwg"] == str(input_dwg)
    assert calls["output_dir"] == str(tmp_path / "converted")
    assert calls["backend_override"] == ""


def test_auto_backend_falls_back_from_haochen_to_autocad_to_oda(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    _clear_app_modules()
    converter_module = importlib.import_module("app.functions.dwg_converter")
    converter = converter_module.DWGConverter(converter_backend="auto")

    sample_dwg = tmp_path / "sample.dwg"
    sample_dwg.write_text("dwg", encoding="utf-8")
    output_dir = tmp_path / "converted"
    output_dir.mkdir(parents=True, exist_ok=True)
    expected_output = output_dir / "sample.dxf"
    expected_output.write_text("dxf", encoding="utf-8")

    calls: list[str] = []

    def fake_haochen(_self, dwg_file_path: str, output_dxf_path: str) -> str:
        calls.append("haochen_com")
        raise ValueError(f"haochen failed for {dwg_file_path} -> {output_dxf_path}")

    def fake_autocad(_self, dwg_file_path: str, output_dxf_path: str) -> str:
        calls.append("autocad_com")
        raise ValueError(f"autocad failed for {dwg_file_path} -> {output_dxf_path}")

    def fake_oda(_self, dwg_file_path: str, _output_dir: Path, output_dxf_path: str) -> str:
        calls.append("oda")
        Path(output_dxf_path).write_text("dxf", encoding="utf-8")
        return output_dxf_path

    monkeypatch.setattr(converter_module.DWGConverter, "_convert_via_haochen_com", fake_haochen)
    monkeypatch.setattr(converter_module.DWGConverter, "_convert_via_autocad_com", fake_autocad)
    monkeypatch.setattr(converter_module.DWGConverter, "_convert_via_oda", fake_oda)

    result = converter.convert(str(sample_dwg), output_dir)

    assert result == str(expected_output)
    assert calls == ["haochen_com", "autocad_com", "oda"]


def test_auto_backend_prefers_detected_and_respects_disabled_backends(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    _clear_app_modules()
    converter_module = importlib.import_module("app.functions.dwg_converter")
    converter = converter_module.DWGConverter(
        converter_backend="auto",
        dwg_auto_backends="haochen_com,autocad_com,oda",
        dwg_disabled_backends="haochen_com",
    )

    sample_dwg = tmp_path / "sample.dwg"
    sample_dwg.write_text("dwg", encoding="utf-8")
    output_dir = tmp_path / "converted"
    output_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        converter,
        "inspect_backends",
        lambda: {
            "haochen_com": {"detected": True, "reason": "registered"},
            "autocad_com": {"detected": True, "reason": "registered"},
            "oda": {"detected": True, "reason": "binary_found"},
        },
    )

    calls: list[str] = []

    def fake_autocad(_self, _dwg_file_path: str, output_dxf_path: str) -> str:
        calls.append("autocad_com")
        Path(output_dxf_path).write_text("dxf", encoding="utf-8")
        return output_dxf_path

    monkeypatch.setattr(converter_module.DWGConverter, "_convert_via_autocad_com", fake_autocad)

    result = converter.convert(str(sample_dwg), output_dir)

    assert result.endswith("sample.dxf")
    assert calls == ["autocad_com"]


def test_inspect_backends_reports_registered_autocad_and_disabled_haochen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    _clear_app_modules()
    converter_module = importlib.import_module("app.functions.dwg_converter")
    converter = converter_module.DWGConverter(
        converter_backend="auto",
        dwg_auto_backends="haochen_com,autocad_com,oda",
        dwg_disabled_backends="haochen_com",
    )

    monkeypatch.setattr(converter, "_running_process_names", lambda: {"acad.exe"})
    monkeypatch.setattr(
        converter,
        "_registered_prog_ids",
        lambda: {"autocad.application", "gstarcad.application"},
    )
    monkeypatch.setattr(
        converter,
        "_candidate_oda_paths",
        lambda: [ROOT_DIR / "definitely-missing-oda.exe"],
    )

    inspected = converter.inspect_backends()

    assert inspected["haochen_com"]["disabled"] is True
    assert inspected["haochen_com"]["detected"] is True
    assert inspected["autocad_com"]["detected"] is True
    assert inspected["autocad_com"]["reason"] in {"process_running", "registered"}
    assert inspected["oda"]["detected"] is False


def test_missing_oda_shows_install_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    _clear_app_modules()
    converter_module = importlib.import_module("app.functions.dwg_converter")
    converter = converter_module.DWGConverter(converter_backend="oda", oda_path="")
    monkeypatch.setattr(
        converter,
        "_resolve_oda_path",
        lambda: (_ for _ in ()).throw(
            ValueError(
                "ODA File Converter was not found. Install it from "
                "https://www.opendesign.com/GUESTFILES/ODA_FILE_CONVERTER "
                "or set ODA_FILE_CONVERTER_PATH."
            )
        ),
    )

    with pytest.raises(ValueError) as excinfo:
        converter._convert_via_oda("demo.dwg", Path("."), "demo.dxf")

    assert "ODA File Converter" in str(excinfo.value)


def test_com_backend_timeout_is_short_and_returns_clear_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    _clear_app_modules()
    converter_module = importlib.import_module("app.functions.dwg_converter")
    converter = converter_module.DWGConverter(converter_backend="auto", cad_converter_timeout=300)
    captured: dict[str, object] = {}
    source_dwg = tmp_path / "demo.dwg"
    source_dwg.write_text("dwg", encoding="utf-8")
    output_dxf = tmp_path / "demo.dxf"

    def fake_run(*_args, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        raise subprocess.TimeoutExpired(cmd="python -m app.services.com_converter_cli", timeout=kwargs.get("timeout"))

    monkeypatch.setattr(converter_module.subprocess, "run", fake_run)

    with pytest.raises(ValueError) as excinfo:
        converter._run_com_converter(
            "app.services.haochen_optimized_converter",
            "OptimizedHaoChenCADConverter",
            str(source_dwg),
            str(output_dxf),
        )

    assert captured["timeout"] == 20
    assert "timed out" in str(excinfo.value)


def test_run_com_converter_uses_utf8_env_and_ascii_temp_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    _clear_app_modules()
    converter_module = importlib.import_module("app.functions.dwg_converter")
    converter = converter_module.DWGConverter(converter_backend="auto", cad_converter_timeout=60)

    source_dwg = tmp_path / "图纸.dwg"
    source_dwg.write_text("dwg", encoding="utf-8")
    final_output = tmp_path / "输出.dxf"
    captured: dict[str, object] = {}

    def fake_finalize(raw_output_path: Path, final_output_path: Path) -> str:
        captured["raw_output_path"] = raw_output_path
        captured["final_output_path"] = final_output_path
        final_output_path.write_text("dxf", encoding="utf-8")
        return str(final_output_path)

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs.get("env", {})
        raw_output = Path(command[command.index("--output") + 1])
        raw_output.parent.mkdir(parents=True, exist_ok=True)
        raw_output.write_text("raw dxf", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout='{"success": true}', stderr="")

    monkeypatch.setattr(converter, "_validate_and_finalize_dxf", fake_finalize)
    monkeypatch.setattr(converter_module.subprocess, "run", fake_run)

    result = converter._run_com_converter(
        "app.services.autocad_converter",
        "AutoCADConverter",
        str(source_dwg),
        str(final_output),
    )

    command = captured["command"]
    env = captured["env"]
    raw_output_path = captured["raw_output_path"]

    assert result == str(final_output)
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"
    assert Path(command[command.index("--dwg") + 1]).name == "input.dwg"
    assert Path(command[command.index("--output") + 1]).name == "output.dxf"
    assert raw_output_path == Path(command[command.index("--output") + 1])
    assert final_output.exists()


def test_prepare_com_paths_is_isolated_per_backend(tmp_path: Path) -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    _clear_app_modules()
    converter_module = importlib.import_module("app.functions.dwg_converter")
    converter = converter_module.DWGConverter(converter_backend="auto")

    source_dwg = tmp_path / "demo.dwg"
    source_dwg.write_text("dwg", encoding="utf-8")
    output_path = tmp_path / "translated.dxf"

    haochen_paths = converter._prepare_com_paths(str(source_dwg), str(output_path), "haochen_com")
    autocad_paths = converter._prepare_com_paths(str(source_dwg), str(output_path), "autocad_com")

    assert haochen_paths[0] != autocad_paths[0]
    assert haochen_paths[1] != autocad_paths[1]


def test_cad_extract_accepts_dwg_and_returns_contract_payload(
    loaded_backend: tuple[ModuleType, TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = loaded_backend
    cad_route_module = importlib.import_module("app.api.routes.cad")

    class DummyPipeline:
        @staticmethod
        def extract_upload(*_args, **_kwargs) -> dict[str, object]:
            return {
                "task_id": "dwg12345",
                "text_count": 2,
                "excel_file_url": "/api/cad/download/dwg12345/excel",
                "texts": [
                    {
                        "id": "dwg12345_0",
                        "original_text": "VALVE",
                        "translated_text": "",
                        "entity_type": "TEXT",
                        "layer": "NOTES",
                        "position": "(1, 2)",
                    }
                ],
            }

    monkeypatch.setattr(cad_route_module, "cad_pipeline_service", DummyPipeline(), raising=False)

    response = client.post(
        "/api/cad/extract",
        data={"converter_backend": "auto", "target_language": "ru"},
        files={"file": ("demo.dwg", b"dwg-binary", "application/octet-stream")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["task_id"] == "dwg12345"
    assert body["data"]["text_count"] == 2
    assert body["data"]["excel_file"] == "/api/cad/download/dwg12345/excel"
    assert body["data"]["texts"][0]["original_text"] == "VALVE"


def test_cad_extract_task_is_visible_in_task_list(
    loaded_backend: tuple[ModuleType, TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = loaded_backend
    cad_route_module = importlib.import_module("app.api.routes.cad")

    class DummyPipeline:
        @staticmethod
        def extract_upload(*_args, **_kwargs) -> dict[str, object]:
            return {
                "task_id": "dwg98765",
                "text_count": 1,
                "excel_file_url": "/api/cad/download/dwg98765/excel",
                "texts": [
                    {
                        "id": "dwg98765_0",
                        "original_text": "PUMP",
                        "translated_text": "",
                        "entity_type": "TEXT",
                        "layer": "TITLE",
                        "position": "(0, 0)",
                    }
                ],
            }

        @staticmethod
        def list_tasks() -> list[dict[str, object]]:
            return [
                {
                    "task_id": "dwg98765",
                    "original_filename": "demo.dwg",
                    "target_language": "ru",
                    "extract_only": False,
                    "processing_time": "0.5s",
                    "text_count": 1,
                    "translation_count": 0,
                    "files": {
                        "excel_file": "/api/cad/download/dwg98765/excel",
                        "translated_cad_file": None,
                        "log_file": "/api/cad/download/dwg98765/log",
                    },
                }
            ]

    monkeypatch.setattr(cad_route_module, "cad_pipeline_service", DummyPipeline(), raising=False)

    extract_response = client.post(
        "/api/cad/extract",
        data={"converter_backend": "auto", "target_language": "ru"},
        files={"file": ("demo.dwg", b"dwg-binary", "application/octet-stream")},
    )

    assert extract_response.status_code == 200

    list_response = client.get("/api/cad/tasks")

    assert list_response.status_code == 200
    body = list_response.json()
    assert body["success"] is True
    assert body["data"][0]["task_id"] == "dwg98765"
    assert body["data"][0]["original_filename"] == "demo.dwg"


def test_health_stays_responsive_while_cad_batch_translation_runs(
    loaded_backend: tuple[ModuleType, TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = loaded_backend
    cad_route_module = importlib.import_module("app.api.routes.cad")

    class SlowTranslator:
        @staticmethod
        def translate_batch(*_args, **_kwargs) -> list[str]:
            time.sleep(0.4)
            return ["насос"]

    monkeypatch.setattr(cad_route_module, "alibaba_ai_translation_service", SlowTranslator(), raising=False)

    translate_response: dict[str, object] = {}

    def run_translation() -> None:
        translate_response["response"] = client.post(
            "/api/cad/translate-batch",
            json={"texts": ["PUMP"], "target_lang": "ru"},
        )

    worker = threading.Thread(target=run_translation)
    worker.start()
    time.sleep(0.05)

    started = time.perf_counter()
    health_response = client.get("/api/health")
    elapsed = time.perf_counter() - started

    worker.join()

    assert health_response.status_code == 200
    assert elapsed < 0.25
    assert translate_response["response"].status_code == 200


def test_dwg_converter_uses_copied_com_scripts_inside_backend() -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    _clear_app_modules()
    module = importlib.import_module("app.functions.dwg_converter")
    converter = module.DWGConverter(converter_backend="auto")

    haochen_script = converter._service_script_path("haochen_optimized_converter.py")
    autocad_script = converter._service_script_path("autocad_converter.py")

    assert haochen_script == BACKEND_DIR / "app" / "services" / "haochen_optimized_converter.py"
    assert autocad_script == BACKEND_DIR / "app" / "services" / "autocad_converter.py"
    assert haochen_script.exists()
    assert autocad_script.exists()


def test_text_applier_can_save_oda_converted_dxf(tmp_path: Path) -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    _clear_app_modules()
    converter_module = importlib.import_module("app.functions.dwg_converter")
    text_applier_module = importlib.import_module("app.functions.text_applier")

    sample_dwg = next(ROOT_DIR.glob("*.dwg"))
    converter = converter_module.DWGConverter(converter_backend="oda")

    converted_dxf = Path(converter.convert(str(sample_dwg), tmp_path / "convert"))
    output_path = tmp_path / "translated.dxf"

    result = text_applier_module.TextApplier().apply(
        dxf_file_path=str(converted_dxf),
        output_file_path=str(output_path),
        translation_map={},
    )

    assert result["success"] is True
    assert output_path.exists()


def test_text_applier_add_mode_inserts_translated_text(tmp_path: Path) -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    _clear_app_modules()
    text_applier_module = importlib.import_module("app.functions.text_applier")

    source_path = tmp_path / "source.dxf"
    output_path = tmp_path / "translated.dxf"
    doc = ezdxf.new("R2010")
    doc.modelspace().add_text("阀门", dxfattribs={"insert": (0, 0), "height": 2.5})
    doc.saveas(source_path)

    result = text_applier_module.TextApplier().apply(
        dxf_file_path=str(source_path),
        output_file_path=str(output_path),
        translation_map={"阀门": "Valve"},
        translation_mode="add",
        font_name="Arial",
        font_size_reduction=1,
    )

    translated_doc = ezdxf.readfile(output_path)
    texts = [entity.dxf.text for entity in translated_doc.modelspace() if entity.dxftype() == "TEXT"]

    assert result["success"] is True
    assert "阀门" in texts
    assert "Valve" in texts
