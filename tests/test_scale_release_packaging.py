from __future__ import annotations

import subprocess
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT_DIR / "scripts" / "build_scale.ps1"


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_build_scale_creates_runtime_only_package(tmp_path: Path) -> None:
    _write_file(tmp_path / "backend" / "run_server.py", "print('backend')\n")
    _write_file(tmp_path / "backend" / "app" / "main.py", "app = object()\n")
    _write_file(tmp_path / "backend" / ".env.example", "HOST=127.0.0.1\n")
    _write_file(tmp_path / "backend" / "runtime.db", "db")
    _write_file(tmp_path / "frontend" / "dist" / "index.html", "<html>runtime</html>\n")
    _write_file(tmp_path / "frontend" / "dist" / "assets" / "app.js", "console.log('runtime');\n")
    _write_file(tmp_path / "frontend" / "src" / "App.tsx", "export const App = () => null;\n")
    _write_file(tmp_path / "tools" / "libredwg" / "README.txt", "tool\n")
    _write_file(tmp_path / "docs" / "modern" / "README.md", "# modern docs\n")
    _write_file(tmp_path / "docs" / "modern" / "ARCHITECTURE.md", "# architecture\n")
    _write_file(tmp_path / "requirements.txt", "fastapi\n")
    _write_file(tmp_path / "README.md", "# source readme\n")
    _write_file(tmp_path / "start_delivery.bat", "@echo off\n")
    _write_file(tmp_path / "agent-harness" / "setup.py", "print('dev only')\n")

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
            "scale_release",
            "-ZipName",
            "scale_release.zip",
            "-SkipFrontendBuild",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout

    package_root = tmp_path / "scale_release"
    assert package_root.exists()
    assert (tmp_path / "scale_release.zip").exists()

    assert (package_root / "backend" / "run_server.py").exists()
    assert (package_root / "frontend" / "dist" / "index.html").exists()
    assert (package_root / "tools" / "libredwg" / "README.txt").exists()
    assert (package_root / "docs" / "modern" / "README.md").exists()

    assert not (package_root / "frontend" / "src").exists()
    assert not (package_root / "agent-harness").exists()
    assert not (package_root / "backend" / "runtime.db").exists()

    launcher = (package_root / "start_delivery.bat").read_text(encoding="utf-8")
    assert "Backend entry:" in launcher
    assert "Frontend dist:" in launcher
    assert "ASYNC_TASKS_MODE=local" in launcher

    package_readme = (package_root / "README.md").read_text(encoding="utf-8")
    assert "runtime bundle" in package_readme.lower()
    assert "Double-click `start_delivery.bat`" in package_readme
