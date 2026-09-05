"""Deterministic checks for release path, secret, launcher, and archive gates."""

from __future__ import annotations

import json
import sys
import types
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "release_exe"))

import release_manifest  # noqa: E402
import launcher  # noqa: E402


def test_sanitizer_clears_provider_key_map_without_printing_values(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "providers": {"provider_api_keys": {"private": "secret-value"}},
                "api_key": "another-secret",
                "api_key_configured": True,
            }
        ),
        encoding="utf-8",
    )
    release_manifest.sanitize_json_file(config)
    result = json.loads(config.read_text(encoding="utf-8"))
    assert result["providers"]["provider_api_keys"] == {}
    assert result["api_key"] == ""
    assert result["api_key_configured"] is False
    assert "secret-value" not in config.read_text(encoding="utf-8")


def test_release_guard_checks_yaml_credentials_and_omits_values(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("provider_api_keys:\n  private: forbidden-value\n")
    with pytest.raises(ValueError, match="secret-bearing config") as error:
        release_manifest.audit_directory(tmp_path)
    assert "forbidden-value" not in str(error.value)


def test_frozen_builder_refuses_missing_required_excel_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    import pyinstaller_manifest

    find_spec = pyinstaller_manifest.importlib.util.find_spec
    monkeypatch.setattr(pyinstaller_manifest.importlib.util, "find_spec",
                        lambda name: None if name == "xlrd" else find_spec(name))
    with pytest.raises(RuntimeError, match="xlrd"):
        pyinstaller_manifest.validate_runtime_dependencies()


def test_copy_filter_excludes_personal_files_but_keeps_built_frontend(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / ".venv").mkdir(parents=True)
    (source / "logs").mkdir()
    (source / "config").mkdir()
    (source / ".venv" / "private.txt").write_text("x")
    (source / "logs" / "server.log").write_text("x")
    (source / "config" / "runtime_config.local.json").write_text("{}")
    (source / "app.py").write_text("pass")
    stage = tmp_path / "stage"
    release_manifest.copy_tree_into(stage, source, "backend")
    assert (stage / "backend/app.py").exists()
    assert not (stage / "backend/.venv/private.txt").exists()
    assert not (stage / "backend/logs/server.log").exists()
    assert not (stage / "backend/config/runtime_config.local.json").exists()
    assert not release_manifest.is_excluded("frontend/dist/index.html")


def test_artifact_gate_audits_nested_zip_and_rejects_forbidden_member(tmp_path: Path) -> None:
    inner = tmp_path / "inner.zip"
    with zipfile.ZipFile(inner, "w") as archive:
        archive.writestr("backend/.env", "SECRET")
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as archive:
        archive.write(inner, "runtime_payload.zip")
    with pytest.raises(ValueError, match="forbidden archive member"):
        release_manifest.audit_zip(outer)


def test_artifact_gate_allows_built_payload_and_requires_runtime_files(tmp_path: Path) -> None:
    (tmp_path / "backend/app").mkdir(parents=True)
    (tmp_path / "frontend/dist").mkdir(parents=True)
    (tmp_path / "backend/app/main.py").write_text("app = object()")
    (tmp_path / "frontend/dist/index.html").write_text("<html>")
    release_manifest.audit_directory(
        tmp_path, required=("backend/app/main.py", "frontend/dist/index.html")
    )


def test_frozen_stdlib_bytecode_exception_does_not_allow_payload_caches(tmp_path: Path) -> None:
    from io import BytesIO

    data = BytesIO()
    with zipfile.ZipFile(data, "w") as inner:
        inner.writestr("encodings/__init__.pyc", b"runtime bytecode")
    artifact = tmp_path / "bundle.zip"
    with zipfile.ZipFile(artifact, "w") as outer:
        outer.writestr("_internal/base_library.zip", data.getvalue())
    release_manifest.audit_zip(artifact)
    with zipfile.ZipFile(artifact, "a") as outer:
        outer.writestr("runtime_payload.zip", data.getvalue())
    with pytest.raises(ValueError, match="forbidden archive member"):
        release_manifest.audit_zip(artifact)


def test_launcher_paths_are_hashed_code_cache_and_separate_durable_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    code, data, lock = launcher._runtime_paths("abc123")
    assert code == tmp_path / "CAD Translation/code-cache/abc123"
    assert data == tmp_path / "CAD Translation/data"
    assert code != data
    assert lock.parent == code.parent


def test_launcher_lock_returns_owned_fd_and_closes_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=lambda *_args: None)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    lock_path = tmp_path / "locks" / "runtime.lock"
    fd = launcher._acquire_lock(lock_path, timeout=0.1)
    assert isinstance(fd, int)
    launcher._release_lock(fd)
    with pytest.raises(OSError):
        import os

        os.fstat(fd)


def test_launcher_safe_extraction_rejects_path_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = tmp_path / "payload.zip"
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../escape.txt", "no")
    monkeypatch.setattr(launcher, "_PAYLOAD_ZIP", payload)
    with pytest.raises(ValueError, match="unsafe payload member"):
        launcher._extract_payload(tmp_path / "out")


@pytest.mark.parametrize("name", ["frontend/dist/.env", "frontend/dist/logs/key.log",
                                 "frontend/dist/credentials.json", "pkg/name.egg-info/PKG-INFO"])
def test_release_filter_does_not_exempt_secrets_inside_built_frontend(name: str) -> None:
    assert release_manifest.is_excluded(name)


@pytest.mark.parametrize("tag", ["v01.2.3", "v1.2.3-01", "v1.2.3-", "main", "v1.2.4"])
def test_release_tag_enforces_semver_and_canonical_match(tmp_path: Path, tag: str) -> None:
    source = tmp_path / "version.py"
    source.write_text('__version__ = "1.2.3"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        release_manifest.validate_release_tag(tag, source)
    release_manifest.validate_release_tag("v1.2.3", source)


def test_launcher_env_uses_only_settings_fields(tmp_path: Path) -> None:
    path = tmp_path / "runtime.env"
    launcher._write_env_file(path, 8910, tmp_path)
    from app.config import Settings

    settings = Settings(_env_file=path)
    assert settings.OUTPUT_DIR == str(tmp_path / "outputs").replace("\\", "/")
    assert not settings.ENABLE_ADMIN_GUARD


@pytest.mark.skipif(sys.platform != "win32", reason="Exercises native Windows msvcrt launcher locking")
def test_launcher_repairs_incomplete_cache_and_preserves_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("CAD_HEADLESS", "true")
    payload = tmp_path / "payload.zip"
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("backend/app/main.py", "app = None")
        archive.writestr("frontend/dist/index.html", "ready")
    monkeypatch.setattr(launcher, "_PAYLOAD_ZIP", payload)
    cache, data, _ = launcher._runtime_paths(launcher._payload_hash())
    (cache / "backend/app").mkdir(parents=True)
    (cache / "backend/app/main.py").write_text("incomplete")
    data.mkdir(parents=True)
    (data / "sentinel").write_text("durable")
    def fake_server(_app_dir: Path, _port: int) -> None:
        import os

        assert Path(os.environ["CAD_TRANSLATION_RUNTIME_CONFIG_FILE"]) == data / "config/config.json"
        assert (cache / "frontend/dist/index.html").is_file()
    monkeypatch.setattr(launcher, "_run_uvicorn", fake_server)
    monkeypatch.setenv("CAD_TRANSLATION_ENV_FILE", "unused")
    monkeypatch.setenv("CAD_TRANSLATION_RUNTIME_CONFIG_FILE", "unused")
    assert launcher.main() == 0
    assert launcher.main() == 0
    assert (data / "sentinel").read_text() == "durable"
    assert not list(data.glob(".runtime-*.env"))
    assert not list(cache.parent.glob("*.stale-*"))
