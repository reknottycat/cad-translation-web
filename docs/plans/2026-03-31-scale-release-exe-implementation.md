# Scale Release EXE Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a second-stage portable EXE launcher pipeline that packages a sanitized runtime payload into a separate `scale_release_exe/` output folder.

**Architecture:** Stage two stays isolated from the existing `scale_release` flow. A new PowerShell build script creates a sanitized runtime copy, generates launcher metadata, and invokes PyInstaller to produce a single user-facing EXE in `scale_release_exe/`.

**Tech Stack:** PowerShell, Python, PyInstaller, pytest

---

### Task 1: Lock the isolated EXE pipeline boundary with tests

**Files:**
- Create: `tests/test_scale_release_exe_packaging.py`

**Step 1: Write the failing test**

Create a packaging test that:

- creates a synthetic repo tree
- runs `scripts/build_scale_exe.ps1`
- asserts it writes to `scale_release_exe/`
- asserts it does not reuse `scale_release/`
- asserts the sanitized runtime payload excludes live API keys from `.env` and `runtime_config.local.json`

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scale_release_exe_packaging.py -v`
Expected: FAIL because the stage-two script does not exist yet.

**Step 3: Write minimal implementation**

Add the new build script and sanitizer helpers needed to satisfy the test.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scale_release_exe_packaging.py -v`
Expected: PASS

### Task 2: Add launcher source and PyInstaller build path

**Files:**
- Create: `release_exe/launcher.py`
- Create: `release_exe/launcher.spec` or generate the equivalent command line in PowerShell

**Step 1: Write the failing test**

Extend the stage-two packaging test to assert that the output contains `launcher.exe` and a runtime payload asset.

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scale_release_exe_packaging.py -v`
Expected: FAIL until the launcher build path exists.

**Step 3: Write minimal implementation**

Implement a console launcher that expands or locates the sanitized runtime payload, starts the backend, waits for health, and opens the browser.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scale_release_exe_packaging.py -v`
Expected: PASS

### Task 3: Run the real EXE build

**Files:**
- Modify: `scripts/build_scale_exe.ps1`

**Step 1: Execute the real stage-two build**

Run: `powershell -ExecutionPolicy Bypass -File scripts/build_scale_exe.ps1`

**Step 2: Verify artifacts**

Check:

- `scale_release_exe/launcher.exe` exists
- stage-two runtime payload exists
- sanitized payload does not contain live API keys

**Step 3: Run focused regression checks**

Run:

- `python -m pytest tests/test_scale_release_exe_packaging.py -v`
- `python -m pytest tests/test_scale_release_packaging.py -v`

**Step 4: Commit**

```bash
git add docs/plans/2026-03-31-scale-release-exe-design.md docs/plans/2026-03-31-scale-release-exe-implementation.md tests/test_scale_release_exe_packaging.py release_exe scripts/build_scale_exe.ps1
git commit -m "feat: add portable scale release exe pipeline"
```
