# Scale Release EXE Design

**Goal:** Add a second, isolated delivery pipeline that produces a portable Windows launcher EXE without changing the first-stage `scale_release` workflow.

## Approved Direction

- Keep the current `scale_release/` and `scripts/build_scale.ps1` flow as stage one.
- Create a separate stage-two folder and script:
  - `release_exe/`
  - `scripts/build_scale_exe.ps1`
- Build a single visible `launcher.exe` with a console window.
- Bundle a Python runtime via PyInstaller.
- Only sanitize API keys in the stage-two delivery copy, never in the source `backend/`.

## Runtime Model

The EXE is the only user-facing entrypoint. On launch it should:

- print the EXE location, runtime directory, backend path, frontend path, and service URL
- materialize a sanitized runtime bundle under the stage-two output directory
- start the backend in single-process mode
- wait for the backend health endpoint to respond
- open the browser to `http://127.0.0.1:8000/`
- shut down the backend when the console is closed

## Packaging Model

The stage-two pipeline should output to `scale_release_exe/` and be independent of `scale_release/`.

Recommended contents:

- `launcher.exe`
- `runtime_payload.zip` or an equivalent packaged runtime asset used only by the launcher
- minimal README for EXE usage

The runtime payload is produced from a sanitized copy of the first-stage runtime bundle. Sensitive local configuration such as `.env` and `runtime_config.local.json` must be sanitized or excluded inside that payload.

## Why This Shape

- It preserves the known-good first-stage runtime delivery flow.
- It avoids touching the user’s source `backend` config.
- It keeps the visible user story simple: one EXE, one console, one browser.
- It gives us a controlled place to perform sanitization only for distributed artifacts.

## Verification

- Unit or integration tests should verify the stage-two script creates `scale_release_exe/`.
- Tests should assert the stage-two runtime payload excludes or sanitizes API keys.
- The real build should verify `launcher.exe` exists and the packaged runtime includes the expected backend/frontend assets.
