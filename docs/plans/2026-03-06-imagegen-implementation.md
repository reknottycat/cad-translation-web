# Image Generation Workflow Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a batch image generation CLI and use it to produce four approved frontend UI mockups.

**Architecture:** The repo gets a small Python CLI under `scripts/` that reads either a direct prompt or a JSONL job list, calls the OpenAI Images API through the official SDK, writes PNG outputs, and emits a manifest. Tests cover only pure helper logic so the API call path remains simple and low-risk.

**Tech Stack:** Python 3.12, OpenAI Python SDK, Pillow, pytest

---

### Task 1: Create the prompt job manifest

**Files:**
- Create: `tmp/imagegen/frontend-ui-prompts.jsonl`

**Step 1: Write the jobs**

- Add four JSONL lines with prompt, filename, model, size, and quality.

**Step 2: Verify the file can be parsed**

Run: `@' ... ' @ | python -`
Expected: prints `4`

### Task 2: Add helper tests

**Files:**
- Create: `tests/scripts/test_image_gen.py`

**Step 1: Write failing tests**

- Test JSONL parsing returns the expected number of jobs.
- Test filename sanitization removes unsafe characters.

**Step 2: Run tests to verify they fail**

Run: `pytest tests/scripts/test_image_gen.py -q`
Expected: import failure because `scripts/image_gen.py` does not exist yet.

### Task 3: Implement the CLI

**Files:**
- Create: `scripts/image_gen.py`

**Step 1: Add minimal implementation**

- Parse CLI args.
- Validate `OPENAI_API_KEY`.
- Load single or batch jobs.
- Call `client.images.generate(...)`.
- Save output PNG files.
- Write manifest JSON.

**Step 2: Run tests**

Run: `pytest tests/scripts/test_image_gen.py -q`
Expected: pass.

### Task 4: Generate the four UI mockups

**Files:**
- Create: `output/imagegen/`
- Modify: `tmp/imagegen/frontend-ui-prompts.jsonl` if prompts need one small iteration

**Step 1: Run batch generation**

Run: `python scripts/image_gen.py --batch-jsonl tmp/imagegen/frontend-ui-prompts.jsonl --out-dir output/imagegen`

**Step 2: Inspect outputs**

- Confirm four PNG files exist.
- Confirm `manifest.json` exists.

### Task 5: Final verification

**Files:**
- No new files required

**Step 1: Run helper tests**

Run: `pytest tests/scripts/test_image_gen.py -q`

**Step 2: Verify generated files**

Run: `Get-ChildItem output\\imagegen`

**Step 3: Report actual results**

- If API generation succeeds, list output files.
- If the API blocks due to model access, org verification, or billing, report the exact error and keep the script and prompt pack in place.
