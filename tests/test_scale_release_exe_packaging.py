from __future__ import annotations

import json
import os
import subprocess
import types
import zipfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT_DIR / "scripts" / "build_scale_exe.ps1"
NUITKA_BUILD_SCRIPT = ROOT_DIR / "scripts" / "build_scale_exe_nuitka.ps1"


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_build_scale_exe_creates_isolated_sanitized_output(tmp_path: Path) -> None:
    _write_file(tmp_path / "backend" / "run_server.py", "print('backend')\n")
    _write_file(tmp_path / "backend" / ".env", "LLM_API_KEY=sk-live-secret\nOPENROUTER_API_KEY=sk-or-live\n")
    _write_file(
        tmp_path / "backend" / "config" / "runtime_config.local.json",
        json.dumps(
            {
                "api_key": "sk-live-secret",
                "fallback_models": [
                    {
                        "api_key": "nvapi-live-secret",
                        "api_key_source": "config",
                        "api_key_configured": True,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    _write_file(tmp_path / "frontend" / "dist" / "index.html", "<html>runtime</html>\n")
    _write_file(tmp_path / "tools" / "libredwg" / "README.txt", "tool\n")
    _write_file(tmp_path / "requirements.txt", "fastapi\n")

    result = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(BUILD_SCRIPT),
            "-Root",
            str(tmp_path),
            "-OutDirName",
            "scale_release_exe",
            "-SkipPyInstaller",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout

    output_dir = tmp_path / "scale_release_exe"
    assert output_dir.exists()
    assert not (tmp_path / "scale_release").exists()
    assert (output_dir / "launcher.exe").exists()
    payload = output_dir / "runtime_payload.zip"
    assert payload.exists()

    with zipfile.ZipFile(payload) as archive:
        members = set(archive.namelist())
        assert "backend/run_server.py" in members
        assert "frontend/dist/index.html" in members
        assert "backend/.env" not in members
        assert "backend/config/runtime_config.local.json" in members

        runtime_config = json.loads(archive.read("backend/config/runtime_config.local.json").decode("utf-8"))
        assert runtime_config["api_key"] == ""
        assert runtime_config["fallback_models"][0]["api_key"] == ""
        assert runtime_config["fallback_models"][0]["api_key_source"] == "none"
        assert runtime_config["fallback_models"][0]["api_key_configured"] is False


def test_build_scale_exe_reuses_build_cache_and_cleans_stale_runtime(tmp_path: Path) -> None:
    output_dir = tmp_path / "scale_release_exe"
    cache_marker = output_dir / "_build" / "pyinstaller_work" / "cache.marker"
    stale_runtime_file = output_dir / "runtime" / "stale.txt"
    stale_root_file = output_dir / "stale.txt"

    _write_file(cache_marker, "keep me\n")
    _write_file(stale_runtime_file, "stale runtime\n")
    _write_file(stale_root_file, "stale root\n")

    _write_file(tmp_path / "backend" / "run_server.py", "print('backend')\n")
    _write_file(
        tmp_path / "backend" / "config" / "runtime_config.local.json",
        json.dumps({"api_key": "sk-live-secret"}, ensure_ascii=False, indent=2),
    )
    _write_file(tmp_path / "frontend" / "dist" / "index.html", "<html>runtime</html>\n")
    _write_file(tmp_path / "tools" / "libredwg" / "README.txt", "tool\n")

    result = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(BUILD_SCRIPT),
            "-Root",
            str(tmp_path),
            "-OutDirName",
            "scale_release_exe",
            "-SkipPyInstaller",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert cache_marker.exists()
    assert not stale_runtime_file.exists()
    assert not stale_root_file.exists()
    assert (output_dir / "launcher.exe").exists()
    assert (output_dir / "runtime_payload.zip").exists()


def test_launcher_spawns_backend_mode_process_and_opens_browser_once(monkeypatch, tmp_path: Path) -> None:
    import release_exe.launcher as launcher

    runtime_root = tmp_path / "runtime"
    backend_entry = runtime_root / "backend" / "run_server.py"
    frontend_dist = runtime_root / "frontend" / "dist"

    backend_entry.parent.mkdir(parents=True, exist_ok=True)
    backend_entry.write_text("print('backend')\n", encoding="utf-8")
    frontend_dist.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(launcher.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launcher.sys, "_MEIPASS", str(tmp_path / "_meipass"), raising=False)
    monkeypatch.setattr(launcher.sys, "executable", str(tmp_path / "launcher.exe"), raising=False)
    monkeypatch.setattr(launcher.sys, "argv", [str(tmp_path / "launcher.exe")], raising=False)
    monkeypatch.setattr(launcher, "ensure_runtime", lambda: runtime_root)
    monkeypatch.setattr(launcher, "wait_for_port", lambda host, port, timeout_seconds=30.0: True)

    captured: dict[str, object] = {}

    class FakeProcess:
        def wait(self) -> int:
            captured["wait_called"] = True
            return 0

        def poll(self) -> int | None:
            return None

        def terminate(self) -> None:
            captured["terminated"] = True

    browser_urls: list[str] = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: browser_urls.append(url) or True)
    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        lambda command, cwd=None: captured.update({"command": command, "cwd": cwd}) or FakeProcess(),
    )

    exit_code = launcher.main([])

    assert exit_code == 0
    assert captured["command"] == [
        str(tmp_path / "launcher.exe"),
        launcher.BACKEND_FLAG,
        launcher.RUNTIME_ROOT_FLAG,
        str(runtime_root),
    ]
    assert captured["cwd"] == str(runtime_root)
    assert captured["wait_called"] is True
    assert browser_urls == [launcher.APP_URL]


def test_launcher_reuses_existing_runtime_without_marker(monkeypatch, tmp_path: Path) -> None:
    import release_exe.launcher as launcher

    runtime_root = tmp_path / "runtime"
    backend_entry = runtime_root / "backend" / "run_server.py"
    backend_entry.parent.mkdir(parents=True, exist_ok=True)
    backend_entry.write_text("print('backend')\n", encoding="utf-8")
    (runtime_root / "backend" / "config").mkdir(parents=True, exist_ok=True)
    (runtime_root / "backend" / "config" / "runtime_config.local.json").write_text("{}", encoding="utf-8")
    (runtime_root / "frontend" / "dist").mkdir(parents=True, exist_ok=True)
    (runtime_root / "frontend" / "dist" / "index.html").write_text("<html>ok</html>\n", encoding="utf-8")

    monkeypatch.setattr(launcher, "runtime_dir", lambda: runtime_root)
    monkeypatch.setattr(launcher, "payload_path", lambda: tmp_path / "missing_payload.zip")

    resolved = launcher.ensure_runtime()

    assert resolved == runtime_root
    assert (runtime_root / ".ready").exists()


def test_launcher_reextracts_runtime_when_required_files_are_missing(monkeypatch, tmp_path: Path) -> None:
    import release_exe.launcher as launcher

    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "backend" / "run_server.py").parent.mkdir(parents=True, exist_ok=True)
    (runtime_root / "backend" / "run_server.py").write_text("print('backend')\n", encoding="utf-8")
    payload_root = tmp_path / "payload"
    (payload_root / "backend" / "run_server.py").parent.mkdir(parents=True, exist_ok=True)
    (payload_root / "backend" / "run_server.py").write_text("print('backend')\n", encoding="utf-8")
    (payload_root / "backend" / "config").mkdir(parents=True, exist_ok=True)
    (payload_root / "backend" / "config" / "runtime_config.local.json").write_text("{}", encoding="utf-8")
    (payload_root / "frontend" / "dist").mkdir(parents=True, exist_ok=True)
    (payload_root / "frontend" / "dist" / "index.html").write_text("<html>ok</html>\n", encoding="utf-8")

    payload_path = tmp_path / "runtime_payload.zip"
    with zipfile.ZipFile(payload_path, "w") as archive:
        for file_path in payload_root.rglob("*"):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(payload_root).as_posix())

    monkeypatch.setattr(launcher, "runtime_dir", lambda: runtime_root)
    monkeypatch.setattr(launcher, "payload_path", lambda: payload_path)

    resolved = launcher.ensure_runtime()

    assert resolved == runtime_root
    assert (runtime_root / "frontend" / "dist" / "index.html").exists()
    assert (runtime_root / "backend" / "config" / "runtime_config.local.json").exists()
    assert (runtime_root / ".ready").exists()


def test_launcher_backend_mode_runs_backend_without_opening_browser(monkeypatch, tmp_path: Path) -> None:
    import release_exe.launcher as launcher

    runtime_root = tmp_path / "runtime"
    backend_entry = runtime_root / "backend" / "run_server.py"
    backend_entry.parent.mkdir(parents=True, exist_ok=True)
    backend_entry.write_text("print('backend')\n", encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_load_backend_main(root: Path):
        captured["root"] = root

        def fake_backend_main() -> int:
            captured["called"] = True
            return 0

        return fake_backend_main

    monkeypatch.setattr(launcher, "ensure_runtime", lambda: runtime_root)
    monkeypatch.setattr(launcher, "load_backend_main", fake_load_backend_main)
    monkeypatch.setattr(
        launcher.webbrowser,
        "open",
        lambda url: (_ for _ in ()).throw(AssertionError(f"browser should not open in backend mode: {url}")),
    )

    exit_code = launcher.main([launcher.BACKEND_FLAG, launcher.RUNTIME_ROOT_FLAG, str(runtime_root)])

    assert exit_code == 0
    assert captured["root"] == runtime_root
    assert captured["called"] is True


def test_load_backend_main_sets_runtime_environment_before_import(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import release_exe.launcher as launcher

    runtime_root = tmp_path / "runtime"
    backend_root = runtime_root / "backend"
    backend_root.mkdir(parents=True, exist_ok=True)

    for key in (
        "ASYNC_TASKS_MODE",
        "HOST",
        "PORT",
        "DEBUG",
        "CAD_TRANSLATION_RUNTIME_CONFIG_FILE",
    ):
        monkeypatch.delenv(key, raising=False)

    captured: dict[str, str] = {}
    fake_module = types.SimpleNamespace(main=lambda: 0)

    def fake_import(name: str):
        captured["name"] = name
        captured["async_mode"] = os.environ.get("ASYNC_TASKS_MODE", "")
        captured["host"] = os.environ.get("HOST", "")
        captured["port"] = os.environ.get("PORT", "")
        captured["debug"] = os.environ.get("DEBUG", "")
        captured["runtime_config"] = os.environ.get("CAD_TRANSLATION_RUNTIME_CONFIG_FILE", "")
        return fake_module

    monkeypatch.setattr(launcher.importlib, "import_module", fake_import)

    backend_main = launcher.load_backend_main(runtime_root)

    assert backend_main is fake_module.main
    assert captured["name"] == "run_server"
    assert captured["async_mode"] == "local"
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == "8000"
    assert captured["debug"] == "false"
    assert captured["runtime_config"] == str(runtime_root / "backend" / "config" / "runtime_config.local.json")


def test_pyinstaller_manifest_uses_explicit_dependency_lists() -> None:
    from release_exe import pyinstaller_manifest

    manifest = pyinstaller_manifest.build_manifest()

    assert "pandas" in manifest["hidden_imports"]
    assert "openpyxl" in manifest["hidden_imports"]
    assert "uvicorn.loops.auto" in manifest["hidden_imports"]
    assert "win32com.client" in manifest["hidden_imports"]
    assert "sqlalchemy.dialects.sqlite" in manifest["hidden_imports"]
    assert manifest["collect_submodules"] == []
    assert manifest["collect_all"] == []


def test_build_scale_exe_uses_pyinstaller_onedir_bundle() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "--onedir" in script
    assert "--onefile" not in script


def test_build_scale_exe_nuitka_creates_isolated_sanitized_output(tmp_path: Path) -> None:
    _write_file(tmp_path / "backend" / "run_server.py", "print('backend')\n")
    _write_file(tmp_path / "backend" / ".env", "LLM_API_KEY=sk-live-secret\nOPENROUTER_API_KEY=sk-or-live\n")
    _write_file(
        tmp_path / "backend" / "config" / "runtime_config.local.json",
        json.dumps(
            {
                "api_key": "sk-live-secret",
                "fallback_models": [
                    {
                        "api_key": "nvapi-live-secret",
                        "api_key_source": "config",
                        "api_key_configured": True,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    _write_file(tmp_path / "frontend" / "dist" / "index.html", "<html>runtime</html>\n")
    _write_file(tmp_path / "tools" / "libredwg" / "README.txt", "tool\n")

    result = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(NUITKA_BUILD_SCRIPT),
            "-Root",
            str(tmp_path),
            "-OutDirName",
            "scale_release_exe_nuitka",
            "-SkipNuitka",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout

    output_dir = tmp_path / "scale_release_exe_nuitka"
    assert output_dir.exists()
    assert not (tmp_path / "scale_release_exe").exists()
    assert (output_dir / "launcher.exe").exists()
    payload = output_dir / "runtime_payload.zip"
    assert payload.exists()

    with zipfile.ZipFile(payload) as archive:
        members = set(archive.namelist())
        assert "backend/run_server.py" in members
        assert "frontend/dist/index.html" in members
        assert "backend/.env" not in members
        assert "backend/config/runtime_config.local.json" in members

        runtime_config = json.loads(archive.read("backend/config/runtime_config.local.json").decode("utf-8"))
        assert runtime_config["api_key"] == ""
        assert runtime_config["fallback_models"][0]["api_key"] == ""
        assert runtime_config["fallback_models"][0]["api_key_source"] == "none"
        assert runtime_config["fallback_models"][0]["api_key_configured"] is False


def test_build_scale_exe_nuitka_reuses_build_cache_and_cleans_stale_output(tmp_path: Path) -> None:
    output_dir = tmp_path / "scale_release_exe_nuitka"
    cache_marker = output_dir / "_build" / "nuitka_work" / "cache.marker"
    stale_runtime_file = output_dir / "runtime" / "stale.txt"
    stale_binary_file = output_dir / "launcher.dll"
    stale_root_file = output_dir / "stale.txt"

    _write_file(cache_marker, "keep me\n")
    _write_file(stale_runtime_file, "stale runtime\n")
    _write_file(stale_binary_file, "stale binary\n")
    _write_file(stale_root_file, "stale root\n")

    _write_file(tmp_path / "backend" / "run_server.py", "print('backend')\n")
    _write_file(
        tmp_path / "backend" / "config" / "runtime_config.local.json",
        json.dumps({"api_key": "sk-live-secret"}, ensure_ascii=False, indent=2),
    )
    _write_file(tmp_path / "frontend" / "dist" / "index.html", "<html>runtime</html>\n")
    _write_file(tmp_path / "tools" / "libredwg" / "README.txt", "tool\n")

    result = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(NUITKA_BUILD_SCRIPT),
            "-Root",
            str(tmp_path),
            "-OutDirName",
            "scale_release_exe_nuitka",
            "-SkipNuitka",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert cache_marker.exists()
    assert not stale_runtime_file.exists()
    assert not stale_binary_file.exists()
    assert not stale_root_file.exists()
    assert (output_dir / "launcher.exe").exists()
    assert (output_dir / "runtime_payload.zip").exists()


def test_build_scale_exe_nuitka_uses_nuitka_standalone_bundle() -> None:
    script = NUITKA_BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "-m" in script
    assert "nuitka" in script.lower()
    assert "--mode=standalone" in script
    assert "release_exe\\launcher.py" in script
    assert "_python" not in script
