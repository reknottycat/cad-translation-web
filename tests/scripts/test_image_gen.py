from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[2]
    script_path = root / "scripts" / "image_gen.py"
    spec = spec_from_file_location("image_gen", script_path)
    module = module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_sanitize_filename_removes_unsafe_characters():
    image_gen = load_module()
    assert image_gen.sanitize_filename("CAD Workspace: v1?.png") == "cad-workspace-v1.png"


def test_load_jsonl_jobs_reads_expected_jobs(tmp_path):
    image_gen = load_module()
    jobs_path = tmp_path / "jobs.jsonl"
    jobs_path.write_text(
        '{"filename":"overview-dashboard.png","prompt":"one"}\n'
        '{"filename":"cad-workspace.png","prompt":"two"}\n',
        encoding="utf-8",
    )

    jobs = image_gen.load_jsonl_jobs(jobs_path)

    assert len(jobs) == 2
    assert jobs[0]["filename"] == "overview-dashboard.png"
    assert jobs[1]["prompt"] == "two"


def test_generate_job_uses_gpt_image_defaults_without_response_format(tmp_path):
    image_gen = load_module()

    calls = {}

    class FakeImages:
        def generate(self, **kwargs):
            calls.update(kwargs)
            return type(
                "Resp",
                (),
                {"data": [type("Image", (), {"b64_json": "aGVsbG8="})()]},
            )()

    class FakeClient:
        images = FakeImages()

    result = image_gen.generate_job(
        FakeClient(),
        {
            "filename": "Overview Dashboard.png",
            "prompt": "mock prompt",
            "model": "gpt-image-1.5",
            "size": "1536x1024",
            "quality": "medium",
        },
        tmp_path,
    )

    assert "response_format" not in calls
    assert calls["model"] == "gpt-image-1.5"
    assert calls["size"] == "1536x1024"
    assert result["filename"] == "overview-dashboard.png"
