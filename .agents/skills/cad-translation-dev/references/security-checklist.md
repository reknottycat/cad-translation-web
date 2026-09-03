# Release Security Checklist

Run this read-only checklist against a freshly generated runtime bundle before
publishing it. scale_release/ and scale_release.zip are generated artifacts,
not files to commit.

## Required bundle content

- backend/run_server.py
- backend/app/version.py
- frontend/dist/index.html
- tools/libredwg/0.13.3-win64/dwg2dxf.exe
- cli/cad_translate/cli.py and cli/setup.py
- cad-cli.bat, install_cli.bat, CLI.md, start_delivery.bat
- requirements.txt

## Forbidden content

- databases: *.db, *.sqlite, *.sqlite3
- .env or non-example .env.* files
- runtime_config.local.json, local settings, API keys, logs
- outputs/, uploads/, temp/, logs/
- .venv/, venv/, env/, node_modules/, __pycache__/, pytest/mypy/ruff caches
- .pyc, .egg-info, tests/, test/, testing/, test_*.py, conftest.py
- frontend/src/ and Electron files at the bundle root

frontend/dist/ is intentional and must be present. The bundled CLI files are
intentional runtime content and must not be rejected as development files.

## Audit and smoke commands

From the repository root:

~~~powershell
& .\.agents\skills\cad-translation-dev\scripts\security-audit.ps1 -ReleaseDir <bundle-path>
~~~

Then, in a clean runtime environment:

~~~powershell
cad-cli.bat --version
cad-cli.bat --help
cad-cli.bat doctor
~~~

Check the directory and ZIP separately. Verify the CLI and backend use the
same SemVer value from backend/app/version.py, record the ZIP SHA-256, and
confirm the GitHub Release asset matches the audited ZIP.

Never fix a bundle by editing scale_release files or by recursively deleting an
unresolved OneDrive path. Fix the source/build script, rebuild, and audit again.
