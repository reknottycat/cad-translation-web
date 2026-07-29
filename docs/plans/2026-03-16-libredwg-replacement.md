# LibreDWG Replacement Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the broken `acadsharp` DWG conversion path with `LibreDWG/dwg2dxf`, including automatic GitHub download when the converter is missing locally.

**Architecture:** Keep DWG conversion centered in `backend/app/functions/dwg_converter.py`, but change backend selection, binary discovery, and validation to use `LibreDWG` as the primary path. Wire the same behavior through backend services and the standalone CLI so all entry points share one conversion implementation.

**Tech Stack:** Python 3.12, FastAPI backend, Click CLI, `pytest`, standard library `urllib` and `zipfile`, `ezdxf`, GitHub release assets.

---

### Task 1: Add failing tests for the new backend contract

**Files:**
- Modify: `C:\Users\zhenhe\OneDrive\永盛\翻译\cad code\tests\backend\test_backend_runtime.py`
- Modify: `C:\Users\zhenhe\OneDrive\永盛\翻译\cad code\agent-harness\cli_anything\cad\tests\test_full_e2e.py`

**Step 1: Write the failing tests**

Add tests that expect:

- `DWGConverter` defaults to `libredwg`
- repo-local `tools/libredwg/.../dwg2dxf.exe` is resolvable
- converted DXF from the real LibreDWG path can be parsed and round-trip saved
- the DWG CLI roundtrip still passes through `convert -> extract -> apply`

**Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/backend/test_backend_runtime.py::test_dwg_converter_resolves_libredwg_binary_relative_to_repo_root tests/backend/test_backend_runtime.py::test_text_applier_can_save_libredwg_converted_dxf -v -s
```

Expected: failure because `libredwg` is not wired as the active backend yet.

### Task 2: Implement LibreDWG backend discovery and auto-download

**Files:**
- Modify: `C:\Users\zhenhe\OneDrive\永盛\翻译\cad code\backend\app\config.py`
- Modify: `C:\Users\zhenhe\OneDrive\永盛\翻译\cad code\backend\app\functions\dwg_converter.py`

**Step 1: Add settings for LibreDWG**

Add only the minimal settings needed:

- `DWG_CONVERTER_BACKEND=libredwg`
- `LIBREDWG_DWG2DXF_PATH`
- `LIBREDWG_INSTALL_DIR`
- `LIBREDWG_DOWNLOAD_URL`
- `LIBREDWG_AUTO_DOWNLOAD`

**Step 2: Implement binary resolution**

In `dwg_converter.py`, add helpers that:

- resolve a configured explicit path
- search `PATH`
- search `tools/libredwg/**/dwg2dxf.exe`
- download and extract the official Windows zip when nothing is found

**Step 3: Implement conversion validation**

After running `dwg2dxf`, verify:

- output file exists
- `ezdxf.readfile()` succeeds
- `doc.saveas()` round-trip succeeds to a temp file

### Task 3: Replace acadsharp wiring in services and CLI bridge

**Files:**
- Modify: `C:\Users\zhenhe\OneDrive\永盛\翻译\cad code\backend\app\services\cad_pipeline_service.py`
- Modify: `C:\Users\zhenhe\OneDrive\永盛\翻译\cad code\backend\app\services\cad_text_processor.py`
- Modify: `C:\Users\zhenhe\OneDrive\永盛\翻译\cad code\agent-harness\cli_anything\cad\utils\backend_bridge.py`

**Step 1: Replace backend mapping**

Update mapping so:

- `auto` resolves to `libredwg`
- `libredwg_cli` resolves to `libredwg`
- `acadsharp` is no longer suggested or used as the default path

**Step 2: Remove stale ACadSharp-only assumptions**

Delete or bypass code paths that claim `LibreDWG` is not wired and ensure service-level conversion routes through the shared `DWGConverter` implementation.

### Task 4: Clean up docs and local tool handling

**Files:**
- Modify: `C:\Users\zhenhe\OneDrive\永盛\翻译\cad code\.gitignore`
- Modify: `C:\Users\zhenhe\OneDrive\永盛\翻译\cad code\agent-harness\cli_anything\cad\README.md`
- Modify: `C:\Users\zhenhe\OneDrive\永盛\翻译\cad code\agent-harness\cli_anything\cad\tests\TEST.md`

**Step 1: Document the new converter behavior**

Explain:

- `LibreDWG` is now the default DWG converter
- missing converter binaries are auto-downloaded from GitHub
- downloaded files live under `tools/libredwg/`

**Step 2: Ignore local tool artifacts**

Ignore repo-local extracted tool folders and conversion scratch outputs without hiding source code changes.

### Task 5: Verify the replacement end to end

**Files:**
- No new files required

**Step 1: Run targeted backend tests**

```bash
python -m pytest tests/backend/test_backend_runtime.py::test_dwg_converter_resolves_libredwg_binary_relative_to_repo_root tests/backend/test_backend_runtime.py::test_text_applier_can_save_libredwg_converted_dxf -v -s
```

**Step 2: Run CLI DWG roundtrip**

```bash
python -m pytest agent-harness/cli_anything/cad/tests/test_full_e2e.py::test_dwg_convert_extract_apply_roundtrip -v -s
```

**Step 3: Run a real manual conversion**

```bash
cli-anything-cad pipeline convert -i ".\\1360001401 施工图.dwg" -o ".\\output\\libredwg_manual_check"
```

Confirm the generated DXF exists, is non-empty, and can be opened and round-trip saved by `ezdxf`.
