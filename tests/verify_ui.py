from playwright.sync_api import sync_playwright
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto("http://localhost:3000")
    page.wait_for_load_state("networkidle")

    # Click the first backend task if any
    backend_tasks = page.locator(".task-row")
    if backend_tasks.count() > 0:
        backend_tasks.first.click()
        page.wait_for_timeout(1000)

    # Screenshot
    page.screenshot(path=str(BASE_DIR / "tests" / "ui_verify.png"), full_page=True)
    print("Screenshot saved")
    browser.close()
