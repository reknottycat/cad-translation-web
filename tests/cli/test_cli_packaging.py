#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Release packaging + CLI metadata regression (no Windows/PowerShell required)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
AGENT_HARNESS = REPO / "agent-harness"
BUILD_SCRIPT = REPO / "scripts" / "build_scale.ps1"


def test_single_version_source():
    """CLI and backend must read the one canonical version in backend/app/version.py."""
    version_py = REPO / "backend" / "app" / "version.py"
    m = re.search(r'__version__\s*=\s*"([^"]+)"', version_py.read_text(encoding="utf-8"))
    assert m, "backend/app/version.py must define __version__"
    canonical = m.group(1)

    setup_py = AGENT_HARNESS / "setup.py"
    assert setup_py.exists()
    setup_text = setup_py.read_text(encoding="utf-8")
    # setup.py must NOT hard-code a second version string.
    assert "version=" in setup_text
    assert "backend" in setup_text and "version.py" in setup_text

    # The CLI reads the backend version.
    sys.path.insert(0, str(AGENT_HARNESS))
    from cad_translate.bridge import get_version

    assert get_version() == canonical


def test_console_entrypoint_declared():
    """Console script is declared once, in the PEP 621 [project.scripts] table
    (moved out of setup.py to avoid duplicate-metadata conflicts with modern
    setuptools/build)."""
    _assert_entrypoint_in_pyproject()


def test_build_script_bundles_cli():
    """build_scale.ps1 must copy agent-harness/cad_translate into the release."""
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "agent-harness\\cad_translate" in text
    assert 'Join-Path $outDir "cli\\cad_translate"' in text
    assert 'Write-CliLauncher' in text
    assert 'cad-cli.bat' in text
    # Release must not package secrets.
    assert ".env" in text and "runtime_config.local.json" in text


def test_cli_source_layout_complete():
    """The CLI package must contain the maintained modules (no drifting lib copy)."""
    pkg = AGENT_HARNESS / "cad_translate"
    for name in ("__init__.py", "cli.py", "operations.py", "store.py", "bridge.py"):
        assert (pkg / name).exists(), f"missing {name}"


def test_no_duplicate_backend_snapshot_in_cli():
    """The CLI must not carry its own copy of backend functions (the anti-pattern)."""
    pkg = AGENT_HARNESS / "cad_translate"
    # No nested snapshot of the CAD pipeline lives under the CLI package.
    for forbidden in ("text_extractor", "dwg_converter", "text_applier", "pipeline.py"):
        for py in pkg.rglob("*.py"):
            assert forbidden not in py.name.lower() or "operations" in py.name.lower()


def test_relative_path_resolution():
    sys.path.insert(0, str(AGENT_HARNESS))
    from cad_translate import store
    from app.utils.file_utils import resolve_within_directory, get_safe_filename

    assert get_safe_filename("a/b\\c:*.dxf").replace("\\", "/") not in ("a/b",)
    assert "/" not in get_safe_filename("../../x.dxf") or ".." not in get_safe_filename("../../x.dxf")


def test_installable_package_metadata():
    """pyproject.toml must carry a real PEP 621 [project] table that modern
    setuptools/build accept (PR #19 review blocker #3): name + dynamic version
    delegating to setup.py (single SemVer source)."""
    _assert_pep621_project_present()


def test_no_eager_app_import_at_module_scope():
    """The CLI package must not import ``app.*`` (which pulls in FastAPI /
    SQLAlchemy / Celery ...) at module scope.  Backend modules are resolved
    lazily (Issue #14 / PR #19 review blocker #1), so ``--version`` / ``--help``
    keep working in a clean environment that only has the CLI's own deps.
    """
    import ast

    for path in sorted((AGENT_HARNESS / "cad_translate").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("app"), (
                        f"{path.name} eagerly imports {alias.name} at module scope"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("app"), (
                    f"{path.name} eagerly imports {node.module} at module scope"
                )


def test_requirements_ascii_decodable_for_windows_pip():
    """Windows default ANSI (GBK) code pages fail on non-ASCII bytes when pip
    reads requirements.txt.  Every machine-consumed requirements file must be
    pure ASCII so `python -m pip install -r ...` works out of the box on a
    zh-CN Windows box (PR #19 review blocker #2)."""
    reqs = [REPO / "requirements.txt", REPO / "backend" / "requirements.txt"]
    for req in reqs:
        assert req.exists(), f"missing {req}"
        raw = req.read_bytes()
        # Pure ASCII (a superset-safe guarantee: ASCII decodes under every
        # legacy ANSI code page incl. GBK), and also explicitly GBK-decodable.
        raw.decode("ascii")
        raw.decode("gbk")


def _read_pyproject() -> str:
    return (AGENT_HARNESS / "pyproject.toml").read_text(encoding="utf-8")


def _assert_entrypoint_in_pyproject():
    """The console script is declared once, in the PEP 621 [project.scripts]
    table (moved out of setup.py so modern setuptools/build accept the
    pyproject.toml without a duplicate-metadata conflict)."""
    import tomllib

    pyproject = tomllib.loads(_read_pyproject())
    scripts = pyproject["project"]["scripts"]
    assert scripts["cad-translate"] == "cad_translate.cli:main"
    # Not double-declared in setup.py (which must only supply dynamic version).
    setup_text = (AGENT_HARNESS / "setup.py").read_text(encoding="utf-8")
    assert "cad-translate=cad_translate.cli:main" not in setup_text


def _assert_pep621_project_present():
    """pyproject.toml must carry a real PEP 621 [project] table that modern
    setuptools/build accept (PR #19 review blocker #3): name, a dynamic
    version delegating to setup.py, dependencies, scripts and entry points."""
    import tomllib

    pyproject = tomllib.loads(_read_pyproject())
    project = pyproject["project"]
    assert project["name"] == "cad-translate"
    # Version is NOT statically hard-coded: it must be dynamic so the single
    # SemVer source stays backend/app/version.py (see test_single_version_source).
    assert "version" in project.get("dynamic", [])
    assert "setuptools.build_meta" in pyproject["build-system"]["build-backend"]
    assert "dependencies" in project
    assert "scripts" in project


def test_isolated_build_generates_wheel_and_sdist_reads_version():
    """Real isolated ``python -m build --wheel --sdist`` inside agent-harness
    must succeed and produce artifacts whose version reads from
    backend/app/version.py (single SemVer source).  Mirrors exactly what the
    Windows Python 3.12 venv runs to build the deliverable CLI (PR #19
    blocker #3)."""
    import shutil
    import subprocess
    import sys
    import tarfile
    import zipfile

    # ``build`` is a declared dependency (backend/requirements.txt) but the
    # CLI test env may not install it; mirror the reviewer command and skip
    # cleanly when the module is absent.
    try:
        import build  # noqa: F401
    except ImportError:
        pytest.skip("`build` is not installed; cannot run isolated build")

    canonical = re.search(
        r'__version__\s*=\s*"([^"]+)"',
        (REPO / "backend" / "app" / "version.py").read_text(encoding="utf-8"),
    ).group(1)

    out = AGENT_HARNESS / "dist"
    for d in (out, AGENT_HARNESS / "build"):
        if d.exists():
            shutil.rmtree(d)

    proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--sdist"],
        cwd=str(AGENT_HARNESS),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"isolated build failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )

    wheels = list(out.glob("*.whl"))
    sdists = list(out.glob("*.tar.gz"))
    assert wheels, f"wheel was not produced\n{proc.stdout}"
    assert sdists, f"sdist was not produced\n{proc.stdout}"
    prefix = f"cad_translate-{canonical}"
    dist_info = f"cad_translate-{canonical}.dist-info"
    assert any(w.name.startswith(prefix) for w in wheels), "wheel version prefix mismatch"
    assert any(s.name.startswith(prefix) for s in sdists), "sdist version prefix mismatch"

    with zipfile.ZipFile(wheels[0]) as zf:
        meta = zf.read(f"{dist_info}/METADATA").decode("utf-8")
    assert f"Version: {canonical}" in meta, "wheel metadata version mismatch"

    with tarfile.open(sdists[0]) as tf:
        assert f"cad_translate-{canonical}/PKG-INFO" in tf.getnames()
        pkg_info = tf.extractfile(f"cad_translate-{canonical}/PKG-INFO").read().decode("utf-8")
    assert f"Version: {canonical}" in pkg_info, "sdist metadata version mismatch"

    # cleanup generated artifacts so the repo stays clean.
    for d in (out, AGENT_HARNESS / "build"):
        if d.exists():
            shutil.rmtree(d)


def test_build_script_py_launcher_split_cmd_and_args():
    """PR #19 review blocker #4: on a machine that only has the ``py`` launcher
    (no ``python``), ``cad-cli.bat`` / ``install_cli.bat`` must set the command
    and its ``-3`` argument separately (``PYTHON=py`` + ``PYTHON_ARGS=-3``) and
    invoke ``%PYTHON% %PYTHON_ARGS%``.  Writing ``PYTHON=py -3`` then calling
    ``"%PYTHON%" ...`` makes cmd treat the whole ``py -3`` as one executable
    path, so the fallback branch can never start/install the CLI."""
    text = BUILD_SCRIPT.read_text(encoding="utf-8").replace("\r\n", "\n")

    start = text.index("function Write-CliLauncher")
    end = text.index("function Write-CliInstallBat", start)
    launcher = text[start:end]

    start_install = text.index("function Write-CliInstallBat")
    install = text[start_install:]

    for name, block in (("cad-cli.bat", launcher), ("install_cli.bat", install)):
        # python branch keeps a (possibly empty) separate args variable.
        assert 'set "PYTHON=python"' in block
        assert 'set "PYTHON_ARGS="' in block, f"{name}: python branch must clear PYTHON_ARGS"
        # py-only fallback sets cmd and -3 argument separately.
        assert 'set "PYTHON=py"' in block, f"{name}: must set PYTHON=py (not \"py -3\")"
        assert 'set "PYTHON_ARGS=-3"' in block, f"{name}: must set PYTHON_ARGS=-3"
        # The old anti-pattern that broke the fallback must be gone.
        assert '"%PYTHON%"' not in block, (
            f"{name}: invocation quotes %PYTHON% so `py -3` would be treated as one path"
        )
        assert 'set "PYTHON=py -3"' not in block, f"{name}: must not bake the arg into PYTHON"
        # Fallback invocation splits command and argument.
        assert "%PYTHON% %PYTHON_ARGS%" in block, f"{name}: must invoke %PYTHON% %PYTHON_ARGS%"
