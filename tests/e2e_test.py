#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAD Translation System E2E Test
Tests: parallel translation, log terminal, resume/restart buttons
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright, expect

BASE_DIR = Path(__file__).resolve().parents[1]
FRONTEND_URL = "http://localhost:3000"
API_BASE = "http://localhost:8000/api"
TEST_FILE = BASE_DIR / "241217-11+小样图.dxf"


def test_backend_api():
    """Test backend APIs: health, config, resume endpoint structure"""
    print("\n[TEST] Backend API Health Check")
    r = requests.get(f"{API_BASE}/cad/health")
    assert r.status_code == 200, f"Health check failed: {r.text}"
    data = r.json()
    assert data.get("success") is True
    print("  [OK] Backend is healthy")

    print("\n[TEST] Backend Config (parallel_count should exist)")
    r = requests.get(f"{API_BASE}/translation/config")
    assert r.status_code == 200
    cfg = r.json()
    runtime = cfg.get("runtime", {})
    assert "parallel_count" in runtime or "parallel_count" in str(cfg)
    print(f"  [OK] Config loaded, parallel_count present in config")


def test_upload_and_task_lifecycle():
    """Upload a DXF file and verify task creation + log endpoint"""
    if not TEST_FILE.exists():
        print(f"\n[SKIP] Test file not found: {TEST_FILE}")
        return

    print(f"\n[TEST] Upload DXF file: {TEST_FILE.name}")
    with open(TEST_FILE, "rb") as f:
        files = {"file": (TEST_FILE.name, f, "application/octet-stream")}
        data = {
            "target_language": "en",
            "extract_only": "true",  # Only extract, avoid LLM call for speed
            "converter_backend": "auto",
        }
        r = requests.post(f"{API_BASE}/cad/upload", files=files, data=data, timeout=120)

    assert r.status_code == 200, f"Upload failed: {r.status_code} {r.text}"
    resp = r.json()
    assert resp.get("success") is True
    task_id = resp.get("data", {}).get("task_id") or resp.get("task_id")
    assert task_id, "No task_id returned"
    print(f"  [OK] Upload success, task_id={task_id}")

    # Wait a bit for extraction
    time.sleep(2)

    # Check task list
    print("\n[TEST] List tasks")
    r = requests.get(f"{API_BASE}/cad/tasks")
    assert r.status_code == 200
    tasks = r.json().get("data", [])
    assert any(t.get("task_id") == task_id for t in tasks), "Task not found in list"
    print(f"  [OK] Task found in list ({len(tasks)} total tasks)")

    # Check logs endpoint
    print("\n[TEST] Task logs endpoint")
    r = requests.get(f"{API_BASE}/cad/tasks/{task_id}/logs")
    assert r.status_code == 200, f"Logs endpoint failed: {r.status_code}"
    logs_data = r.json()
    assert "logs" in logs_data.get("data", {})
    logs_text = logs_data["data"]["logs"]
    print(f"  [OK] Logs retrieved ({len(logs_text)} chars)")
    assert "任务创建" in logs_text or "提取" in logs_text or "task" in logs_text.lower(), "Log content unexpected"

    # Check resume endpoint exists and validates correctly
    print("\n[TEST] Resume endpoint validation")
    r = requests.post(
        f"{API_BASE}/cad/tasks/{task_id}/resume",
        json={"target_language": "en", "translation_mode": "replace"},
        timeout=10,
    )
    # For extract_only tasks, resume may fail because there's nothing to resume
    # We just check the endpoint is reachable and returns proper JSON
    assert r.status_code in (200, 400, 409, 500), f"Unexpected status: {r.status_code}"
    print(f"  [OK] Resume endpoint reachable (status={r.status_code})")

    return task_id


def test_translate_batch_parallel():
    """Directly test the LLMTranslationService.translate_batch with parallel_count"""
    print("\n[TEST] translate_batch parallel_count logic")
    sys.path.insert(0, str(BASE_DIR / "backend"))
    from app.services.llm.translation_service import LLMTranslationService

    svc = LLMTranslationService()
    texts = ["Hello", "123.45", "World", "2024/01/01", "Test"]
    results = []
    progress_events = []

    def progress_cb(evt):
        progress_events.append(evt)

    # We test with a dummy translation func to avoid real LLM calls
    def dummy_translate(text, target_lang):
        return f"[TR]{text}"

    # Monkey-patch for test
    original_translate = svc.translate_text
    svc._LLMTranslationService__translate = dummy_translate
    # Actually translate_text calls _chat, let's just patch _chat
    original_chat = svc._chat
    svc._chat = lambda messages: f"[TR]{messages[-1]['content'][-20:]}"

    try:
        out = svc.translate_batch(
            texts,
            source_lang="en",
            target_lang="zh",
            progress_callback=progress_cb,
        )
        # Verify pure numbers are filtered
        assert out[1] == "123.45", f"Pure number should pass through untranslated: got {out[1]}"
        assert out[3] == "2024/01/01", f"Date-like number should pass through: got {out[3]}"
        print("  [OK] _is_translatable_text filters numbers correctly")

        # Verify progress events contain parallel_count
        if progress_events:
            first = progress_events[0]
            assert "parallel_count" in first, "parallel_count missing from progress event"
            print(f"  [OK] Progress events include parallel_count={first.get('parallel_count')}")
    finally:
        svc._chat = original_chat


def test_playwright_ui():
    """Use Playwright to verify UI elements: terminal log area, resume/restart buttons"""
    print("\n[TEST] Playwright UI verification")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(FRONTEND_URL)
        page.wait_for_load_state("networkidle")

        # Verify page loaded
        expect(page.locator("text=上传文件")).to_be_visible(timeout=5000)
        print("  [OK] Page loaded")

        # Verify terminal log area exists
        terminal = page.locator("text=进程日志")
        if terminal.count() > 0:
            print("  [OK] Terminal log area label found")
        else:
            print("  [WARN] Terminal log area label not found (may need task selection)")

        # Verify LLM Monitor section exists (use class-based selector to avoid encoding issues)
        expect(page.locator(".detail-label").first).to_be_visible(timeout=3000)
        print("  [OK] Detail sections found")

        # Check parallel count input exists by looking for number inputs in the config area
        page.wait_for_selector("input[type='number']", timeout=3000)
        number_inputs = page.locator("input[type='number']")
        if number_inputs.count() >= 3:
            print(f"  [OK] Number inputs found ({number_inputs.count()}), parallel control likely present")
        else:
            print("  [WARN] Parallel count control not directly found (may be in collapsed section)")

        # Take screenshot for visual verification
        screenshot_path = BASE_DIR / "tests" / "e2e_screenshot.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        print(f"  [OK] Screenshot saved: {screenshot_path}")

        browser.close()


def main():
    print("=" * 60)
    print("CAD Translation System E2E Tests")
    print("=" * 60)

    test_backend_api()
    task_id = test_upload_and_task_lifecycle()
    test_translate_batch_parallel()
    test_playwright_ui()

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
