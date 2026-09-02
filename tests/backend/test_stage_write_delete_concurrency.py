#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real multiprocessing regression tests for task-**stage** product writes
racing ``delete_task`` / ``clear_all_tasks``.

The core invariant under test, for every stage that creates/writes products
inside a task directory:

    After a task directory is deleted (delete_task / clear_all_tasks), no
    still-running worker may *recreate* task_dir / task.json / task.log /
    checkpoint / products (translated DXF, translated Excel, DocuTranslate
    JSON artifacts), and no half-written/orphaned file may survive.

Two uncovered races are covered here:

  1. DocuTranslate working-dir race:
     ``_run_docutranslate_translation_with_logging`` used to pass
     ``working_dir = <task_dir>/docutranslate`` to
     ``DocuTranslateJsonAdapter.translate_records``, which unconditionally does
     ``mkdir(parents=True, exist_ok=True)`` and writes cad_records.json /
     translated JSON there.  Because no per-task lifecycle lock was held between
     ``ensure_not_cancelled()`` and those writes, a delete could remove task_dir
     and a running worker would then *re-create* the deleted task directory and
     its orphan products.  Fix: DocuTranslate now runs in a per-run staging
     directory *outside* the task tree (``outputs/cad_work/docutranslate``),
     which delete/clear never remove, so a worker can never recreate task_dir.

  2. apply_translation output race:
     ``apply_translation`` wrote the translated DXF (via the pipeline) and the
     translated Excel (via ``_write_translated_excel``) plus the metadata
     write-back *without* holding the per-task lifecycle lock.  A delete could
     interleave and the worker would write half-products into a deleted (then
     re-created) task_dir.  Fix: the whole apply operation — DXF/Excel output
     writes + status write-back — now runs under the per-task lifecycle lock
     after confirming the task still exists, so delete waits for a consistent
     apply to finish, then removes everything.

Each scenario runs real cross-process delete/apply via ``multiprocessing`` and
asserts the final tasks-root contains no re-created task_dir, no orphan
``docutranslate``/``translated_*`` products and no stale cancel marker.

Run: python -m pytest tests/backend/test_stage_write_delete_concurrency.py -v
"""

import io as _io
import json
import multiprocessing
import os
import sys
import time
from pathlib import Path

import pytest

# Ensure backend modules are importable.
BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _make_upload_bytes(label: str) -> tuple[Path, bytes]:
    """Return (temp_path, bytes) for a tiny deterministic DXF containing text."""
    import tempfile as tmp
    import ezdxf

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_text(f"{label} text one", dxfattribs={"height": 2.5})
    msp.add_text(f"{label} text two", dxfattribs={"height": 2.5})
    tmpf = tmp.NamedTemporaryFile(suffix=".dxf", delete=False)
    tmpf.close()
    tmp_path = Path(tmpf.name)
    doc.saveas(str(tmp_path))
    data = tmp_path.read_bytes()
    tmp_path.unlink(missing_ok=True)
    return tmp_path, data


def _mp_build_svc(env_file):
    os.environ["CAD_TRANSLATION_ENV_FILE"] = env_file
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService
    return CADPipelineService()


def _build_local_svc():
    """Build a CADPipelineService in the *test* process (fresh settings)."""
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService
    return CADPipelineService()


def _create_task(svc, label: str) -> str:
    """Create a real task via extract_upload inside the current process."""
    from fastapi import UploadFile
    tmp_path, data = _make_upload_bytes(label)
    upload = UploadFile(filename=tmp_path.name, file=_io.BytesIO(data))
    result = svc.extract_upload(
        uploaded_file=upload,
        target_language="en",
        converter_backend="dxf_only",
    )
    return result["task_id"]


def _assert_tasks_root_clean(svc, forbidden_suffixes=()) -> None:
    """Assert tasks root holds no task with the forbidden suffix products and no
    orphan docutranslate dir / stray files."""
    tasks_root = svc._tasks_root()
    if not tasks_root.exists():
        return
    for child in tasks_root.iterdir():
        if child.is_dir():
            # No task dir may contain a re-created docutranslate staging subtree.
            assert not (child / "docutranslate").exists(), (
                f"re-created docutranslate dir under deleted task: {child / 'docutranslate'}"
            )
            for suffix in forbidden_suffixes:
                for p in child.rglob(f"*{suffix}"):
                    assert False, f"orphan '{suffix}' product re-created in {child}: {p}"
        else:
            assert False, f"stray non-directory file left in tasks root: {child}"


# ---------------------------------------------------------------------------
# Test 1: DocuTranslate external staging vs delete
# ---------------------------------------------------------------------------

def _mp_docutranslate_worker(
    env_file,
    result_queue,
    write_started_event,
    allow_finish_event,
):
    """Run _run_docutranslate_translation_with_logging with a fake adapter whose
    translate_records writes cad_records.json into the *given* working_dir,
    signals, then (after delete races in) re-mkdirs + writes the translated JSON
    there — faithfully mirroring the real DocuTranslateJsonAdapter behavior.
    """
    from app.services.docutranslate_adapter import (
        CadTranslatedRecord,
        CadTranslationBatchResult,
    )

    svc = _mp_build_svc(env_file)

    # A fake DocuTranslate workflow adapter: writes intermediate JSON into the
    # working_dir it is handed, exactly like DocuTranslateJsonAdapter.
    class FakeAdapter:
        def __init__(self, wp_event, finish_event):
            self.wp_event = wp_event
            self.finish_event = finish_event
            self.captured_working_dir = None

        def translate_records(self, records, *, working_dir, **kwargs):
            wp = Path(working_dir)
            self.captured_working_dir = str(wp)
            # Simulate DocuTranslateJsonAdapter.translate_records:
            wp.mkdir(parents=True, exist_ok=True)
            (wp / "cad_records.json").write_text("{}", encoding="utf-8")
            result_queue.put(("working_dir", str(wp)))
            self.wp_event.set()
            # Wait while the test deletes the task dir concurrently.
            if not self.finish_event.wait(timeout=30):
                raise RuntimeError("docutranslate allow_finish timeout")
            # Simulate DirectJsonWorkflowRunner.translate_json_file which does
            # output_dir.mkdir then save_as_json into that output_dir:
            wp.mkdir(parents=True, exist_ok=True)
            out = wp / "cad_records.translated.json"
            out.write_text(
                json.dumps(
                    {
                        "records": [
                            {"record_id": "a", "source_text": "bonjour"},
                            {"record_id": "b", "source_text": "monde"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            translated = [
                CadTranslatedRecord(record_id="a", source_text="hello", translated_text="bonjour"),
                CadTranslatedRecord(record_id="b", source_text="world", translated_text="monde"),
            ]
            return CadTranslationBatchResult(
                records=translated,
                input_json_path=wp / "cad_records.json",
                translated_json_path=out,
                input_payload={},
                translated_payload={},
            )

    fake = FakeAdapter(write_started_event, allow_finish_event)
    svc._build_docutranslate_adapter = lambda runtime, lang: fake

    try:
        task_id = _create_task(svc, "docu")
        result_queue.put(("task_id", task_id))

        translations = svc._run_docutranslate_translation_with_logging(
            task_id=task_id,
            original_texts=["hello", "world"],
            target_language="en",
            runtime={"model": "m", "parallel_count": 1},
            batch_size=10,
            total_chunks=1,
            ensure_not_cancelled=lambda: _raise_if(svc, task_id),
            record_ids=["a", "b"],
        )
        result_queue.put(("translations", len(translations)))
        result_queue.put(("worker_done", True))
    except Exception as exc:  # pragma: no cover - surfaced via result_queue
        result_queue.put(("error", repr(exc)))


def _raise_if(svc, task_id):
    # Re-import lazily to avoid import cycles under spawn.
    from app.services.cad_pipeline_service import TaskCancelledError

    if svc._is_task_cancelled(task_id):
        raise TaskCancelledError("cancelled")


def _mp_delete(env_file, task_id, result_queue):
    svc = _mp_build_svc(env_file)
    try:
        svc.delete_task(task_id)
        result_queue.put(("delete_done", True))
    except Exception as exc:  # pragma: no cover
        result_queue.put(("error", repr(exc)))


def test_docutranslate_staging_never_recreates_deleted_task_dir():
    """While a DocuTranslate translation is writing its working artifacts, a
    concurrent delete_task must be able to remove the task dir, and the worker
    must NOT re-create it (nor an orphan docutranslate/ subtree) afterwards."""
    env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    assert env_file, "CAD_TRANSLATION_ENV_FILE must be set by conftest"

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    write_started = ctx.Event()
    allow_finish = ctx.Event()

    worker = ctx.Process(
        target=_mp_docutranslate_worker,
        args=(env_file, q, write_started, allow_finish),
    )
    worker.start()

    # Learn the task id created by the worker.
    task_id = None
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            k, v = q.get(timeout=0.5)
        except Exception:
            continue
        if k == "task_id":
            task_id = v
            break
    assert task_id, "worker never created a task"

    # Wait until the adapter has begun writing into its working_dir.
    assert write_started.wait(timeout=20), "docutranslate worker never started writing"

    # Delete the task dir concurrently while the worker is mid-translation.
    deleter = ctx.Process(target=_mp_delete, args=(env_file, task_id, q))
    deleter.start()
    deleter.join(timeout=20)
    assert not deleter.is_alive(), "delete timed out"
    assert deleter.exitcode == 0, f"deleter exited {deleter.exitcode}"
    saw_delete = False
    dl = time.time() + 10
    while time.time() < dl:
        try:
            k, v = q.get(timeout=0.5)
        except Exception:
            continue
        if k == "delete_done":
            saw_delete = True
            break
    assert saw_delete, "deleter never reported delete_done"

    # Now let the docutranslate worker finish (its re-mkdir + translated write).
    allow_finish.set()
    worker.join(timeout=25)
    assert not worker.is_alive(), "docutranslate worker timed out"
    assert worker.exitcode == 0, f"worker exited {worker.exitcode}"

    results = {}
    while not q.empty():
        try:
            k, v = q.get(timeout=1)
            results[k] = v
        except Exception:
            break

    # The worker may either complete cleanly (delete happened after it finished)
    # or be cancelled (delete raced in while it was translating).  Both are
    # correct outcomes; the invariant is that nothing is re-created.
    assert results.get("error") is None or "cancelled" in str(results.get("error")).lower(), (
        f"worker failed unexpectedly: {results}"
    )

    svc = _build_local_svc()
    # The deleted task dir must not have been re-created by the worker, and no
    # orphan docutranslate subtree may survive anywhere in the tasks root.
    assert not svc._task_dir(task_id).exists(), (
        "worker re-created a deleted task dir — DocuTranslate must run outside the task tree"
    )
    _assert_tasks_root_clean(svc)
    assert not svc._cancel_marker_path(task_id).exists(), (
        "stale cancel marker left for deleted task"
    )


# ---------------------------------------------------------------------------
# Test 2: apply_translation DXF/Excel outputs vs delete
# ---------------------------------------------------------------------------

def _mp_apply_worker(
    env_file,
    result_queue,
    apply_started_event,
    allow_finish_event,
):
    """Run apply_translation in a separate process with the pipeline DXF apply
    monkey-patched to (a) write the translated DXF into task_dir, (b) signal
    that it is mid-write, then (c) wait so the delete can be attempted while
    apply holds (under the fix) the per-task lifecycle lock."""
    svc = _mp_build_svc(env_file)

    def fake_run_apply_only(dxf_file, task_dir, translation_map, **_kwargs):
        # Simulate the pipeline writing translated_<name>.dxf into task_dir.
        out = Path(task_dir) / f"translated_{Path(dxf_file).name}"
        out.write_text("simulated-dxf-output", encoding="utf-8")
        result_queue.put(("apply_wrote_dxf", str(out)))
        apply_started_event.set()
        if not allow_finish_event.wait(timeout=30):
            raise RuntimeError("apply allow_finish timeout")
        return {"output_file": str(out), "translated_entities": []}

    svc._pipeline.run_apply_only = fake_run_apply_only

    try:
        task_id = _create_task(svc, "apply")
        result_queue.put(("task_id", task_id))

        result = svc.apply_translation(
            task_id=task_id,
            translations=[
                {"original": "hello", "translated": "un"},
                {"original": "world", "translated": "deux"},
            ],
            translation_mode="replace",
        )
        result_queue.put(("apply_result", result["translation_count"]))
        result_queue.put(("worker_done", True))
    except Exception as exc:  # pragma: no cover - surfaced via result_queue
        result_queue.put(("error", repr(exc)))


def _mp_delete_waiting(env_file, task_id, result_queue, allowed):
    """delete_task that must block until 'allowed' (because the apply worker
    holds the per-task lifecycle lock).  Records whether it blocked."""
    svc = _mp_build_svc(env_file)
    try:
        svc.delete_task(task_id)
        result_queue.put(("delete_done", True))
    except Exception as exc:  # pragma: no cover
        result_queue.put(("error", repr(exc)))


def test_apply_outputs_serialized_with_delete_no_orphan():
    """delete_task requested while apply_translation is writing its DXF/Excel
    outputs must be serialized behind the per-task lifecycle lock: it waits for
    the apply to finish, then fully removes the task dir — never leaving a
    half-written translated DXF/Excel behind and never letting the worker
    re-create a deleted task_dir."""
    env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    assert env_file, "CAD_TRANSLATION_ENV_FILE must be set by conftest"

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    apply_started = ctx.Event()
    allow_finish = ctx.Event()

    worker = ctx.Process(
        target=_mp_apply_worker,
        args=(env_file, q, apply_started, allow_finish),
    )
    worker.start()

    task_id = None
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            k, v = q.get(timeout=0.5)
        except Exception:
            continue
        if k == "task_id":
            task_id = v
            break
    assert task_id, "apply worker never created a task"

    # Wait until apply has written the translated DXF (mid-apply).
    assert apply_started.wait(timeout=20), "apply worker never started DXF write"

    # Attempt delete while apply is mid-write.
    deleter = ctx.Process(target=_mp_delete_waiting, args=(env_file, task_id, q, allow_finish))
    deleter.start()

    # Under the fix, apply holds the per-task lifecycle lock while writing its
    # outputs, so delete must block until the apply finishes.
    time.sleep(0.8)
    assert deleter.is_alive(), (
        "delete_task proceeded while apply_translation was writing outputs — "
        "apply must hold the per-task lifecycle lock"
    )

    # Let apply finish (writes translated Excel + metadata, releases the lock);
    # delete then proceeds and fully removes the task dir.
    allow_finish.set()
    worker.join(timeout=25)
    deleter.join(timeout=25)
    assert not worker.is_alive(), "apply worker timed out"
    assert not deleter.is_alive(), "deleter timed out"
    assert worker.exitcode == 0, f"apply worker exited {worker.exitcode}"
    assert deleter.exitcode == 0, f"deleter exited {deleter.exitcode}"

    results = {}
    while not q.empty():
        try:
            k, v = q.get(timeout=1)
            results[k] = v
        except Exception:
            break

    assert results.get("worker_done") is True, f"apply worker failed: {results}"
    assert results.get("delete_done") is True

    svc = _build_local_svc()
    # Final invariant: task dir fully gone, no translated DXF/Excel orphans, no
    # stale cancel marker.
    assert not svc._task_dir(task_id).exists(), (
        "task dir survived/regenerated after delete — apply outputs must not "
        "re-create a deleted task dir"
    )
    _assert_tasks_root_clean(svc, forbidden_suffixes=(".dxf", ".xlsx"))
    assert not svc._cancel_marker_path(task_id).exists(), (
        "stale cancel marker left for deleted task"
    )


# ---------------------------------------------------------------------------
# Test 3: parallel — different tasks' processing stays parallel (no global
# serialization introduced by the stage-lock fixes).
# ---------------------------------------------------------------------------

def _mp_apply_only(env_file, task_id, result_queue):
    """Run only apply_translation on an already-created task (no creation, no
    extraction), with a fake DXF applier that sleeps ~1s and records its enter /
    exit timestamps so the test can verify real-time overlap."""
    import time as _time

    svc = _mp_build_svc(env_file)

    def fake_run_apply_only(dxf_file, task_dir, translation_map, **_kwargs):
        out = Path(task_dir) / f"translated_{Path(dxf_file).name}"
        out.write_text("simulated-dxf-output", encoding="utf-8")
        result_queue.put(("enter", task_id, _time.time()))
        _time.sleep(1.0)  # modest per-task processing time
        result_queue.put(("exit", task_id, _time.time()))
        return {"output_file": str(out), "translated_entities": []}

    svc._pipeline.run_apply_only = fake_run_apply_only
    try:
        svc.apply_translation(
            task_id=task_id,
            translations=[
                {"original": "hello", "translated": "one"},
                {"original": "world", "translated": "two"},
            ],
        )
        result_queue.put(("done", task_id))
    except Exception as exc:  # pragma: no cover
        result_queue.put(("error", repr(exc)))


def test_distinct_tasks_still_process_in_parallel():
    """Two apply/processing tasks on *distinct* tasks must run concurrently, not
    globally serialized by the new per-task stage-locking.  Each apply holds only
    its own per-task lifecycle lock and sleeps ~1s in the (fake) DXF apply.  If
    they were globally serialized they would execute strictly back-to-back, so
    the second apply's start would be after the first apply's finish.  We assert
    the two applies *overlap in real time*: both ``enter`` stamps occur before
    the earliest ``exit`` stamp.  (Task creation is deliberately not timed here:
    it is serialized by the pre-existing global creation/clear coordination lock
    by design.)"""
    env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    assert env_file, "CAD_TRANSLATION_ENV_FILE must be set by conftest"

    # Pre-create two tasks in the main process so only the apply phase is timed.
    svc = _build_local_svc()
    task_a = _create_task(svc, "paralpha")
    task_b = _create_task(svc, "parbeta")

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()

    p1 = ctx.Process(target=_mp_apply_only, args=(env_file, task_a, q))
    p2 = ctx.Process(target=_mp_apply_only, args=(env_file, task_b, q))
    p1.start()
    p2.start()
    p1.join(timeout=40)
    p2.join(timeout=40)

    assert not p1.is_alive() and not p2.is_alive(), "parallel apply workers timed out"
    assert p1.exitcode == 0 and p2.exitcode == 0, f"exitcodes {p1.exitcode}/{p2.exitcode}"

    enters, exits, done = [], [], 0
    drain_deadline = time.time() + 10
    while time.time() < drain_deadline and done < 2:
        try:
            raw = q.get(timeout=0.5)
        except Exception:
            break
        kind = raw[0]
        if kind == "enter":
            enters.append(raw[2])
        elif kind == "exit":
            exits.append(raw[2])
        elif kind == "done":
            done += 1
        elif kind == "error":
            raise AssertionError(f"apply worker failed: {raw[1]}")

    # Overlap holds iff the second apply entered before the first apply exited,
    # i.e. max(enter) < min(exit).  Global serialization would put the second
    # enter after the first exit, breaking this inequality.
    assert max(enters) < min(exits), (
        "applies did not overlap in time — they appear globally serialized "
        "(second enter after first exit)"
    )
