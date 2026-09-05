"""Deterministic regressions for the 2026-09-05 LLM engine audit."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from app.services.llm import providers
from app.services.llm.rate_limit import TokenBucket
from app.services.llm.translation_service import LLMTranslationService
from app.services.llm.transport import RequestsTransport


def _candidate(**overrides):
    value = {
        "provider": "custom-a",
        "format": "openai_compatible",
        "base_url": "https://llm.invalid/v1",
        "model": "model-a",
        "api_key": "secret-a",
        "timeout": 1,
        "temperature": 0.0,
        "max_tokens": 10,
        "retry_count": 0,
        "rpm": 0,
        "tpm": "",
        "extra_body": "",
        "use_system_proxy": False,
    }
    value.update(overrides)
    return value


def _runtime(**overrides):
    value = _candidate()
    value.update(
        {
            "system_prompt": "translate",
            "system_prompt_mode": "custom",
            "custom_system_prompt": "translate",
            "glossary_file": "",
            "default_glossary_used": False,
            "batch_size": 2,
            "batch_json": True,
            "parallel_count": 1,
            "allow_demo_fallback": False,
            "fallback_models": [],
        }
    )
    value.update(overrides)
    return value


def test_probe_waits_outside_lock_and_shares_result(monkeypatch):
    service = LLMTranslationService()
    calls = 0
    calls_lock = threading.Lock()

    def probe_network(cfg):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.12)
        return service._probe_result(
            cfg, True, True, 200, cfg["base_url"] + "/models", "ok"
        )

    monkeypatch.setattr(service, "_probe_network", probe_network)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(service._probe_candidate, [_candidate(), _candidate()]))
    elapsed = time.monotonic() - started

    assert elapsed < 0.5
    assert calls == 1
    assert all(item["success"] for item in results)


def test_probe_unexpected_failure_always_notifies_waiter(monkeypatch):
    service = LLMTranslationService()
    entered = threading.Event()
    release = threading.Event()

    def fail(_cfg):
        entered.set()
        release.wait(1)
        raise RuntimeError("broken probe parser")

    monkeypatch.setattr(service, "_probe_network", fail)
    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(service._probe_candidate, _candidate())
        assert entered.wait(1)
        waiter = pool.submit(service._probe_candidate, _candidate())
        release.set()
        with pytest.raises(RuntimeError, match="broken probe parser"):
            owner.result(timeout=1)
        assert waiter.result(timeout=1)["message"] == "provider probe failed"


def test_probe_cache_uses_fingerprint_and_invalidates_changed_credential(monkeypatch):
    service = LLMTranslationService()
    monkeypatch.setattr(
        service,
        "_probe_network",
        lambda cfg: service._probe_result(
            cfg, True, True, 200, cfg["base_url"] + "/models", "ok"
        ),
    )
    service._probe_candidate(_candidate(api_key="first-secret"))
    first_key = next(iter(service._probe_cache))
    assert "first-secret" not in repr(first_key)

    service._probe_candidate(_candidate(api_key="second-secret"))
    assert len(service._probe_cache) == 1
    second_key = next(iter(service._probe_cache))
    assert first_key != second_key
    assert "second-secret" not in repr(second_key)


def test_token_bucket_reserves_distinct_future_slots_with_monotonic_clock():
    now = [100.0]
    bucket = TokenBucket(1, 1, clock=lambda: now[0])
    assert [bucket.acquire(1) for _ in range(4)] == [0.0, 1.0, 2.0, 3.0]
    now[0] += 1.5
    assert bucket.acquire(1) == pytest.approx(2.5)


def test_throttle_wait_is_cancel_aware():
    service = LLMTranslationService()
    service._rate_buckets[("custom-a", "https://llm.invalid/v1", "model-a", "rpm", 1)] = SimpleNamespace(
        acquire=lambda _cost: 30.0
    )
    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        return checks >= 2

    with service.cancellation_check(cancelled), pytest.raises(
        RuntimeError, match="cancelled"
    ):
        service._throttle(_candidate(rpm=1))


def test_retry_backoff_stops_after_cancellation(monkeypatch):
    service = LLMTranslationService()
    cfg = _runtime(retry_count=5)
    attempts = 0

    monkeypatch.setattr(service, "_active_config", lambda: cfg)
    monkeypatch.setattr(service, "_probe_candidate", lambda _cfg: {"success": True})

    def dispatch(_cfg, _messages):
        nonlocal attempts
        attempts += 1
        raise requests.Timeout("retry me")

    monkeypatch.setattr(service, "_dispatch_chat", dispatch)
    with service.cancellation_check(lambda: attempts >= 1), pytest.raises(
        RuntimeError, match="cancelled"
    ):
        service._chat([{"role": "user", "content": "x"}])
    assert attempts == 1


@pytest.mark.parametrize(
    "payload, message",
    [
        ('{"text_0":"A"}', "missing keys: text_1"),
        ('{"text_0":"A","text_1":7}', "values must be strings"),
        ('["A","B"]', "must be a JSON object"),
    ],
)
def test_batch_json_requires_complete_string_map(monkeypatch, payload, message):
    service = LLMTranslationService()
    monkeypatch.setattr(service, "_chat", lambda _messages: payload)
    with pytest.raises(ValueError, match=message):
        service._translate_batch_json(["阀门", "压力"], "zh", "en", "prompt")


def test_parallel_batch_has_bounded_inflight_work_and_stops_submission(monkeypatch):
    service = LLMTranslationService()
    cfg = _runtime(batch_size=1, batch_json=False, parallel_count=2)
    monkeypatch.setattr(service, "_active_config", lambda: cfg)
    monkeypatch.setattr(service, "_compose_system_prompt", lambda *a, **k: "prompt")
    entered = 0
    entered_lock = threading.Lock()
    both_started = threading.Event()
    release = threading.Event()

    def translate(text, *args, **kwargs):
        nonlocal entered
        with entered_lock:
            entered += 1
            if entered == 2:
                both_started.set()
        release.wait(1)
        return text + "-translated"

    monkeypatch.setattr(service, "translate_text", translate)

    def cancelled():
        return both_started.is_set()

    with pytest.raises(RuntimeError, match="cancelled"):
        try:
            service.translate_batch(
                [f"文本{i}" for i in range(10)], should_cancel=cancelled
            )
        finally:
            release.set()
    assert entered == 2


def test_every_http_request_checks_cancellation_before_transport():
    service = LLMTranslationService()
    called = False

    class NoCallTransport:
        def request(self, *args, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("transport should not be reached")

    service._transport = NoCallTransport()
    with service.cancellation_check(lambda: True), pytest.raises(RuntimeError):
        service._request("GET", "https://llm.invalid", _candidate())
    assert called is False


def test_direct_transport_disables_all_environment_proxies():
    transport = RequestsTransport()
    direct, environment = transport._sessions()
    assert direct.trust_env is False
    assert environment.trust_env is True


def test_connection_probe_uses_service_transport(monkeypatch):
    service = LLMTranslationService()
    seen = []

    class FakeTransport:
        def request(self, method, url, **kwargs):
            seen.append((method, url, kwargs["use_system_proxy"]))
            return SimpleNamespace(status_code=200, text="", headers={})

    service._transport = FakeTransport()
    result = service.test_connection(
        {
            "provider": "custom",
            "format": "openai_compatible",
            "base_url": "https://llm.invalid/v1",
            "model": "m",
            "api_key": "key",
            "use_system_proxy": False,
        }
    )
    assert result["success"] is True
    assert seen == [("GET", "https://llm.invalid/v1/models", False)]


def test_custom_provider_unicode_id_atomic_persistence_and_collisions(
    monkeypatch, tmp_path: Path
):
    path = tmp_path / "custom_providers.json"
    monkeypatch.setattr(providers, "_custom_path", lambda: path)
    original_customs = {
        key: value
        for key, value in providers.PROVIDER_PRESETS.items()
        if key not in providers.BUILTIN_PROVIDER_IDS
    }
    try:
        for key in list(original_customs):
            providers.PROVIDER_PRESETS.pop(key, None)
        first = providers.add_custom_provider(
            None, "中文模型服务", "https://one.invalid/v1", "m1", api_format="anthropic"
        )
        assert first["id"].startswith("custom-")
        assert first["id"].isascii()
        assert first["api_format"] == "anthropic"
        with pytest.raises(ValueError, match="already exists"):
            providers.add_custom_provider(
                first["id"], "duplicate", "https://two.invalid/v1", "m2"
            )
        with pytest.raises(ValueError, match="already exists"):
            providers.add_custom_provider(
                "ÓpenAI", "collision", "https://two.invalid/v1", "m2"
            )

        def add(index):
            return providers.add_custom_provider(
                f"parallel-{index}", f"Parallel {index}", f"https://{index}.invalid/v1", "m"
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(add, [1, 2]))
        persisted = json.loads(path.read_text(encoding="utf-8"))
        assert {first["id"], "parallel-1", "parallel-2"} <= set(persisted)
    finally:
        for key in list(providers.PROVIDER_PRESETS):
            if key not in providers.BUILTIN_PROVIDER_IDS:
                providers.PROVIDER_PRESETS.pop(key, None)
        providers.PROVIDER_PRESETS.update(original_customs)


def test_progress_reports_effective_fallback_provider(monkeypatch):
    service = LLMTranslationService()
    fallback = _candidate(
        provider="fallback", base_url="https://fallback.invalid/v1", model="fallback-m"
    )
    cfg = _runtime(fallback_models=[fallback], batch_json=False)
    monkeypatch.setattr(service, "_active_config", lambda: cfg)
    monkeypatch.setattr(
        service,
        "_probe_candidate",
        lambda candidate: {"success": candidate["provider"] == "fallback", "message": "down"},
    )
    monkeypatch.setattr(service, "_dispatch_chat", lambda candidate, _messages: "translated")
    events = []
    assert service.translate_batch(["阀门"], progress_callback=events.append) == [
        "translated"
    ]
    completed = next(item for item in events if item["event"] == "chunk_completed")
    assert completed["provider"] == "fallback"
    assert completed["model"] == "fallback-m"
    assert completed["base_url"] == "https://fallback.invalid/v1"


def test_llm_modules_remain_below_project_line_limit():
    llm_dir = Path(__file__).parents[2] / "backend" / "app" / "services" / "llm"
    oversized = {
        path.name: len(path.read_text(encoding="utf-8").splitlines())
        for path in llm_dir.glob("*.py")
        if len(path.read_text(encoding="utf-8").splitlines()) >= 800
    }
    assert oversized == {}
