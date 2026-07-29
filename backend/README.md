# Backend

This folder contains the FastAPI + Celery backend used by the CAD translation workspace.

## What it does

- Converts DWG files to DXF when a converter backend is available
- Extracts DXF text into Excel
- Applies translated text back into DXF
- Stores project and task state
- Supports the shared runtime configuration used by the CLI package

## Dependencies

Install the backend dependencies from this folder:

```bash
cd backend
pip install -r requirements.txt
```

The same dependency set also covers the installable CLI package under `agent-harness/cli_anything/cad/`, because the CLI imports backend modules directly.

## Run the API

```bash
python run_server.py
```

Optional Celery worker:

```bash
python run_celery.py
```

## Admin access token

Dangerous routes such as task cleanup and project clearing are unguarded by default for internal deployments.

To enable the admin guard, set both `ENABLE_ADMIN_GUARD=true` and `ADMIN_API_TOKEN` in `backend/.env`, then send the token with either:

- `X-Admin-Token: <token>`
- `Authorization: Bearer <token>`

`JWT_SECRET_KEY` is not used as an admin token fallback.

## Related package

The installable CLI lives in `agent-harness/cli_anything/cad/` and is exposed as `cli-anything-cad`.

Install it separately with:

```bash
cd agent-harness
pip install -e .
```

For the full command reference, see `agent-harness/cli_anything/cad/README.md`.
