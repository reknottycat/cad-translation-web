# API Routes Quick Reference

Base URL: http://localhost:8000

Use /api/docs for the live OpenAPI contract. This file is a short reference,
not a replacement for request and response schemas.

## Health and documentation

| Method | Path | Purpose |
|--------|------|---------|
| GET | / | Frontend when built, otherwise app info |
| GET | /api/health | Backend, database, and async-runtime liveness |
| GET | /api/cad/health | CAD service liveness |
| GET | /api/docs | Swagger UI |
| GET | /api/redoc | ReDoc |

## Translation

Router: backend/app/routers/translation.py

| Method | Path | Purpose |
|--------|------|---------|
| POST | /api/translation/glossary/upload | Upload CSV/XLSX/XLS glossary |
| POST | /api/translation/text | Translate one text value |
| POST | /api/translation/batch | Translate a batch |
| POST | /api/translation/excel | Translate Excel synchronously |
| POST | /api/translation/excel/async | Submit Excel translation to Celery |
| GET | /api/translation/task/{task_id} | Read async task status |
| GET | /api/translation/download/{filename} | Download translated output |
| GET | /api/translation/languages | List supported languages; public |
| GET | /api/translation/providers | List provider presets and masked config |
| POST | /api/translation/providers/custom | Add a custom provider |
| DELETE | /api/translation/providers/custom/{provider_id} | Delete a custom provider |
| GET/POST | /api/translation/config | Read/update runtime config |
| POST | /api/translation/test-connection | Test a proposed provider config |

All translation rows except languages use the instance admin guard when it is
enabled.

## CAD pipeline

Router: backend/app/api/routes/cad.py

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST | /api/cad/defaults | Read/update CAD defaults |
| POST | /api/cad/extract | Upload DWG/DXF and extract text to Excel |
| POST | /api/cad/apply-translation | Apply translations to a task CAD output |
| POST | /api/cad/upload | Full upload pipeline or extraction-only mode |
| GET | /api/cad/download/{task_id}/{file_type} | Download a task artifact |
| POST | /api/cad/download-package | Package selected task artifacts |
| GET | /api/cad/tasks | List CAD tasks |
| POST | /api/cad/tasks/stop-all | Stop all active CAD tasks |
| DELETE | /api/cad/tasks | Clear all CAD tasks |
| POST | /api/cad/tasks/{task_id}/resume | Resume a failed/interrupted task |
| GET | /api/cad/tasks/{task_id}/logs | Read task logs |
| DELETE | /api/cad/tasks/{task_id} | Delete one CAD task |
| POST | /api/cad/translate-text | Translate one form text value |
| POST | /api/cad/translate-batch | Translate a list |
| PUT | /api/cad/dictionary/{task_id}/update | Acknowledge dictionary update |
| GET | /api/cad/health | CAD service liveness; public |

There is no registered /api/cad/pipeline, /api/cad/apply, or
GET /api/cad/tasks/{task_id} route in the current implementation.

## Projects and files

Routers: backend/app/routers/projects.py and backend/app/routers/files.py

| Method | Path | Purpose |
|--------|------|---------|
| GET | /api/projects/summary | Project summary |
| GET/POST | /api/projects/ | List/create projects |
| GET/PUT/DELETE | /api/projects/{project_id} | Project detail/update/delete |
| POST | /api/projects/{project_id}/process | Start project processing |
| GET | /api/projects/{project_id}/status | Processing status |
| POST | /api/projects/{project_id}/cancel | Cancel processing |
| POST | /api/files/upload/{project_id} | Upload files to a project |
| GET | /api/files/{project_id} | List project files |
| GET | /api/files/detail/{file_id} | File metadata/detail |
| GET | /api/files/download/{file_id} | Download one file |
| POST | /api/files/batch-download/{project_id} | Download project files |
| DELETE | /api/files/{file_id} | Delete one file |

## Agent and runtime boundary

The legacy POST /api/translate endpoint remains in backend/app/main.py; new
integrations should prefer guarded /api/translation/* routes.

When the user invokes a Skill through an Agent, the Agent may use its existing
authorized model/tools without requiring the project to store an API Key.
That does not grant the Web app, CLI, Celery, or unattended jobs access to an
LLM provider: those runtime paths still need their own configured
authentication, unless the provider is local or keyless.

With ENABLE_ADMIN_GUARD=true, guarded routes require X-Admin-Token or
Authorization: Bearer. If the guard is enabled but ADMIN_API_TOKEN is empty,
guarded routes fail closed with 503. The token protects the whole single-tenant
instance, not separate users.

Runtime JSON configuration is an internal service, not a router. Its default
path is Path.home()/.config/cli-anything-cad/config.json, with
XDG_CONFIG_HOME and CAD_TRANSLATION_RUNTIME_CONFIG_FILE overrides. Writes use
cross-process locking and atomic replacement; public summaries mask keys.
