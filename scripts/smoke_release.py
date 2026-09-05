"""Start a portable release twice and verify durable local task/DB/config state.

Runs only synthetic DXF extraction; never invokes a paid translation provider.
Use --exe for the frozen Windows artifact, or --payload with the source launcher.
All server data and logs live in an automatically removed temporary directory.
"""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid


def request(base: str, path: str, data: bytes | None = None,
            content_type: str = "application/json") -> object:
    req = urllib.request.Request(base + path, data=data,
                                 headers={"Content-Type": content_type})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=30) as response:
        return json.load(response)


def verify(command: list[str], stage: Path, timeout: float) -> dict:
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith(("CAD_", "LLM_", "ALIBABA_", "OPENAI_")) or key in {
            "DATABASE_URL", "UPLOAD_DIR", "OUTPUT_DIR", "TEMP_DIR",
            "ENABLE_ADMIN_GUARD", "ADMIN_API_TOKEN", "PYTHONPATH",
        }:
            environment.pop(key)
    environment.update(LOCALAPPDATA=str(stage / "local"), CAD_HEADLESS="1",
                       PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1", PYTHONUTF8="1")
    project_id = task_id = None
    for run in range(2):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        environment["CAD_PORT"] = str(port)
        base = f"http://127.0.0.1:{port}"
        with (stage / f"run-{run}.log").open("wb") as log:
            process = subprocess.Popen(command, cwd=stage, env=environment,
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + timeout
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f"release exited during startup: {process.returncode}")
                    try:
                        request(base, "/api/translation/config")
                        break
                    except (OSError, ValueError, urllib.error.URLError):
                        if time.monotonic() >= deadline:
                            raise TimeoutError("release did not become ready")
                        time.sleep(0.25)
                if run == 0:
                    request(base, "/api/translation/config", json.dumps({
                        "provider": "ollama", "model": "release-smoke-local",
                        "base_url": "http://127.0.0.1:11434", "temperature": 0.37,
                    }).encode())
                    project = request(base, "/api/projects/", json.dumps(
                        {"name": "release-persistence-smoke"}).encode())
                    project_id = project["id"]
                    # A minimal real DXF proves the shipped ezdxf/pandas/openpyxl imports.
                    import ezdxf

                    drawing = ezdxf.new()
                    drawing.modelspace().add_text("Release smoke", dxfattribs={"height": 2})
                    stream = io.StringIO()
                    drawing.write(stream)
                    boundary = uuid.uuid4().hex
                    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"extract_only\"\r\n\r\ntrue\r\n"
                            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"smoke.dxf\"\r\n"
                            "Content-Type: application/octet-stream\r\n\r\n").encode()
                    body += stream.getvalue().encode() + f"\r\n--{boundary}--\r\n".encode()
                    task = request(base, "/api/cad/upload", body,
                                   f"multipart/form-data; boundary={boundary}")
                    task_id = task["data"]["task_id"]
                    if task["data"]["text_count"] != 1:
                        raise AssertionError("synthetic drawing extraction failed")
                else:
                    project = request(base, f"/api/projects/{project_id}")
                    if project["name"] != "release-persistence-smoke":
                        raise AssertionError("project did not survive restart")
                    task = request(base, f"/api/cad/tasks/{task_id}")
                    if task["data"]["task_id"] != task_id:
                        raise AssertionError("task did not survive restart")
                    config = stage / "local/CAD Translation/data/config/config.json"
                    runtime = request(base, "/api/translation/config")["runtime"]
                    if not config.is_file() or runtime["model"] != "release-smoke-local":
                        raise AssertionError("runtime configuration did not survive restart")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=15)
    return {"startup_runs": 2, "project_persistent": True,
            "task_persistent": True, "config_persistent": True, "synthetic_texts": 1}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--exe", type=Path)
    group.add_argument("--payload", type=Path)
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="cad_release_smoke_") as folder:
        stage = Path(folder)
        if args.exe:
            command = [str(args.exe.resolve())]
        else:
            shutil.copyfile(args.payload, stage / "runtime_payload.zip")
            shutil.copyfile(Path(__file__).resolve().parents[1] / "release_exe/launcher.py",
                            stage / "launcher.py")
            command = [sys.executable, str(stage / "launcher.py")]
        try:
            print(json.dumps(verify(command, stage, args.timeout), sort_keys=True))
        except Exception:
            # Synthetic inputs and isolated config only; retain diagnostics on failure.
            for path in sorted(stage.glob("run-*.log")):
                print(path.read_text(encoding="utf-8", errors="replace")[-6000:], file=sys.stderr)
            raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
