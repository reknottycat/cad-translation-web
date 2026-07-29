# Scale Release Runtime Delivery Design

**Goal:** Rebuild `scale_release` as an end-user runtime bundle that launches with one double-click entrypoint, serves the built frontend from the backend, and avoids shipping development-only material.

## Approved Direction

- Delivery bundle keeps only runtime assets.
- Frontend is shipped as built static files under `frontend/dist`.
- Backend runs in a single process.
- End users launch the package by double-clicking `start_delivery.bat`.
- The launcher prints backend and frontend paths in the console window and opens the browser automatically.
- A later phase can wrap the launcher as a Windows `.exe`.

## Bundle Shape

The generated `scale_release/` directory should contain:

- `backend/` runtime code and backend requirements
- `frontend/dist/` built frontend assets only
- `tools/` runtime helper binaries and assets
- `docs/modern/` cleaned operational docs
- `README.md` generated for end-user handoff
- `start_delivery.bat`
- `requirements.txt`

It should exclude:

- `frontend/src`
- `frontend/node_modules`
- `agent-harness`
- tests, caches, databases, `.env`, logs, and historical delivery material

## Runtime Behavior

- `start_delivery.bat` becomes the single visible launch entrypoint.
- The launcher sets single-process runtime defaults such as `ASYNC_TASKS_MODE=local` and `HOST=127.0.0.1`.
- The launcher prints:
  - delivery root
  - backend entry path
  - frontend dist path
  - service URL
- The backend remains responsible for serving `/`, `/assets/*`, and `/api/*`.

## Implementation Notes

- Keep the current FastAPI static asset mounting model and make the release build guarantee that `frontend/dist` exists.
- Refactor `scripts/build_scale.ps1` from a source-copy script into a runtime-bundle assembler.
- Build the frontend during packaging unless explicitly skipped for tests.
- Generate the top-level delivery README during packaging so the shipped instructions always match the latest runtime model.

## Verification

- Add an automated packaging test that runs `scripts/build_scale.ps1` against a synthetic repo tree.
- Verify the package contains runtime-only content and excludes development-only files.
- Run the real packaging script in this workspace to produce a refreshed `scale_release/` and `scale_release.zip`.
