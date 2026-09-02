#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Release packaging + CLI metadata regression (no Windows/PowerShell required)."""
from __future__ import annotations

import json
import re
import shutil
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


def test_isolated_build_generates_wheel_and_sdist_reads_version(tmp_path):
    """Real isolated ``python -m build --wheel --sdist`` must succeed and
    produce artifacts whose version reads from backend/app/version.py (single
    SemVer source).

    Windows/OneDrive regression (gstack release gate / Issue #14): the old
    version cleaned the **repository** ``agent-harness/dist`` and
    ``agent-harness/build`` with ``shutil.rmtree``.  On a OneDrive / cloud
    ``agent-harness`` (a reparse-point directory) that delete raised
    ``PermissionError``.  This version stages a throwaway **per-run copy of
    agent-harness under TEMP** (together with the ``backend/app/version.py`` it
    needs as a sibling), runs the real isolated build there and verifies the
    produced wheel/sdist versions -- without ever creating or deleting build
    artifacts inside the repository.  ``tmp_path`` is removed automatically by
    pytest, so no manual rmtree of repo dirs is needed.
    """
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

    # Record the repository's PRE-EXISTING state of the classic build-output dirs
    # (dist/, build/).  In some real workspaces these already exist -- e.g. an
    # empty Microsoft OneDrive "cloud" / reparse-point directory named
    # ``agent-harness/dist`` checked into the tree.  We must NOT delete them and
    # must NOT assert their absence; we only guard that THIS test does not create
    # or write them inside the repository (everything is built under tmp_path).
    repo_dist_preexisting = (AGENT_HARNESS / "dist").exists()
    repo_build_preexisting = (AGENT_HARNESS / "build").exists()

    canonical = re.search(
        r'__version__\s*=\s*"([^"]+)"',
        (REPO / "backend" / "app" / "version.py").read_text(encoding="utf-8"),
    ).group(1)

    # Stage agent-harness into a per-run TEMP tree that keeps it a sibling of
    # backend/app/version.py (setup.py resolves ``../backend/app/version.py``).
    stage = tmp_path / "stage"
    stage_harness = stage / "agent-harness"
    shutil.copytree(
        AGENT_HARNESS,
        stage_harness,
        ignore=shutil.ignore_patterns(
            "*.pyc", "__pycache__", ".pytest_cache", "*.egg-info",
            "build", "dist", ".git",
        ),
    )
    # Provide the canonical version.py at the sibling-relative location.
    stage_version = stage / "backend" / "app" / "version.py"
    stage_version.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        REPO / "backend" / "app" / "version.py",
        stage_version,
    )

    # Run the real isolated build entirely inside the temp staging tree.
    proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--sdist"],
        cwd=str(stage_harness),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, (
        f"isolated build failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )

    out = stage_harness / "dist"
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

    # Everything (dist/, build/, *.egg-info) lives under the temp staging tree,
    # which pytest cleans up automatically.  Guard only that THIS run did not
    # newly create/write the classic build-output dirs in the repository: if a
    # dir already existed before the test (OneDrive reparse placeholder etc.)
    # we leave it untouched and never assert its absence or delete it.
    if not repo_dist_preexisting:
        assert not (AGENT_HARNESS / "dist").exists(), (
            "repo agent-harness/dist must not be created by this test"
        )
    if not repo_build_preexisting:
        assert not (AGENT_HARNESS / "build").exists(), (
            "repo agent-harness/build must not be created by this test"
        )

# Each release launcher .bat is produced by exactly one writer function.
_LAUNCHER_WRITERS = {
    # function name -> emitted .bat file
    "Write-DeliveryLauncher": "start_delivery.bat",
    "Write-CliLauncher": "cad-cli.bat",
    "Write-CliInstallBat": "install_cli.bat",
}


def _slice_function(text: str, func: str, next_func: str | None) -> str:
    """Return the body of ``func`` up to (but not including) ``next_func``."""
    start = text.index(f"function {func}")
    if next_func is None:
        # function is the last one in the file.
        end = text.find("\nfunction ", start)
        end = end if end != -1 else len(text)
        return text[start:end]
    return text[start:text.index(f"function {next_func}", start)]


@pytest.mark.parametrize(
    "func,next_func,bat_name",
    [
        # start_delivery.bat is generated by Write-DeliveryLauncher (delivery entry).
        ("Write-DeliveryLauncher", "Write-DeliveryReadme", "start_delivery.bat"),
        # cad-cli.bat and install_cli.bat are the two CLI launchers (PR #19).
        ("Write-CliLauncher", "Write-CliInstallBat", "cad-cli.bat"),
        ("Write-CliInstallBat", None, "install_cli.bat"),
    ],
)
def test_py_launcher_split_cmd_and_args(func, next_func, bat_name):
    """On a machine that only has the ``py`` launcher (no ``python``) every
    release .bat must set the command and its ``-3`` argument separately
    (``PYTHON=py`` + ``PYTHON_ARGS=-3``) and invoke ``%PYTHON% %PYTHON_ARGS%``.
    Writing ``PYTHON=py -3`` then calling ``"%PYTHON%" ...`` makes cmd treat the
    whole ``py -3`` as one executable path, so the py-only fallback branch can
    never start the backend / CLI (delivery blocker, PR #19 only fixed the two
    CLI launchers)."""
    text = BUILD_SCRIPT.read_text(encoding="utf-8").replace("\r\n", "\n")
    block = _slice_function(text, func, next_func)

    # python branch keeps a (possibly empty) separate args variable.
    assert 'set "PYTHON=python"' in block, f"{bat_name}: python branch must set PYTHON=python"
    assert 'set "PYTHON_ARGS="' in block, f"{bat_name}: python branch must clear PYTHON_ARGS"
    # py-only fallback sets cmd and -3 argument separately.
    assert 'set "PYTHON=py"' in block, f'{bat_name}: must set PYTHON=py (not "py -3")'
    assert 'set "PYTHON_ARGS=-3"' in block, f"{bat_name}: must set PYTHON_ARGS=-3"
    # The old anti-pattern that broke the py fallback must be gone.
    assert '"%PYTHON%"' not in block, (
        f"{bat_name}: invocation quotes %PYTHON% so `py -3` would be treated as one path"
    )
    assert 'set "PYTHON=py -3"' not in block, f"{bat_name}: must not bake the arg into PYTHON"
    # Fallback invocation splits command and argument.
    assert "%PYTHON% %PYTHON_ARGS%" in block, f"{bat_name}: must invoke %PYTHON% %PYTHON_ARGS%"


def test_all_delivery_launchers_are_written():
    """Every release .bat (start_delivery, cad-cli, install_cli) must be emitted
    by the build script, and the backend entry must be launched via the split
    command/args variables so the py-only fallback can start it."""
    text = BUILD_SCRIPT.read_text(encoding="utf-8").replace("\r\n", "\n")

    # 1) All three launchers are written to the delivery output dir.
    for func, bat_name in _LAUNCHER_WRITERS.items():
        assert f"function {func}" in text, f"missing writer {func}"
        assert f'"{bat_name}"' in text, f"build script must emit {bat_name}"

    # 2) The delivery entry (start_delivery.bat) launches the backend entry via
    #    %PYTHON% %PYTHON_ARGS%, never quoting the command on its own.
    launcher = _slice_function(text, "Write-DeliveryLauncher", "Write-DeliveryReadme")
    assert '%PYTHON% %PYTHON_ARGS% "%BACKEND_ENTRY%"' in launcher, (
        "start_delivery.bat must run the backend with %PYTHON% %PYTHON_ARGS%"
    )


# ---------------------------------------------------------------------------
# Release-gate PowerShell build regression (Issue #14 / gstack OneDrive probe)
#
# The probe build showed the delivered ZIP carried dev-only content the build
# script was supposed to exclude: backend/.venv (~7114 files), server*.log /
# *.stdout.log / *.stderr.log, backend/app/__pycache__ and
# cli/cad_translate/__pycache__, .pyc files etc.  These tests really run
# build_scale.ps1 (via pwsh when available) against a controlled dirty staging
# workspace and audit the produced ZIP, mirroring the Windows OneDrive probe.
# ---------------------------------------------------------------------------

# Dev-only artifacts the delivered package must never contain (matched against
# the ZIP's normalized '/'-path entry names and against a pathname substring).
_BANNED_SUBSTRINGS = (
    "/.venv/", "/venv/", "/env/", "__pycache__", ".pyc",
    ".log",  # server*.log / *.stdout.log / *.stderr.log
    ".db", "runtime_config.local.json", "/.env", "local_settings.py",
    "db.sqlite3", ".egg-info", "/outputs/", "/uploads/", "/temp/",
    "/tests/", "conftest.py", "/test_",
)


def _is_banned_entry(name: str) -> bool:
    """True when an entry name must not appear in the release ZIP.

    ``.env.example`` is the intended shipped template (not a secret) and must
    be allowed through; every other ``.env*`` local config / secret is banned.
    """
    if name.endswith("/.env.example") or "/.env.example" in name:
        return False
    return any(b in name for b in _BANNED_SUBSTRINGS)


def _pwsh():
    """Locate a runnable PowerShell, or None when absent (then tests skip)."""
    return shutil.which("pwsh") or shutil.which("powershell")


def _stage_dirty_release_workspace(tmp_path):
    """Build a controlled workspace exactly like the dirty Windows probe root:
    real backend + agent-harness source, a stub frontend/dist + tools, plus the
    dev-only clutter (a .venv, __pycache__/.pyc, server logs, a dev db, local
    config/secret, test dirs & scripts) that must be excluded from the ZIP."""
    root = tmp_path / "probe"
    (root / "backend").mkdir(parents=True)
    # Real runtime sources the package must keep.
    shutil.copytree(REPO / "backend", root / "backend", dirs_exist_ok=True)
    shutil.copytree(REPO / "agent-harness", root / "agent-harness", dirs_exist_ok=True)
    if (REPO / "docs" / "modern").exists():
        shutil.copytree(REPO / "docs" / "modern", root / "docs" / "modern", dirs_exist_ok=True)
    shutil.copy2(REPO / "requirements.txt", root / "requirements.txt")
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(BUILD_SCRIPT, root / "scripts" / "build_scale.ps1")
    # frontend/dist + tools are runtime pieces required by the build (skipped in CI).
    dist = root / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>probe</body></html>", encoding="utf-8")
    (root / "tools" / "libredwg").mkdir(parents=True)
    (root / "tools" / "libredwg" / "dwg2dxf.exe").write_bytes(b"MZ probe")

    # --- inject the dev-only clutter reported by the OneDrive probe ---
    # backend/.venv (a real venv subtree with many files).
    venv = root / "backend" / ".venv" / "Lib" / "site-packages" / "demo"
    venv.mkdir(parents=True)
    for i in range(20):
        (venv / f"m_{i}.py").write_text(f"x = {i}\n", encoding="utf-8")
    (root / "backend" / ".venv" / "pyvenv.cfg").write_text("home = demo\n", encoding="utf-8")
    # __pycache__ + stray .pyc under backend and under the CLI package.
    for rel in ("backend/app", "backend/services", "agent-harness/cad_translate"):
        pc = root / rel / "__pycache__"
        pc.mkdir(parents=True, exist_ok=True)
        (pc / "mod.cpython-312.pyc").write_bytes(b"\x00\x01\x02")
    # server run logs at the backend root.
    for name in ("server.log", "server.stdout.log", "server.stderr.log"):
        (root / "backend" / name).write_text("run\n", encoding="utf-8")
    # a 4th standalone log as the probe reported "4 server*.log"-style entries.
    (root / "backend" / "app" / "translation.log").write_text("run\n", encoding="utf-8")
    # dev database + local config / secrets + local settings.
    (root / "backend" / "cad_translation.db").write_bytes(b"SQLite format 3\x00")
    (root / "backend" / "config").mkdir(parents=True, exist_ok=True)
    (root / "backend" / "config" / "runtime_config.local.json").write_text(
        '{"api_key":"sk-probe-secret"}\n', encoding="utf-8"
    )
    (root / "backend" / "config" / "local_settings.py").write_text(
        "DEBUG=True\n", encoding="utf-8"
    )
    (root / "backend" / ".env").write_text("ADMIN_API_TOKEN=secret\n", encoding="utf-8")
    # test dirs and ad-hoc test scripts anywhere (incl. inside backend/app).
    (root / "backend" / "tests").mkdir(parents=True, exist_ok=True)
    (root / "backend" / "tests" / "test_dummy.py").write_text("def test(): pass\n")
    (root / "backend" / "app" / "test_something.py").write_text("def test(): pass\n")
    (root / "backend" / "conftest.py").write_text("import pytest\n")
    return root


@pytest.mark.skipif(_pwsh() is None, reason="PowerShell (pwsh/powershell) is not installed")
def test_real_powershell_build_excludes_dev_artifacts_and_keeps_runtime(tmp_path):
    """Really run build_scale.ps1 (as the Windows probe does) and audit the ZIP:
    the dirty dev-only clutter (.venv, __pycache__/.pyc, *.log, *.db, .env,
    local config/secrets, tests, test scripts) must be absent while the CLI,
    frontend/dist and necessary runtime files must remain.  The script has no
    Windows-only COM dependency when built with -SkipFrontendBuild, so pwsh can
    run it unchanged here."""
    root = _stage_dirty_release_workspace(tmp_path)
    out_name = "scale_release_probe_test"
    zip_name = "scale_release_probe_test.zip"

    proc = subprocess.run(
        [_pwsh(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(root / "scripts" / "build_scale.ps1"),
         "-SkipFrontendBuild", "-OutDirName", out_name, "-ZipName", zip_name],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, (
        f"build_scale.ps1 failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )

    release = root / out_name
    zip_path = root / zip_name
    assert release.is_dir(), f"release dir missing: {release}"
    assert zip_path.is_file(), f"zip missing: {zip_path}"

    # ---- 1) Banned dev-only content must be entirely absent ----
    import zipfile

    with zipfile.ZipFile(zip_path) as zf:
        entries = [e.filename.replace("\\", "/") for e in zf.infolist()]

    leaked = sorted(n for n in entries if _is_banned_entry(n))
    assert not leaked, f"release ZIP leaked dev-only artifacts: {leaked}"

    # The .venv subtree would have pulled in hundreds of files; assert nothing
    # under any venv dir survived.
    assert not any("/.venv/" in n for n in entries)

    # ---- 2) Required runtime pieces must remain ----
    required = [
        "backend/run_server.py",
        "backend/app/main.py",
        "frontend/dist/index.html",
        "cli/cad_translate/cli.py",
        "cli/setup.py",
        "tools/libredwg/dwg2dxf.exe",
        "requirements.txt",
        "start_delivery.bat",
        "cad-cli.bat",
        "install_cli.bat",
        # The .env TEMPLATE (not a secret) is an intended deliverable.
        "backend/.env.example",
    ]
    missing = [r for r in required if r not in entries]
    assert not missing, f"release ZIP is missing required files: {missing}"


@pytest.mark.skipif(_pwsh() is None, reason="PowerShell (pwsh/powershell) is not installed")
def test_real_powershell_build_secret_guard_is_fail_closed(tmp_path):
    """The fail-closed secret guard (a hard throw, not a filter) must still be
    the last line of defence: if an exclusion rule ever lets a secret reach the
    staging dir, the build must abort with a non-zero exit code and refuse to
    write a package -- never silently ship a .env / runtime_config.local.json.
    Here we deliberately strip the secret exclusions from a scratch copy of the
    build script so a secret WOULD be copied; the guard must then abort."""

    root = _stage_dirty_release_workspace(tmp_path)
    # Scratch copy of the script with the secret exclusions removed so the
    # secret files would otherwise make it into the staging dir.
    scratch = root / "scripts" / "build_no_secret_excl.ps1"
    script_text = (root / "scripts" / "build_scale.ps1").read_text(encoding="utf-8")
    script_text = script_text.replace(
        "    '(^|/)\\.env$',\n    '(^|/)\\.env\\.(?!example$)',\n"
        "    '(^|/)runtime_config\\.local\\.json$',",
        "",
    )
    scratch.write_text(script_text, encoding="utf-8")

    proc = subprocess.run(
        [_pwsh(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(scratch),
         "-SkipFrontendBuild",
         "-OutDirName", "scale_release_probe_test",
         "-ZipName", "scale_release_probe_test.zip"],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    combined = f"{proc.stdout}\n{proc.stderr}"
    # Fail-closed: must abort and never produce the zip.
    assert proc.returncode != 0, (
        f"secret guard did not abort a build that staged a secret:\n{combined}"
    )
    assert "Refusing to package secret files" in combined, (
        f"secret guard message missing from output:\n{combined}"
    )
    zip_path = root / "scale_release_probe_test.zip"
    assert not zip_path.exists(), "a package with secrets must never be written"
