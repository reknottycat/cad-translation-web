"""Offline CAD timings; writes only to its own temporary directory.

Run with backend/.venv/Scripts/python.exe scripts/benchmark_cad_pipeline.py.
Stdout is one JSON document. No network, credentials, DWG or COM are used.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import platform
import socket
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch


def measured(call, repeats=1):
    samples = []
    result = None
    for _ in range(repeats):
        started = time.perf_counter()
        result = call()
        samples.append(time.perf_counter() - started)
    return result, {"seconds": samples, "median_seconds": statistics.median(samples)}


def run(root: Path, sizes: list[int], repeats: int, history_sizes: list[int]):
    # Set every runtime location before importing modules with singleton settings.
    os.environ.update({
        "CAD_TRANSLATION_ENV_FILE": str(root / ".env"),
        "CAD_TRANSLATION_RUNTIME_CONFIG_FILE": str(root / "config.json"),
        "XDG_CONFIG_HOME": str(root / "config"),
        "DATABASE_URL": f"sqlite:///{(root / 'bench.db').as_posix()}",
        "UPLOAD_DIR": str(root / "uploads"), "OUTPUT_DIR": str(root / "outputs"),
        "TEMP_DIR": str(root / "temp"), "ASYNC_TASKS_MODE": "local",
    })
    (root / ".env").write_text("ENABLE_ADMIN_GUARD=false\n", encoding="utf-8")
    (root / "config.json").write_text("{}", encoding="utf-8")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    import ezdxf
    from fastapi import UploadFile
    from app.functions.text_extractor import TextExtractor
    from app.functions.text_applier import TextApplier
    from app.services.cad_pipeline_service import CADPipelineService
    from app.services.llm.translation_service import LLMTranslationService
    from app.services.llm.rate_limit import TokenBucket

    report = {"python": platform.python_version(), "platform": platform.platform(),
              "cpu_count": os.cpu_count(), "repeats": repeats, "dxf": [], "task_lists": []}
    for size in sizes:
        source = root / f"source_{size}.dxf"
        doc = ezdxf.new("R2010")
        translations = {}
        for index in range(size):
            entity = doc.modelspace().add_text(f"阀门{index}", dxfattribs={"height": 2.5, "insert": (index % 50, index // 50)})
            translations[entity.dxf.handle] = f"Valve {index}"
        doc.saveas(source)
        extracted, extraction = measured(lambda: TextExtractor().extract_to_excel(str(source), str(root / f"excel_{size}")), repeats)
        assert extracted["texts_count"] == size
        output = root / f"translated_{size}.dxf"
        applied, application = measured(lambda: TextApplier().apply(str(source), str(output), {}, entity_translations=translations), repeats)
        assert applied["translated_entities"] == size
        assert [e.dxf.text for e in ezdxf.readfile(output).modelspace()] == [f"Valve {i}" for i in range(size)]
        service = CADPipelineService()
        def task(_index):
            with source.open("rb") as stream:
                return service.extract_upload(UploadFile(filename=source.name, file=stream), converter_backend="dxf_only")
        _, sequential = measured(lambda: [task(i) for i in range(2)])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results, parallel = measured(lambda: list(pool.map(task, range(2))))
        assert len({r["task_id"] for r in results}) == 2
        assert all(r["text_count"] == size for r in results)
        report["dxf"].append({"entities": size, "extract_excel": extraction, "apply_dxf": application,
                              "two_sequential_extract_tasks": sequential, "two_parallel_extract_tasks": parallel})

    # Independent metadata fixtures measure listing rather than DXF generation.
    for size in history_sizes:
        service = CADPipelineService()
        task_root = root / f"list_tasks_{size}"
        task_root.mkdir()
        service._tasks_root = lambda: task_root
        for index in range(size):
            task_id = f"{index:08x}"
            directory = task_root / task_id
            directory.mkdir(exist_ok=True)
            (directory / "task.json").write_text(json.dumps({"task_id": task_id, "status": "done", "stage": "completed", "created_at": index + 1, "last_activity_at": index + 1, "original_filename": "synthetic.dxf", "text_count": 100}), encoding="utf-8")
        _, migration = measured(lambda: service._task_index().reconcile(force=True))
        # Match application startup: validate changed legacy manifests separately
        # from the first page, rather than concealing the restart scan cost.
        restarted = CADPipelineService()
        restarted._tasks_root = lambda: task_root
        _, startup = measured(lambda: restarted.recover_interrupted_jobs())
        page, cold = measured(lambda: restarted.task_page(limit=100))
        assert page["total"] == size and len(page["data"]) == min(100, size)
        _, hot = measured(lambda: restarted.task_page(limit=100, offset=max(0, size - 100)), repeats)
        # Existing canonical save includes atomic JSON publication and index upsert.
        metadata = json.loads((task_root / "00000000" / "task.json").read_text(encoding="utf-8"))
        metadata["processing_time"] = "benchmark-saved"
        _, save = measured(lambda: restarted._save_task("00000000", metadata), repeats)
        assert restarted.task_page(limit=1)["total"] == size
        last_page = restarted.task_page(limit=100, offset=max(0, size - 100))["data"]
        assert next(item for item in last_page if item["task_id"] == "00000000")["processing_time"] == "benchmark-saved"
        report["task_lists"].append({"history_count": size, "page_size": 100,
                                    "legacy_first_import": migration, "restart_reconciliation": startup,
                                    "restart_first_page": cold, "hot_last_page": hot,
                                    "canonical_manifest_and_index_save": save})

    llm = LLMTranslationService()
    cfg = {"provider": "custom", "format": "openai_compatible", "base_url": "https://llm.invalid/v1", "model": "offline", "api_key": "synthetic", "timeout": 0.1}
    calls = []
    def probe(candidate):
        calls.append(1)
        time.sleep(0.1)
        return llm._probe_result(candidate, True, True, 200, candidate["base_url"], "offline")
    with patch.object(llm, "_probe_network", probe), ThreadPoolExecutor(max_workers=2) as pool:
        results, timing = measured(lambda: list(pool.map(llm._probe_candidate, [cfg, cfg])))
    assert len(calls) == 1 and all(r["success"] for r in results)
    report["probe"] = {"simulated_network_seconds": 0.1, "network_calls": len(calls), **timing}
    bucket = TokenBucket(1, 1, clock=lambda: 100.0)
    reservations = [bucket.acquire(1) for _ in range(4)]
    assert reservations == [0.0, 1.0, 2.0, 3.0]
    report["rate_reservation_seconds"] = reservations
    runtime = dict(cfg, batch_size=1, batch_json=False, parallel_count=2)
    started = []
    lock = threading.Lock()
    cancelled = threading.Event()
    def translate(text, *args, **kwargs):
        with lock:
            started.append(text)
            if len(started) == 2:
                cancelled.set()
        if not cancelled.wait(3):
            raise AssertionError("second worker did not start")
        return "translated"
    with patch.object(llm, "_active_config", lambda: runtime), patch.object(llm, "_compose_system_prompt", lambda *a, **k: "offline"), patch.object(llm, "translate_text", translate):
        try:
            llm.translate_batch([f"阀门{i}" for i in range(100)], should_cancel=cancelled.is_set)
        except RuntimeError as exc:
            assert "cancelled" in str(exc)
        else:
            raise AssertionError("cancel was not surfaced")
    assert len(started) == 2
    report["cancellation"] = {"chunks": 100, "parallel_limit": 2, "calls_started": len(started)}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 1000])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--history-sizes", type=int, nargs="+", default=[100, 1000],
                        help="Metadata history counts, independent of DXF entity counts")
    args = parser.parse_args()
    if args.repeats < 1 or min(args.sizes) < 1 or min(args.history_sizes) < 1:
        parser.error("sizes and repeats must be positive")
    with tempfile.TemporaryDirectory(prefix="cad_offline_benchmark_") as directory:
        # Any accidental network use fails immediately, including dependency calls.
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network is forbidden")), contextlib.redirect_stdout(io.StringIO()):
            report = run(Path(directory), sorted(set(args.sizes)), args.repeats,
                         sorted(set(args.history_sizes)))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
