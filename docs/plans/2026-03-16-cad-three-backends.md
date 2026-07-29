# CAD Three-Backend Routing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add three DWG converter backends with ordered fallback so the backend and CLI prefer `haochen_com`, then `autocad_com`, then `oda`.

**Architecture:** Keep conversion orchestration in `backend/app/functions/dwg_converter.py`, but split explicit backend execution from ordered fallback policy. Reuse the existing COM subprocess bridge for HaoChen and AutoCAD scripts in `trans_CAD_gui_V1.0`, and keep ODA as a separately discovered executable with strong install guidance.

**Tech Stack:** Python 3.12, FastAPI backend, Click CLI, `pytest`, Win32 COM subprocess wrappers, ODA File Converter.

---

### Task 1: Add failing routing tests for three backends

**Files:**
- Modify: `<USER_HOME>\cad-code\tests\backend\test_backend_runtime.py`
- Modify: `<USER_HOME>\cad-code\agent-harness\cli_anything\cad\tests\test_core.py`

**Step 1: Write the failing tests**

Add tests that expect:

- default project backend is `haochen_com`
- `auto` resolves through `haochen_com -> autocad_com -> oda`
- explicit `com` tries HaoChen then AutoCAD
- missing ODA raises an install-guidance error

**Step 2: Run the tests to verify they fail**

Run:

```bash
python -m pytest tests/backend/test_backend_runtime.py::test_auto_backend_falls_back_from_haochen_to_autocad_to_oda tests/backend/test_backend_runtime.py::test_missing_oda_shows_install_guidance agent-harness/cli_anything/cad/tests/test_core.py::test_build_context_merges_defaults -v -s
```

Expected: failure because the three-backend routing does not exist yet.

### Task 2: Implement backend orchestration in DWGConverter

**Files:**
- Modify: `<USER_HOME>\cad-code\backend\app\functions\dwg_converter.py`
- Modify: `<USER_HOME>\cad-code\backend\app\config.py`

**Step 1: Define backend names and default**

Set the default backend to `haochen_com`.

Support:

- `haochen_com`
- `autocad_com`
- `oda`
- `com`
- `auto`

**Step 2: Reuse the COM subprocess bridge**

Make the converter invoke:

- `haochen_optimized_converter.OptimizedHaoChenCADConverter`
- `autocad_converter.AutoCADConverter`

from `trans_CAD_gui_V1.0`.

**Step 3: Keep ODA discovery and guidance**

Find ODA from:

- explicit config
- `PATH`
- common Windows ODA install folders

If missing, raise a message that points to the official ODA install page.

### Task 3: Update service and CLI mapping

**Files:**
- Modify: `<USER_HOME>\cad-code\backend\app\services\cad_pipeline_service.py`
- Modify: `<USER_HOME>\cad-code\backend\app\services\cad_text_processor.py`
- Modify: `<USER_HOME>\cad-code\agent-harness\cli_anything\cad\core\project.py`
- Modify: `<USER_HOME>\cad-code\agent-harness\cli_anything\cad\utils\backend_bridge.py`

**Step 1: Map API and CLI names**

Make:

- default empty backend use `auto`
- `auto` mean ordered fallback
- `haochen_com`, `autocad_com`, and `oda` pass through cleanly

**Step 2: Keep old names compatible where safe**

Map old compatibility names without changing the new preferred interface.

### Task 4: Update docs for user-facing backend behavior

**Files:**
- Modify: `<USER_HOME>\cad-code\agent-harness\cli_anything\cad\README.md`
- Modify: `<USER_HOME>\cad-code\agent-harness\cli_anything\cad\tests\TEST.md`

**Step 1: Document fallback order**

Explain:

- default DWG backend is ordered fallback
- first HaoChen COM
- second AutoCAD COM
- third ODA

**Step 2: Document ODA install guidance**

Explain that ODA is not bundled and should be installed separately if missing.

### Task 5: Verify real DWG conversion still works

**Files:**
- No new files required

**Step 1: Run targeted backend tests**

```bash
python -m pytest tests/backend/test_backend_runtime.py::test_auto_backend_falls_back_from_haochen_to_autocad_to_oda tests/backend/test_backend_runtime.py::test_missing_oda_shows_install_guidance tests/backend/test_backend_runtime.py::test_text_applier_can_save_oda_converted_dxf -v -s
```

**Step 2: Run CLI defaults test**

```bash
python -m pytest agent-harness/cli_anything/cad/tests/test_core.py -v
```

**Step 3: Run real DWG roundtrip**

```bash
python -m pytest agent-harness/cli_anything/cad/tests/test_full_e2e.py::test_dwg_convert_extract_apply_roundtrip -v -s
```
