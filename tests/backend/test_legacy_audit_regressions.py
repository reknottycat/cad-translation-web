"""Regressions for legacy SQL/Celery paths retained by the application."""

from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError

from app.database import (
    ProcessingTask,
    Project,
    ProjectFile,
    SessionLocal,
    init_db,
)


@pytest.mark.parametrize("managed", [True, False])
def test_excel_cleanup_uses_configured_upload_root(tmp_path, monkeypatch, managed):
    from app.services.tasks import translation_tasks as tasks

    uploads = tmp_path / "custom-inputs"
    source_dir = uploads if managed else tmp_path / "external" / "uploads"
    source_dir.mkdir(parents=True)
    source = source_dir / "drawing.xlsx"
    source.write_bytes(b"fixture")
    monkeypatch.setattr(tasks, "settings", SimpleNamespace(
        get_upload_path=lambda: uploads, get_output_path=lambda: tmp_path / "outputs"))
    monkeypatch.setattr(tasks.translate_excel_task, "update_state", lambda **kwargs: None)
    monkeypatch.setattr(tasks.ai_excel_processor, "translate_excel_file", lambda **kwargs: {})
    monkeypatch.setattr(tasks.ai_excel_processor, "create_translation_report", lambda *args: None)
    assert tasks.translate_excel_task.run(str(source))["success"] is True
    assert source.exists() is not managed


@pytest.fixture(autouse=True)
def clean_sql_tables():
    init_db()
    db = SessionLocal()
    try:
        db.query(ProcessingTask).delete()
        db.query(ProjectFile).delete()
        db.query(Project).delete()
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.query(ProcessingTask).delete()
        db.query(ProjectFile).delete()
        db.query(Project).delete()
        db.commit()
    finally:
        db.close()


def _project(db, *, status="created") -> Project:
    value = Project(name="legacy", status=status, target_language="en")
    db.add(value)
    db.commit()
    db.refresh(value)
    return value


def _file(db, project_id: int, path: Path, content_hash: str = "hash") -> ProjectFile:
    value = ProjectFile(
        project_id=project_id,
        filename=path.name,
        original_filename=path.name,
        file_path=str(path),
        file_size=path.stat().st_size,
        file_type="dxf",
        content_hash=content_hash,
        status="uploaded",
    )
    db.add(value)
    db.commit()
    db.refresh(value)
    return value


def test_cad_processor_delegates_single_file_to_canonical_pipeline(
    monkeypatch, tmp_path
):
    from app.services.cad_pipeline_service import cad_pipeline_service
    from app.services.cad_processor import CADProcessor

    source = tmp_path / "drawing.dxf"
    source.write_bytes(b"DXF")
    seen = {}

    def process(upload, target, backend, extract_only, mode, font, reduction):
        seen.update(
            filename=upload.filename,
            target=target,
            extract_only=extract_only,
            mode=mode,
        )
        return {"task_id": "abc12345", "status": "done"}

    monkeypatch.setattr(cad_pipeline_service, "process_upload", process)
    result = asyncio.run(
        CADProcessor().process_cad_file(
            input_file=str(source), auto_translate=True, target_language="ja"
        )
    )
    assert result["task_id"] == "abc12345"
    assert seen == {
        "filename": "drawing.dxf",
        "target": "ja",
        "extract_only": False,
        "mode": "replace",
    }


def test_cad_processor_has_real_project_batch_contract(monkeypatch):
    from app.services.cad_processor import CADProcessor

    processor = CADProcessor()

    async def process(**kwargs):
        if kwargs["input_file"].endswith("bad.dxf"):
            raise ValueError("bad drawing")
        return {"task_id": "ok"}

    monkeypatch.setattr(processor, "process_cad_file", process)
    result = asyncio.run(
        processor.process_project_files(
            7, ["good.dxf", "bad.dxf"], {"auto_translate": False}
        )
    )
    assert result["converted_files"] == 1
    assert result["failed_files"] == 1
    assert len(result["processed_files"]) == 2


def test_legacy_translation_task_awaits_async_processor(monkeypatch):
    import app.services.cad_processor as processor_module
    from app.services.tasks.translation_tasks import cad_file_translate_task

    calls = []

    class FakeProcessor:
        async def process_cad_file(self, **kwargs):
            calls.append(kwargs)
            await asyncio.sleep(0)
            return {"task_id": "done"}

    monkeypatch.setattr(processor_module, "CADProcessor", FakeProcessor)
    result = cad_file_translate_task.apply(
        args=(
            4,
            ["one.dxf"],
            {"target_language": "fr", "auto_translate": False},
        ),
        task_id="legacy-translation-test",
    ).get()
    assert result["successful_files"] == 1
    assert calls[0]["input_file"] == "one.dxf"
    assert calls[0]["target_language"] == "fr"


def test_celery_callbacks_preserve_soft_failure_result(monkeypatch):
    from app.services import celery_app as celery_module

    updates = []
    monkeypatch.setattr(
        celery_module,
        "update_task_status",
        lambda *args, **kwargs: updates.append((args, kwargs)),
    )
    failure = {
        "success": False,
        "message": "translation failed",
        "error": "bad gateway",
    }

    celery_module.task_postrun_handler(
        task_id="soft-failure", retval=failure, state="SUCCESS"
    )
    celery_module.CADTask().on_success(
        failure, "cad-soft-failure", (), {}
    )

    assert [call[0][1] for call in updates] == ["failure", "failure"]
    assert all(call[0][4] == "bad gateway" for call in updates)


def test_project_file_hash_unique_within_project(tmp_path):
    db = SessionLocal()
    try:
        project = _project(db)
        first = tmp_path / "one.dxf"
        second = tmp_path / "two.dxf"
        first.write_bytes(b"same")
        second.write_bytes(b"same")
        _file(db, project.id, first, "same-hash")
        duplicate = ProjectFile(
            project_id=project.id,
            filename=second.name,
            original_filename=second.name,
            file_path=str(second),
            file_size=4,
            file_type="dxf",
            content_hash="same-hash",
            status="uploaded",
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_upload_route_rejects_duplicate_content_and_keeps_one_row():
    from app.routers import files as routes

    db = SessionLocal()
    try:
        project = _project(db)
        first = UploadFile(filename="one.dxf", file=io.BytesIO(b"same-dxf"))
        second = UploadFile(filename="renamed.dxf", file=io.BytesIO(b"same-dxf"))
        first_result = asyncio.run(routes.upload_files(project.id, [first], db))
        second_result = asyncio.run(routes.upload_files(project.id, [second], db))
        assert first_result[0].success is True
        assert second_result[0].success is False
        assert second_result[0].error == "文件已存在"
        rows = db.query(ProjectFile).filter_by(project_id=project.id).all()
        assert len(rows) == 1
        assert rows[0].content_hash
    finally:
        db.close()


def test_start_persists_task_before_dispatch_and_returns_eager_final_state(
    monkeypatch, tmp_path
):
    from app.routers import projects as routes

    db = SessionLocal()
    try:
        project = _project(db)
        source = tmp_path / "drawing.dxf"
        source.write_bytes(b"DXF")
        _file(db, project.id, source)
        observed = {}

        def dispatch(*, args, task_id):
            worker_db = SessionLocal()
            try:
                row = worker_db.query(ProcessingTask).filter_by(task_id=task_id).one()
                observed["status_before_dispatch"] = row.status
                row.status = "success"
                row.progress = 1.0
                worker_project = worker_db.query(Project).filter_by(id=args[0]).one()
                worker_project.status = "completed"
                worker_db.commit()
            finally:
                worker_db.close()

        monkeypatch.setattr(routes.process_project_batch_task, "apply_async", dispatch)
        result = asyncio.run(routes.start_project_processing(project.id, db))
        assert observed["status_before_dispatch"] == "pending"
        assert result["task_status"] == "success"
        assert result["project_status"] == "completed"
    finally:
        db.close()


def test_duplicate_project_start_is_atomically_rejected(monkeypatch, tmp_path):
    from app.routers import projects as routes

    first_db = SessionLocal()
    second_db = SessionLocal()
    try:
        project = _project(first_db)
        source = tmp_path / "drawing.dxf"
        source.write_bytes(b"DXF")
        _file(first_db, project.id, source)
        monkeypatch.setattr(
            routes.process_project_batch_task, "apply_async", lambda **kwargs: None
        )
        first = asyncio.run(routes.start_project_processing(project.id, first_db))
        assert first["project_status"] == "processing"
        with pytest.raises(HTTPException) as error:
            asyncio.run(routes.start_project_processing(project.id, second_db))
        assert error.value.status_code == 409
    finally:
        first_db.close()
        second_db.close()


def test_summary_always_combines_sql_and_canonical_tasks(monkeypatch):
    from app.routers import projects as routes

    db = SessionLocal()
    try:
        project = _project(db, status="completed")
        sql_task = ProcessingTask(
            project_id=project.id,
            task_id="sql-task",
            task_type="batch_process",
            status="success",
            progress=1.0,
        )
        db.add(sql_task)
        db.commit()
        monkeypatch.setattr(
            routes.cad_pipeline_service,
            "list_tasks",
            lambda: [
                {
                    "task_id": "json-task",
                    "original_filename": "drawing.dxf",
                    "status": "error",
                    "stage": "failed",
                    "text_count": 3,
                    "translation_count": 1,
                    "total_chunks": 2,
                    "completed_chunks": 1,
                    "created_at": 100.0,
                }
            ],
        )
        summary = asyncio.run(routes.get_projects_summary(db))
        ids = {task["task_id"] for task in summary["recent_tasks"]}
        assert {"sql-task", "json-task"} <= ids
        assert summary["counts"]["total_projects"] == 2
        assert summary["artifact_status_breakdown"] == {"error": 1}
        assert summary["alerts"]["failed_tasks"] == 1
    finally:
        db.close()


def test_delete_project_removes_owned_upload_and_output_files(tmp_path):
    from app.routers import projects as routes

    db = SessionLocal()
    try:
        project = _project(db)
        upload_dir = routes.settings.get_upload_path() / f"project_{project.id}"
        upload_dir.mkdir(parents=True, exist_ok=True)
        original = upload_dir / "drawing.dxf"
        original.write_bytes(b"DXF")
        output = routes.settings.get_output_path() / f"project-{project.id}.xlsx"
        output.write_bytes(b"xlsx")
        row = _file(db, project.id, original)
        row.excel_path = str(output)
        db.commit()
        result = asyncio.run(routes.delete_project(project.id, db))
        assert result["cleanup_complete"] is True
        assert not original.exists()
        assert not output.exists()
        assert not upload_dir.exists()
    finally:
        db.close()


def test_batch_download_removes_temp_directory_after_response(tmp_path):
    from app.routers import files as routes

    db = SessionLocal()
    try:
        project = _project(db)
        source = routes.settings.get_upload_path() / f"project_{project.id}" / "d.dxf"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"DXF")
        _file(db, project.id, source)
        response = asyncio.run(routes.create_batch_download(project.id, "all", db))
        zip_path = Path(response.path)
        temp_dir = zip_path.parent
        assert zip_path.exists()
        asyncio.run(response.background())
        assert not temp_dir.exists()
    finally:
        db.close()
