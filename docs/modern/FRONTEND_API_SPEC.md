# Frontend API Spec

This document describes the frontend routes and the backend endpoints currently consumed by the web client.

Reference:
- Backend source of truth: [BACKEND_API_SPEC.md](./BACKEND_API_SPEC.md)

## Scope

- Frontend app entry: `frontend/src/App.tsx`
- App shell: `frontend/src/components/Layout.tsx`
- Service layer: `frontend/src/services/api.ts`
- Main pages:
  - `frontend/src/pages/HomePage.tsx`
  - `frontend/src/pages/TranslationPage.tsx`
  - `frontend/src/components/CADWorkflow.tsx`
  - `frontend/src/pages/ProjectsPage.tsx`
  - `frontend/src/pages/ModelGatewayPage.tsx`

## Base URL

Frontend uses `VITE_API_BASE_URL` when present. Fallback is `/api`.

Example:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000/api
```

## Frontend Routes

| Route | Page | Purpose |
| --- | --- | --- |
| `/` | Overview Dashboard | Health, runtime summary, project summary, recent task feed |
| `/translation` | Translation Lab | Text translation and Excel translation |
| `/cad` | CAD Workspace | Extract, translate, apply and download CAD output |
| `/projects` | Projects Center | Task history, summary stats, downloads, delete |
| `/gateway` | Model Gateway | Provider, endpoint, model and runtime config |

## Service Layer

Service wrapper lives in `frontend/src/services/api.ts`.

### Common

- Axios interceptor unwraps `response.data`
- Page code receives JSON bodies directly
- Error helper reads backend fields in this order:
  - `response.data.error`
  - `response.data.detail`
  - `error.message`

## API Usage By Page

### Overview Dashboard

Endpoints:
- `GET /api/health`
- `GET /api/translation/config`
- `GET /api/projects/summary`

Consumed fields:
- Health:
  - `status`
- Runtime:
  - `provider`
  - `model`
  - `batch_size`
- Project summary:
  - `counts.total_files`
  - `counts.active_projects`
  - `alerts.failed_tasks`
  - `recent_tasks`
  - `last_release`

### Translation Lab

Endpoints:
- `GET /api/translation/languages`
- `POST /api/translation/text`
- `POST /api/translation/excel`

Notes:
- Language select options are loaded from backend instead of being hardcoded only.
- If language loading fails, the page falls back to local defaults.

### CAD Workspace

Endpoints:
- `POST /api/cad/extract`
- `POST /api/cad/translate-batch`
- `POST /api/cad/apply-translation`
- `GET /api/cad/download/{task_id}/{file_type}`

Current frontend assumptions:
- Extract response body is `{ success, data }`
- `data.texts` is an editable dictionary grid
- Apply response body returns `translated_cad_file`

### Projects Center

Endpoints:
- `GET /api/cad/tasks`
- `GET /api/projects/summary`
- `DELETE /api/cad/tasks/{task_id}`
- `GET /api/cad/download/{task_id}/{file_type}`

Current data split:
- Table rows and detail panel come from `GET /api/cad/tasks`
- Top summary cards come from `GET /api/projects/summary`

### Model Gateway

Endpoints:
- `GET /api/translation/config`
- `GET /api/translation/providers`
- `POST /api/translation/config`
- `POST /api/translation/test-connection`

Important behavior:
- Frontend omits `api_key` when the field is blank.
- This preserves the server-side key already stored in runtime config.
- Connection test result uses backend fields:
  - `success`
  - `reachable`
  - `status_code`
  - `provider`
  - `endpoint`
  - `model`
  - `message`

## Current Canonical Endpoints Used By Frontend

### Health

```text
GET /api/health
```

### Project Summary

```text
GET /api/projects/summary
```

### Text Translation

```text
POST /api/translation/text
```

Note:
- Frontend no longer depends on legacy `POST /api/translate` as its primary path.

### Excel Translation

```text
POST /api/translation/excel
GET /api/translation/download/{filename}
```

### Runtime Config

```text
GET /api/translation/languages
GET /api/translation/config
GET /api/translation/providers
POST /api/translation/config
POST /api/translation/test-connection
```

### CAD Workflow

```text
POST /api/cad/extract
POST /api/cad/translate-batch
POST /api/cad/apply-translation
GET /api/cad/tasks
DELETE /api/cad/tasks/{task_id}
GET /api/cad/download/{task_id}/{file_type}
```

## Notes

1. Dashboard and Projects stats now come from `GET /api/projects/summary` instead of being derived only from CAD task rows.
2. Model Gateway `batch_json` is a real backend-backed runtime field, not a frontend-only toggle.
3. `CAD Workspace` still uses the unified Route B pipeline and supports real `DWG/DXF` extract flow.
4. Compatibility endpoints still exist on the backend, but frontend now prefers the canonical router endpoints.
