"""Behavioral regressions for durable jobs, entity addressing and recovery."""
from __future__ import annotations

import io
import threading
from concurrent.futures import ThreadPoolExecutor

import ezdxf
import pandas as pd
import pytest
from fastapi import UploadFile


@pytest.fixture
def service():
    from app.services.cad_pipeline_service import cad_pipeline_service
    cad_pipeline_service.clear_all_tasks()
    return cad_pipeline_service


def drawing(*texts):
    doc = ezdxf.new()
    for index, value in enumerate(texts):
        doc.modelspace().add_text(value, dxfattribs={"insert": (index * 10, 0)})
    stream = io.StringIO()
    doc.write(stream)
    return UploadFile(filename="drawing.dxf", file=io.BytesIO(stream.getvalue().encode()))


def test_same_original_can_receive_different_entity_translations(service):
    extracted = service.extract_upload(drawing("相同", "相同"), converter_backend="dxf_only")
    task_id = extracted["task_id"]
    translations = [{"record_id": row["id"], "original": "相同", "translated": text}
                    for row, text in zip(extracted["texts"], ["First", "Second"])]
    result = service.apply_translation(task_id, translations)
    path, _ = service.resolve_download(task_id, "translated_cad")
    assert [e.dxf.text for e in ezdxf.readfile(path).modelspace().query("TEXT")] == ["First", "Second"]
    assert result["translation_count"] == 2
    meta = service._load_task(task_id)
    frame = pd.read_excel(service._task_dir(task_id) / meta["translated_excel_filename"])
    assert frame["译文"].tolist() == ["First", "Second"]


def test_background_submission_does_not_wait_for_extraction(service, monkeypatch):
    from app.services import cad_task_jobs
    entered, release = threading.Event(), threading.Event()
    original = service._extract_reserved

    def blocked(task_id):
        entered.set()
        assert release.wait(10)
        return original(task_id)

    with ThreadPoolExecutor(max_workers=1) as pool:
        monkeypatch.setattr(cad_task_jobs, "_executor", pool)
        monkeypatch.setattr(service, "_extract_reserved", blocked)
        try:
            result = service.submit_upload(drawing("墙"), converter_backend="dxf_only", extract_only=True)
            assert result["status"] == "queued"
            assert entered.wait(5)
            assert service._load_task(result["task_id"])["original_filename"] == "drawing.dxf"
        finally:
            release.set()
    assert service._load_task(result["task_id"])["status"] == "done"


def test_independent_extractions_do_not_hold_global_registration_lock(service, monkeypatch):
    barrier = threading.Barrier(2)
    original = service.processor.extract_texts_to_excel

    def concurrent(*args, **kwargs):
        barrier.wait(timeout=10)
        return original(*args, **kwargs)

    monkeypatch.setattr(service.processor, "extract_texts_to_excel", concurrent)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(service.extract_upload, drawing("墙"), converter_backend="dxf_only")
                   for _ in range(2)]
        assert len({future.result(timeout=15)["task_id"] for future in results}) == 2


def test_repeated_execution_fails_without_waiting(service):
    from app.services.cad_task_jobs import TaskBusyError
    task_id = service.reserve_upload(drawing("墙"))
    held, release = threading.Event(), threading.Event()

    def claim():
        with service._task_execution_claim(task_id):
            held.set()
            assert release.wait(10)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(claim)
        try:
            assert held.wait(5)
            with pytest.raises(TaskBusyError):
                service.resume_task(task_id)
        finally:
            release.set()
        future.result(timeout=5)


def test_partial_output_does_not_skip_retry_and_missing_checkpoint_records(service, monkeypatch):
    extracted = service.extract_upload(drawing("墙", "门"), converter_backend="dxf_only")
    task_id = extracted["task_id"]
    first = {"record_id": extracted["texts"][0]["id"], "original": "墙", "translated": "Wall"}
    service.apply_translation(task_id, [first])
    service._save_checkpoint(task_id, [first])
    service._update_task(task_id, status="partial", stage="completed", failed_count=1)
    calls = []

    def translate(**kwargs):
        calls.append(kwargs["original_texts"])
        return [{"record_id": kwargs["record_ids"][0], "original": "门", "translated": "Door"}]

    monkeypatch.setattr(service, "_run_translation_with_logging", translate)
    service.resume_task(task_id)
    assert calls == [["门"]]
    path, _ = service.resolve_download(task_id, "translated_cad")
    assert [e.dxf.text for e in ezdxf.readfile(path).modelspace().query("TEXT")] == ["Wall", "Door"]
    assert service._load_task(task_id)["failed_count"] == 0


def test_download_snapshot_survives_task_deletion(service):
    extracted = service.extract_upload(drawing("墙"), converter_backend="dxf_only")
    snapshot, _, _ = service.snapshot_download(extracted["task_id"], "excel")
    try:
        service.delete_task(extracted["task_id"])
        assert not service._task_dir(extracted["task_id"]).exists()
        assert len(pd.read_excel(snapshot)) == 1
    finally:
        snapshot.unlink(missing_ok=True)


def test_resume_inherits_language_and_layout(service, monkeypatch):
    extracted = service.extract_upload(drawing("墙"), target_language="fr", converter_backend="dxf_only")
    task_id = extracted["task_id"]
    service._update_task(task_id, job_options={"translation_mode": "add", "font_size_reduction": 0.5})
    calls = []

    def translate(**kwargs):
        calls.append(kwargs["target_language"])
        return [{"record_id": kwargs["record_ids"][0], "original": "墙", "translated": "Mur"}]

    monkeypatch.setattr(service, "_run_translation_with_logging", translate)
    service.resume_task(task_id)
    assert calls == ["fr"]
    metadata = service._load_task(task_id)
    assert metadata["translation_mode"] == "add"
    assert metadata["font_size_reduction"] == 0.5


def test_invalid_resume_is_rejected_before_queueing(service, monkeypatch):
    from app.services import cad_task_jobs
    monkeypatch.setattr(cad_task_jobs._executor, "submit", lambda *args: pytest.fail("Invalid job queued"))
    with pytest.raises(FileNotFoundError):
        service.submit_resume("deadbeef")
    task_id = service.extract_upload(drawing("墙"), target_language="fr")["task_id"]
    with pytest.raises(ValueError, match="original target language"):
        service.submit_resume(task_id, target_language="en")
    assert not service._load_task(task_id).get("resume_queued")


def test_resume_registration_failure_releases_capacity(service, monkeypatch):
    from app.services import cad_task_jobs
    capacity = threading.BoundedSemaphore(1)
    monkeypatch.setattr(cad_task_jobs, "_capacity", capacity)
    task_id = service.extract_upload(drawing("墙"))["task_id"]
    monkeypatch.setattr(service, "_clear_task_cancel", lambda *args: (_ for _ in ()).throw(OSError("disk failure")))
    with pytest.raises(OSError, match="disk failure"):
        service.submit_resume(task_id)
    assert capacity.acquire(blocking=False)
    capacity.release()


def test_original_artifact_urls_require_admin_token(monkeypatch):
    import app.config as config_module
    from app.main import app
    from fastapi.testclient import TestClient
    monkeypatch.setenv("ENABLE_ADMIN_GUARD", "true")
    monkeypatch.setenv("ADMIN_API_TOKEN", "test-only-token")
    config_module._settings = None
    with TestClient(app) as client:
        for path in ("/outputs/private.xlsx", "/uploads/private.dxf"):
            assert client.get(path).status_code == 403
        assert client.post("/api/translate", json={"text": "墙", "target_lang": "en"}).status_code == 403
