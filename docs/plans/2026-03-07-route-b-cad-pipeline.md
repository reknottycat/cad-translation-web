# Route B CAD Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the CAD web pipeline so `DWG` uploads can flow through a real Route B conversion chain while keeping the frontend API contract in `docs/modern/FRONTEND_API_SPEC.md` stable.

**Architecture:** Add a .NET ACadSharp sidecar to convert `DWG -> DXF` and optionally extract metadata, then keep Python as the orchestration layer for task storage, text extraction, translation, and DXF write-back through `ezdxf`. Replace ad hoc output folders with unified task directories used by `/api/cad/extract`, `/api/cad/apply-translation`, `/api/cad/tasks`, and `/api/cad/download`.

**Tech Stack:** FastAPI, pytest, Python subprocess integration, ezdxf, pandas, .NET 8 console app, ACadSharp.

---

### Task 1: Lock the API-compatible backend behavior with tests

**Files:**
- Modify: `tests/backend/test_backend_runtime.py`
- Test: `tests/backend/test_backend_runtime.py`

**Step 1: Write the failing test**

Add tests that assert:
- `POST /api/cad/extract` accepts `.dwg` when a converter backend is configured.
- The route returns the documented payload shape with `task_id`, `text_count`, `excel_file`, and `texts`.
- `GET /api/cad/tasks` reads from the same unified task directory used by extract/apply.

**Step 2: Run test to verify it fails**

Run: `pytest tests/backend/test_backend_runtime.py -q -k cad_extract`
Expected: FAIL because the current route rejects `.dwg` and does not persist extract tasks in the same directory shape as the task list route.

**Step 3: Write minimal implementation**

Only change the code needed so the new tests can reach the converter service boundary without performing a real CAD conversion.

**Step 4: Run test to verify it passes**

Run: `pytest tests/backend/test_backend_runtime.py -q -k cad_extract`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/backend/test_backend_runtime.py
git commit -m "test: cover route b cad extract contract"
```

### Task 2: Add the ACadSharp sidecar project

**Files:**
- Create: `tools/AcadSharpBridge/AcadSharpBridge.csproj`
- Create: `tools/AcadSharpBridge/Program.cs`
- Create: `tools/AcadSharpBridge/Models/TextEntityRecord.cs`
- Modify: `backend/app/config.py`

**Step 1: Write the failing test**

Add a backend unit test that expects the converter service to build the ACadSharp command line from config, and expects a missing executable to raise a clear error.

**Step 2: Run test to verify it fails**

Run: `pytest tests/backend/test_backend_runtime.py -q -k acadsharp`
Expected: FAIL because no ACadSharp sidecar config or command builder exists yet.

**Step 3: Write minimal implementation**

Create a .NET console app that supports:
- `convert --input <dwg> --output <dxf>`
- JSON stderr/stdout for failure reporting

Add config fields for:
- `DWG_CONVERTER_BACKEND`
- `ACADSHARP_BRIDGE_PROJECT`
- `ACADSHARP_BRIDGE_DLL`
- `CAD_CONVERTER_TIMEOUT`

**Step 4: Run test to verify it passes**

Run: `pytest tests/backend/test_backend_runtime.py -q -k acadsharp`
Expected: PASS.

**Step 5: Commit**

```bash
git add tools/AcadSharpBridge backend/app/config.py tests/backend/test_backend_runtime.py
git commit -m "feat: add acadsharp converter sidecar"
```

### Task 3: Refactor the Python CAD conversion service

**Files:**
- Modify: `backend/app/services/cad_text_processor.py`
- Create: `backend/app/services/cad_pipeline_service.py`
- Modify: `backend/app/services/com_converter_cli.py`
- Test: `tests/backend/test_backend_runtime.py`

**Step 1: Write the failing test**

Add tests that expect:
- Route B converter selection prefers `acadsharp` and falls back to `oda` only when configured.
- The pipeline stores original input, generated DXF, extracted Excel, and task metadata under one task directory.
- `apply_translation` reads from the persisted DXF instead of rescanning arbitrary files.

**Step 2: Run test to verify it fails**

Run: `pytest tests/backend/test_backend_runtime.py -q -k cad_pipeline`
Expected: FAIL because extract/apply/list/download still use mismatched directory conventions.

**Step 3: Write minimal implementation**

Create a focused pipeline service that:
- creates a task id and task directory
- persists metadata in a single `task.json`
- converts DWG to DXF when needed
- extracts text to Excel from the normalized DXF
- applies translations back to the normalized DXF

**Step 4: Run test to verify it passes**

Run: `pytest tests/backend/test_backend_runtime.py -q -k cad_pipeline`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/services/cad_text_processor.py backend/app/services/cad_pipeline_service.py tests/backend/test_backend_runtime.py
git commit -m "refactor: unify route b cad pipeline storage"
```

### Task 4: Rewire the CAD API routes to the unified pipeline

**Files:**
- Modify: `backend/app/api/routes/cad.py`
- Test: `tests/backend/test_backend_runtime.py`

**Step 1: Write the failing test**

Add integration tests for:
- `POST /api/cad/extract`
- `POST /api/cad/apply-translation`
- `GET /api/cad/tasks`
- `GET /api/cad/download/{task_id}/{file_type}`

**Step 2: Run test to verify it fails**

Run: `pytest tests/backend/test_backend_runtime.py -q -k cad_route`
Expected: FAIL because the route responses and task folder handling are inconsistent.

**Step 3: Write minimal implementation**

Rewire routes to the new pipeline service while preserving:
- documented request fields
- documented response shape
- compatible file type aliases (`cad`, `translated_cad`, `excel`, `log`)

**Step 4: Run test to verify it passes**

Run: `pytest tests/backend/test_backend_runtime.py -q -k cad_route`
Expected: PASS.

**Step 5: Commit**

```bash
git add backend/app/api/routes/cad.py tests/backend/test_backend_runtime.py
git commit -m "refactor: route cad api through unified pipeline"
```

### Task 5: Verify the real sample flow and document usage

**Files:**
- Modify: `docs/modern/FRONTEND_API_SPEC.md`
- Modify: `docs/modern/CAD_CONVERTER_BACKENDS.md`
- Test: `tests/backend/test_backend_runtime.py`

**Step 1: Write the verification checklist**

Document the exact commands for:
- `dotnet build tools/AcadSharpBridge/AcadSharpBridge.csproj`
- `pytest tests/backend/test_backend_runtime.py -q`
- sample DWG extract on `样本 _X260116-04  自力式小样图.dwg`

**Step 2: Run verification**

Expected:
- sidecar builds
- backend tests pass
- sample flow either extracts text successfully or fails with an explicit sidecar/parser error instead of a hidden COM hang

**Step 3: Update docs**

Document the new Route B defaults and the fact that ACadSharp is now the primary converter backend.

**Step 4: Commit**

```bash
git add docs/modern/FRONTEND_API_SPEC.md docs/modern/CAD_CONVERTER_BACKENDS.md
git commit -m "docs: document route b cad pipeline"
```
