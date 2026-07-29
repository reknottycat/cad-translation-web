# Image Generation Workflow Design

**Date:** 2026-03-06

**Goal:** Add a repo-local image generation workflow that can batch-generate four UI mockups for the new CAD SaaS frontend using the OpenAI Image API.

## Scope

- Add a reusable CLI script at `scripts/image_gen.py`.
- Support single-prompt and JSONL batch generation.
- Write outputs to `output/imagegen/`.
- Keep prompts and job manifests under `tmp/imagegen/`.
- Generate four UI mockups:
  - Overview Dashboard
  - CAD Workspace
  - Projects Center
  - Model Gateway

## Design

- The script uses the OpenAI Python SDK and reads `OPENAI_API_KEY` from the environment.
- Batch mode consumes one JSON object per line with prompt metadata and output filename.
- Each job produces:
  - a PNG image
  - a manifest entry with prompt, model, size, quality, and output path
- The script keeps a small surface area:
  - validate environment and arguments
  - load jobs
  - call `client.images.generate(...)`
  - decode base64 image data
  - save PNG files
  - emit a manifest JSON file

## Constraints

- Use the OpenAI SDK, not raw HTTP.
- Do not depend on frontend code or backend services.
- Prefer deterministic filenames and stable output paths.
- Default to a GPT Image model and batch mode for the four UI screens.

## Error Handling

- Missing `OPENAI_API_KEY`: exit with a clear message.
- Missing prompt or JSONL path: fail argument validation.
- API failure for one job: keep processing other jobs, then exit non-zero if any job failed.
- Invalid JSONL line: fail early with the line number.

## Verification

- Add small pytest coverage for JSONL parsing and filename sanitization.
- Run the script against the four approved UI prompts.
- Verify that images and a manifest file exist under `output/imagegen/`.
