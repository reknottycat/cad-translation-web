# CAD Translation Runtime Bundle

`scale_release/` is the runtime bundle for end users.

It is a runnable delivery package, not a source checkout. The bundle keeps the backend runtime, the built frontend static files, the required tools, and the one-click launcher.

## Included

- `backend/`: backend runtime code
- `frontend/dist/`: built frontend assets
- `tools/`: runtime helper tools
- `docs/modern/`: cleaned release documentation
- `start_delivery.bat`: one-click launcher
- `requirements.txt`: Python dependency list

## Start

- Install Python 3.10 or newer.
- Install dependencies with `pip install -r requirements.txt`.
- Double-click `start_delivery.bat`.
- The launcher opens `http://127.0.0.1:8000/` in your browser.

## Notes

- The launcher runs the backend in single-process mode.
- The frontend is served from the packaged `frontend/dist` folder.
- This runtime bundle intentionally excludes development-only files such as frontend source, tests, and `agent-harness`.
