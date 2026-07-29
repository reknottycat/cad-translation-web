from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Iterator

import pytest
from fastapi.testclient import TestClient


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"


def _clear_app_modules() -> None:
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            sys.modules.pop(module_name, None)


def _write_env_file(
    env_path: Path,
    db_path: Path,
    debug_value: str,
    jwt_secret: str,
    *,
    enable_admin_guard: bool = False,
    admin_api_token: str = "",
) -> None:
    lines = [
        "APP_ENV=test",
        f"DEBUG={debug_value}",
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
        f"JWT_SECRET_KEY={jwt_secret}",
        f"ENABLE_ADMIN_GUARD={'true' if enable_admin_guard else 'false'}",
        f"ADMIN_API_TOKEN={admin_api_token}",
    ]
    env_path.write_text("\n".join(lines), encoding="utf-8")


@pytest.fixture()
def backend_with_debug_release(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[tuple[ModuleType, TestClient]]:
    env_path = tmp_path / ".env"
    db_path = tmp_path / "runtime.db"
    runtime_config_path = tmp_path / "runtime_config.local.json"
    _write_env_file(env_path, db_path, "release", "test-admin-secret")

    monkeypatch.delenv("DEBUG", raising=False)
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


@pytest.fixture()
def backend_with_admin_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    env_path = tmp_path / ".env"
    db_path = tmp_path / "runtime.db"
    runtime_config_path = tmp_path / "runtime_config.local.json"
    _write_env_file(
        env_path,
        db_path,
        "false",
        "test-jwt-secret",
        enable_admin_guard=True,
        admin_api_token="test-admin-secret",
    )

    monkeypatch.delenv("DEBUG", raising=False)
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    monkeypatch.setenv("CAD_TRANSLATION_ENV_FILE", str(env_path))
    monkeypatch.setenv("CAD_TRANSLATION_RUNTIME_CONFIG_FILE", str(runtime_config_path))
    monkeypatch.chdir(ROOT_DIR)
    _clear_app_modules()

    module = importlib.import_module("app.main")
    with TestClient(module.app) as client:
        yield client
    _clear_app_modules()


@pytest.fixture()
def backend_without_admin_guard(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    env_path = tmp_path / ".env"
    db_path = tmp_path / "runtime.db"
    runtime_config_path = tmp_path / "runtime_config.local.json"
    _write_env_file(env_path, db_path, "false", "test-admin-secret")

    monkeypatch.delenv("DEBUG", raising=False)
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    monkeypatch.setenv("CAD_TRANSLATION_ENV_FILE", str(env_path))
    monkeypatch.setenv("CAD_TRANSLATION_RUNTIME_CONFIG_FILE", str(runtime_config_path))
    monkeypatch.chdir(ROOT_DIR)
    _clear_app_modules()

    module = importlib.import_module("app.main")
    with TestClient(module.app) as client:
        yield client
    _clear_app_modules()


@pytest.fixture()
def backend_with_missing_admin_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    env_path = tmp_path / ".env"
    db_path = tmp_path / "runtime.db"
    runtime_config_path = tmp_path / "runtime_config.local.json"
    _write_env_file(
        env_path,
        db_path,
        "false",
        "test-jwt-secret",
        enable_admin_guard=True,
    )

    monkeypatch.delenv("DEBUG", raising=False)
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    monkeypatch.setenv("CAD_TRANSLATION_ENV_FILE", str(env_path))
    monkeypatch.setenv("CAD_TRANSLATION_RUNTIME_CONFIG_FILE", str(runtime_config_path))
    monkeypatch.chdir(ROOT_DIR)
    _clear_app_modules()

    module = importlib.import_module("app.main")
    with TestClient(module.app) as client:
        yield client
    _clear_app_modules()


def test_debug_release_is_treated_as_disabled_debug_mode(
    backend_with_debug_release: tuple[ModuleType, TestClient],
) -> None:
    module, client = backend_with_debug_release

    response = client.get("/")

    assert response.status_code == 200
    assert module.settings.DEBUG is False


def test_dangerous_routes_do_not_require_admin_token_by_default(
    backend_without_admin_guard: TestClient,
) -> None:
    client = backend_without_admin_guard

    allowed_clear = client.delete("/api/projects/clear")
    allowed_tasks = client.delete("/api/cad/tasks")
    allowed_stop_all = client.post("/api/cad/tasks/stop-all")

    assert allowed_clear.status_code == 200
    assert allowed_tasks.status_code == 200
    assert allowed_stop_all.status_code == 200


def test_dangerous_routes_require_admin_token_when_guard_enabled(backend_with_admin_token: TestClient) -> None:
    client = backend_with_admin_token

    denied_clear = client.delete("/api/projects/clear")
    denied_tasks = client.delete("/api/cad/tasks")
    denied_stop_all = client.post("/api/cad/tasks/stop-all")

    assert denied_clear.status_code == 403
    assert denied_tasks.status_code == 403
    assert denied_stop_all.status_code == 403

    headers = {"X-Admin-Token": "test-admin-secret"}

    allowed_clear = client.delete("/api/projects/clear", headers=headers)
    allowed_tasks = client.delete("/api/cad/tasks", headers=headers)
    allowed_stop_all = client.post("/api/cad/tasks/stop-all", headers=headers)

    assert allowed_clear.status_code == 200
    assert allowed_tasks.status_code == 200
    assert allowed_stop_all.status_code == 200


def test_dangerous_routes_reject_missing_admin_token_when_guard_enabled(
    backend_with_missing_admin_token: TestClient,
) -> None:
    client = backend_with_missing_admin_token

    denied_clear = client.delete("/api/projects/clear")
    denied_tasks = client.delete("/api/cad/tasks")
    denied_stop_all = client.post("/api/cad/tasks/stop-all")

    assert denied_clear.status_code == 403
    assert denied_tasks.status_code == 403
    assert denied_stop_all.status_code == 403


def test_jwt_secret_key_is_not_used_as_admin_fallback(backend_with_admin_token: TestClient) -> None:
    client = backend_with_admin_token

    denied_clear = client.delete("/api/projects/clear", headers={"X-Admin-Token": "test-jwt-secret"})
    allowed_clear = client.delete("/api/projects/clear", headers={"X-Admin-Token": "test-admin-secret"})

    assert denied_clear.status_code == 403
    assert allowed_clear.status_code == 200


def test_cad_upload_does_not_require_admin_token(
    backend_with_admin_token: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = backend_with_admin_token
    cad_route_module = importlib.import_module("app.api.routes.cad")

    class DummyPipeline:
        @staticmethod
        def process_upload(*_args, **_kwargs) -> dict[str, object]:
            return {
                "task_id": "upload123",
                "text_count": 1,
                "translation_count": 0,
                "excel_file_url": "/api/cad/download/upload123/excel",
                "translated_cad_file": None,
                "texts": [
                    {
                        "id": "upload123_0",
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
        "/api/cad/upload",
        data={
            "target_language": "ru",
            "extract_only": "false",
            "converter_backend": "auto",
            "translation_mode": "replace",
        },
        files={"file": ("demo.dwg", b"dwg-binary", "application/octet-stream")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["task_id"] == "upload123"
    assert body["data"]["text_count"] == 1


def test_cad_upload_rejects_invalid_file_before_pipeline_runs(
    backend_without_admin_guard: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = backend_without_admin_guard
    cad_route_module = importlib.import_module("app.api.routes.cad")

    class FailingPipeline:
        @staticmethod
        def process_upload(*_args, **_kwargs) -> dict[str, object]:
            raise AssertionError("process_upload should not run for invalid files")

    monkeypatch.setattr(cad_route_module, "cad_pipeline_service", FailingPipeline(), raising=False)

    response = client.post(
        "/api/cad/upload",
        data={
            "target_language": "ru",
            "extract_only": "false",
            "converter_backend": "auto",
            "translation_mode": "replace",
        },
        files={"file": ("demo.txt", b"not-cad", "text/plain")},
    )

    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["error"]


def test_cad_extract_rejects_invalid_file_before_pipeline_runs(
    backend_without_admin_guard: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = backend_without_admin_guard
    cad_route_module = importlib.import_module("app.api.routes.cad")

    class FailingPipeline:
        @staticmethod
        def extract_upload(*_args, **_kwargs) -> dict[str, object]:
            raise AssertionError("extract_upload should not run for invalid files")

    monkeypatch.setattr(cad_route_module, "cad_pipeline_service", FailingPipeline(), raising=False)

    response = client.post(
        "/api/cad/extract",
        data={"converter_backend": "auto", "target_language": "ru"},
        files={"file": ("demo.txt", b"not-cad", "text/plain")},
    )

    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["error"]
