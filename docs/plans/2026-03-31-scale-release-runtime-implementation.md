# Scale Release Runtime Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild `scale_release` into a runtime-only delivery bundle with a single-process launcher and bundled frontend static assets.

**Architecture:** The packaging script becomes the source of truth for the runtime bundle layout. It builds the frontend, copies only runtime paths into `scale_release/`, rewrites the launcher for single-process startup, and regenerates the end-user README. Backend serving remains FastAPI-based and uses the packaged `frontend/dist` assets.

**Tech Stack:** PowerShell packaging, Windows batch launcher, FastAPI, pytest

---

### Task 1: Lock packaging expectations with tests

**Files:**
- Create: `tests/test_scale_release_packaging.py`

**Step 1: Write the failing test**

Create a packaging integration test that:

- creates a synthetic repo tree
- runs `scripts/build_scale.ps1`
- asserts the output contains `frontend/dist/index.html`
- asserts `frontend/src`, `agent-harness`, `.env`, and `.db` files are excluded
- asserts the packaged `start_delivery.bat` prints backend and frontend paths

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scale_release_packaging.py -v`
Expected: FAIL because the current packaging script still copies development material and does not support test-friendly frontend build skipping.

**Step 3: Write minimal implementation**

Refactor `scripts/build_scale.ps1` to support a runtime-only package and a `-SkipFrontendBuild` switch for the integration test.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scale_release_packaging.py -v`
Expected: PASS

### Task 2: Refactor the launcher for single-process delivery

**Files:**
- Modify: `start_delivery.bat`
- Modify: `backend/run_server.py`

**Step 1: Write the failing test**

Extend the packaging test to assert the launcher content now reflects the runtime bundle: single process, printed backend/frontend paths, and browser auto-open.

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scale_release_packaging.py -v`
Expected: FAIL on launcher content assertions.

**Step 3: Write minimal implementation**

Update the launcher and backend banner output to surface runtime paths and single-process defaults.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scale_release_packaging.py -v`
Expected: PASS

### Task 3: Update release docs

**Files:**
- Modify: `docs/modern/RELEASE_SCALE.md`
- Modify: `README.md`

**Step 1: Write the failing test**

Use the packaging test to assert the generated package README mentions runtime-only delivery and double-click startup.

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scale_release_packaging.py -v`
Expected: FAIL until the generated README and docs reflect the new behavior.

**Step 3: Write minimal implementation**

Refresh release documentation to match the runtime-only bundle and single-process launcher.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scale_release_packaging.py -v`
Expected: PASS

### Task 4: Build and verify the real package

**Files:**
- Modify: `scripts/build_scale.ps1`

**Step 1: Run the real packaging command**

Run: `powershell -ExecutionPolicy Bypass -File scripts/build_scale.ps1`

**Step 2: Verify generated artifacts**

Check:

- `scale_release/` exists
- `scale_release.zip` exists
- runtime-only structure matches expectations

**Step 3: Run focused regression checks**

Run:

- `python -m pytest tests/test_scale_release_packaging.py -v`
- `python -m pytest tests/backend/test_backend_runtime.py -k "serves_root or health_uses_local_async_mode" -v`

**Step 4: Commit**

```bash
git add docs/plans/2026-03-31-scale-release-runtime-design.md docs/plans/2026-03-31-scale-release-runtime-implementation.md tests/test_scale_release_packaging.py scripts/build_scale.ps1 start_delivery.bat backend/run_server.py docs/modern/RELEASE_SCALE.md README.md
git commit -m "refactor: rebuild scale release as runtime delivery bundle"
```
