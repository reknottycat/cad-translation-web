#!/usr/bin/env python3
"""Generate images with the OpenAI Images API."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from openai import OpenAI


DEFAULT_MODEL = "gpt-image-1.5"
DEFAULT_SIZE = "1536x1024"
DEFAULT_QUALITY = "medium"


def sanitize_filename(filename: str) -> str:
    path = Path(filename)
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", path.stem).strip("-_.").lower()
    stem = re.sub(r"-{2,}", "-", stem) or "image"
    suffix = path.suffix.lower() or ".png"
    return f"{stem}{suffix}"


def load_jsonl_jobs(path: Path) -> List[Dict[str, Any]]:
    jobs: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                job = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on line {line_number}: {exc}") from exc
            if not job.get("prompt"):
                raise ValueError(f"missing prompt on line {line_number}")
            job["filename"] = sanitize_filename(job.get("filename", f"image-{line_number}.png"))
            jobs.append(job)
    if not jobs:
        raise ValueError(f"no jobs found in {path}")
    return jobs


def save_base64_png(b64_data: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(base64.b64decode(b64_data))


def build_jobs_from_args(args: argparse.Namespace) -> List[Dict[str, Any]]:
    if args.batch_jsonl:
        return load_jsonl_jobs(Path(args.batch_jsonl))
    if not args.prompt:
        raise ValueError("either --prompt or --batch-jsonl is required")
    filename = sanitize_filename(args.out or "generated-image.png")
    return [
        {
            "filename": filename,
            "prompt": args.prompt,
            "model": args.model,
            "size": args.size,
            "quality": args.quality,
        }
    ]


def generate_job(client: OpenAI, job: Dict[str, Any], output_dir: Path) -> Dict[str, Any]:
    model = job.get("model", DEFAULT_MODEL)
    size = job.get("size", DEFAULT_SIZE)
    quality = job.get("quality", DEFAULT_QUALITY)
    response = client.images.generate(
        model=model,
        prompt=job["prompt"],
        size=size,
        quality=quality,
    )
    image = response.data[0].b64_json
    if not image:
        raise RuntimeError("API returned no image payload")
    output_path = output_dir / sanitize_filename(job["filename"])
    save_base64_png(image, output_path)
    return {
        "filename": output_path.name,
        "output_path": str(output_path),
        "model": model,
        "size": size,
        "quality": quality,
        "prompt": job["prompt"],
        "status": "success",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate images with the OpenAI Images API.")
    parser.add_argument("--prompt", help="Single prompt to generate.")
    parser.add_argument("--out", help="Output filename for single prompt mode.")
    parser.add_argument("--batch-jsonl", help="Path to a JSONL job list.")
    parser.add_argument("--out-dir", default="output/imagegen", help="Output directory.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Image model.")
    parser.add_argument("--size", default=DEFAULT_SIZE, help="Image size, e.g. 1536x1024.")
    parser.add_argument("--quality", default=DEFAULT_QUALITY, help="Image quality.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return 2

    try:
        jobs = build_jobs_from_args(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    client = OpenAI(api_key=api_key)
    output_dir = Path(args.out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    for job in jobs:
        try:
            results.append(generate_job(client, job, output_dir))
            print(f"generated {job['filename']}")
        except Exception as exc:  # pragma: no cover - exercised only with live API
            failures.append(
                {
                    "filename": sanitize_filename(job.get("filename", "image.png")),
                    "prompt": job["prompt"],
                    "status": "failed",
                    "error": str(exc),
                }
            )
            print(f"failed {job.get('filename', 'image')}: {exc}", file=sys.stderr)

    manifest = {
        "results": results,
        "failures": failures,
        "summary": {
            "total": len(jobs),
            "success": len(results),
            "failed": len(failures),
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
