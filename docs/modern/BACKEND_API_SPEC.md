# Backend API Spec

This document describes the backend API that is actually implemented by the FastAPI app in `backend/app/main.py` and the included routers.

## Base

- App root: `backend/app/main.py`
- OpenAPI docs: `/api/docs`
- ReDoc: `/api/redoc`
- Default local base URL: `http://127.0.0.1:8000`

## App Endpoints

### `GET /`

Response:

```json
{
  "message": "CAD translation backend API",
  "version": "1.0.0",
  "docs": "/api/docs",
  "status": "running"
}
```

### `GET /api/health`

Response:

```json
{
  "status": "healthy|degraded",
  "celery": "local_eager|celery",
  "async_runtime": {
    "status": "healthy|degraded",
    "mode": "local_eager|celery"
  },
  "database": "connected",
  "timestamp": "2026-03-08T00:00:00+00:00"
}
```

### `POST /api/translate`

Compatibility shortcut for old text-translation clients. Canonical text translation lives at `POST /api/translation/text`.

## Translation Routes

Router:
- `backend/app/routers/translation.py`
- Prefix: `/api/translation`

### `POST /api/translation/text`

Request:

```json
{
  "text": "Valve",
  "source_lang": "auto",
  "target_lang": "ru"
}
```

Response:

```json
{
  "original_text": "Valve",
  "translated_text": "Клапан",
  "source_lang": "auto",
  "target_lang": "ru",
  "success": true,
  "error_message": null
}
```

### `POST /api/translation/batch`

Request:

```json
{
  "texts": ["Valve", "Pump"],
  "source_lang": "auto",
  "target_lang": "ru"
}
```

Response:
- Array of translation rows

### `POST /api/translation/excel`

Request:
- `multipart/form-data`
- Fields:
  - `file`
  - `source_lang`
  - `target_lang`
  - `translation_mode`
  - optional `text_columns`

Response:

```json
{
  "success": true,
  "message": "excel translation completed",
  "output_filename": "translated_demo.xlsx",
  "download_url": "/api/translation/download/translated_demo.xlsx",
  "report_filename": "translated_demo_translation_report.xlsx",
  "stats": {}
}
```

### `POST /api/translation/excel/async`

Response:

```json
{
  "task_id": "task-id",
  "status": "submitted",
  "message": "task submitted"
}
```

### `GET /api/translation/task/{task_id}`

Returns async Excel task status.

### `GET /api/translation/download/{filename}`

Returns translated Excel file stream.

### `GET /api/translation/languages`

Response:

```json
{
  "languages": {
    "zh": "中文",
    "en": "English",
    "ru": "Русский"
  },
  "default_source": "zh",
  "default_target": "en"
}
```

### `GET /api/translation/providers`

Returns active runtime summary and provider presets.

### `GET /api/translation/config`

Response includes:
- supported languages
- translation modes
- file types
- runtime summary
- provider presets

Runtime fields currently exposed:
- `provider`
- `base_url`
- `model`
- `api_key_configured`
- `timeout_seconds`
- `temperature`
- `max_tokens`
- `batch_size`
- `batch_json`
- `masked_api_key`
- `env_file`
- `config_file`

### `POST /api/translation/config`

Request:

```json
{
  "provider": "openrouter",
  "base_url": "https://openrouter.ai/api/v1",
  "api_key": "sk-...",
  "model": "stepfun/step-3.5-flash:free",
  "temperature": 0.1,
  "max_tokens": 4000,
  "timeout_seconds": 45,
  "batch_size": 4,
  "batch_json": true
}
```

Notes:
- If `api_key` is omitted, backend preserves the existing key from runtime config or environment.
- Runtime config persists to `backend/config/runtime_config.local.json`.

### `POST /api/translation/test-connection`

Response:

```json
{
  "success": true,
  "reachable": true,
  "status_code": 200,
  "provider": "openrouter",
  "endpoint": "https://openrouter.ai/api/v1/models",
  "model": "stepfun/step-3.5-flash:free",
  "message": "connection ok"
}
```

## CAD Routes

Router:
- `backend/app/api/routes/cad.py`
- Prefix: `/api/cad`

### `POST /api/cad/extract`

Request:
- `multipart/form-data`
- Fields:
  - `file`
  - `converter_backend`
  - `target_language`

Response:

```json
{
  "success": true,
  "data": {
    "task_id": "abcd1234",
    "text_count": 24,
    "excel_file": "/api/cad/download/abcd1234/excel",
    "texts": []
  }
}
```

### `POST /api/cad/translate-batch`

Request:

```json
{
  "texts": ["PUMP", "VALVE"],
  "target_lang": "ru"
}
```

Response:

```json
{
  "success": true,
  "data": {
    "translated_texts": ["НАСОС", "КЛАПАН"]
  }
}
```

### `POST /api/cad/apply-translation`

Request:

```json
{
  "task_id": "abcd1234",
  "translations": [
    {
      "original": "PUMP",
      "translated": "НАСОС"
    }
  ]
}
```

Response:

```json
{
  "success": true,
  "data": {
    "task_id": "abcd1234",
    "translation_count": 1,
    "translated_cad_file": "/api/cad/download/abcd1234/translated_cad"
  }
}
```

### `GET /api/cad/tasks`

Returns Route B task list with artifact URLs.

### `DELETE /api/cad/tasks/{task_id}`

Deletes a Route B task directory.

### `GET /api/cad/download/{task_id}/{file_type}`

Supported `file_type` values:
- `excel`
- `cad`
- `translated_cad`
- `log`

### Other CAD routes

Also available:
- `POST /api/cad/upload`
- `POST /api/cad/translate-text`
- `GET /api/cad/health`
- `PUT /api/cad/dictionary/{task_id}/update`

## Project Routes

Router:
- `backend/app/routers/projects.py`
- Prefix: `/api/projects`

### `GET /api/projects/summary`

Purpose:
- Dashboard and Projects Center aggregate payload

Response includes:
- `counts`
- `status_breakdown`
- `alerts`
- `recent_projects`
- `recent_tasks`
- `last_release`

### Other project routes

Available:
- `POST /api/projects/`
- `GET /api/projects/`
- `GET /api/projects/{project_id}`
- `PUT /api/projects/{project_id}`
- `DELETE /api/projects/{project_id}`
- `POST /api/projects/{project_id}/process`
- `GET /api/projects/{project_id}/status`
- `POST /api/projects/{project_id}/cancel`

## File Routes

Router:
- `backend/app/routers/files.py`
- Prefix: `/api/files`

Available:
- `POST /api/files/upload/{project_id}`
- `GET /api/files/{project_id}`
- `GET /api/files/detail/{file_id}`
- `DELETE /api/files/{file_id}`
- `GET /api/files/download/{file_id}`
- `POST /api/files/batch-download/{project_id}`

Status:
- These are legacy project/file-management routes and are not the main Route B frontend path.

## Error Shape

Handled FastAPI HTTP errors return:

```json
{
  "error": "detail message",
  "status_code": 400
}
```

Unhandled server errors return:

```json
{
  "error": "internal server error",
  "status_code": 500
}
```
