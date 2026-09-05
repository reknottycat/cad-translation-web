"""The derived task index must stay fast, persistent and subordinate to manifests."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def service(tmp_path):
    from app.services.cad_pipeline_service import CADPipelineService
    result = CADPipelineService()
    result.settings = SimpleNamespace(get_output_path=lambda: tmp_path)
    return result


def save(service, number, **patch):
    task_id = f"{number:08x}"
    service._task_dir(task_id).mkdir(exist_ok=True)
    service._save_task(task_id, {
        "task_id": task_id, "original_filename": "index-test.dxf",
        "status": "done", "stage": "completed", "created_at": number,
        "last_activity_at": number, **patch,
    })
    return task_id


def test_reopened_index_reads_only_page_without_opening_manifests(service, monkeypatch):
    from app.services.cad_pipeline_service import CADPipelineService
    for number in range(1, 121):
        save(service, number)
    assert service.task_page(limit=20)["total"] == 120
    reopened = CADPipelineService()
    reopened.settings = service.settings
    original_read = Path.read_text

    def no_historical_reads(path, *args, **kwargs):
        if path.name == "task.json":
            pytest.fail("A normal indexed page must not read historical manifests")
        return original_read(path, *args, **kwargs)

    with monkeypatch.context() as scope:
        scope.setattr(Path, "read_text", no_historical_reads)
        page = reopened.task_page(limit=20, offset=100)
    assert page["total"] == 120
    assert len(page["data"]) == 20
    assert page["data"][0]["task_id"] == f"{20:08x}"


def test_another_service_update_is_immediately_visible(service):
    from app.services.cad_pipeline_service import CADPipelineService
    task_id = save(service, 1)
    assert service.task_page()["data"][0]["status"] == "done"
    other = CADPipelineService()
    other.settings = service.settings
    other._update_task(task_id, status="error", stage="failed", last_error="fixture")
    assert service.task_page()["data"][0]["status"] == "error"


def test_delete_and_late_writer_do_not_resurrect_index_entry(service):
    task_id = save(service, 1)
    assert service.task_page()["total"] == 1
    service.delete_task(task_id)
    service._update_task(task_id, status="done")
    assert service.task_page()["total"] == 0
    assert not service._task_dir(task_id).exists()


def test_dirty_index_reconciles_canonical_change(service):
    from app.utils.locking import atomic_write_json
    task_id = save(service, 1)
    service.task_page()
    path = service._task_meta_path(task_id)
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata.update(status="partial", stage="completed", failed_count=2)
    atomic_write_json(path, metadata)
    service._task_index().dirty.touch()
    assert service.task_page()["data"][0]["status"] == "partial"
    assert not service._task_index().dirty.exists()


def test_malformed_manifest_cannot_break_history_import(service):
    save(service, 1)
    invalid = service._task_dir("00000002")
    invalid.mkdir()
    (invalid / "task.json").write_text('{"task_id":"ffffffff"}', encoding="utf-8")
    assert service.task_page()["total"] == 1


def test_broken_derived_index_keeps_manifests_available(service):
    save(service, 1)
    service.task_page()
    service._task_index().path.write_bytes(b"invalid sqlite index")
    assert service.task_page()["data"][0]["task_id"] == "00000001"
    service.recover_interrupted_jobs()
    assert service._task_meta_path("00000001").exists()


def test_startup_recovers_abandoned_jobs_but_keeps_live_owner(service):
    import os
    from app.services.cad_task_jobs import _PROCESS_STARTED
    abandoned = save(service, 1, status="processing", stage="translating", owner_pid=-1)
    live = save(service, 2, status="queued", stage="queued", job_queued=True,
                owner_pid=os.getpid(), owner_started=_PROCESS_STARTED)
    service.recover_interrupted_jobs()
    assert service._load_task(abandoned)["stage"] == "interrupted"
    assert service._load_task(abandoned)["status"] == "error"
    assert service._load_task(live)["status"] == "queued"
