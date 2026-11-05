"""End-to-end headless browser test suite for FOOTBALL SPA.

Covers Task 2 / EDGE-03:
- Playwright dependency verification in requirements.txt
- Live FastAPI background server fixture on ephemeral port
- Headless browser navigation across World Cup 2026, UCL, and LaLiga
- UI-triggered Monte Carlo simulation execution and DOM reactivity
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
import pytest
import requests

# Graceful skip if playwright is not installed in the current environment
playwright_pkg = pytest.importorskip(
    "playwright",
    reason="playwright not installed. Install with 'pip install playwright pytest-playwright'"
)
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent


def get_free_port() -> int:
    """Acquire a free ephemeral localhost TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server_url():
    """Start FastAPI server fixture on an ephemeral port in a daemon thread."""
    import uvicorn
    from web.server import app

    port = get_free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 12.0
    ready = False
    while time.time() < deadline:
        try:
            r = requests.get(f"{base_url}/health", timeout=1.0)
            if r.status_code == 200:
                ready = True
                break
        except Exception:
            pass
        time.sleep(0.1)

    assert ready, f"Live test server failed to start within 12s on {base_url}"
    yield base_url
    server.should_exit = True
    thread.join(timeout=3.0)


@pytest.fixture(scope="module")
def browser_context():
    """Provide Chromium headless browser context, skipping gracefully if binaries are missing."""
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(
                f"Playwright browser binary not installed or launch failed: {exc}. "
                "Run 'python -m playwright install chromium' to install."
            )
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        yield context
        context.close()
        browser.close()


@pytest.fixture
def page(browser_context):
    """Provide a fresh browser page for each test."""
    pg = browser_context.new_page()
    yield pg
    pg.close()


def test_requirements_contain_playwright_dependencies():
    """Verify requirements.txt declares pinned playwright and pytest-playwright dependencies."""
    req_file = ROOT / "requirements.txt"
    assert req_file.exists(), "requirements.txt must exist"
    req_text = req_file.read_text(encoding="utf-8")
    assert "playwright==1.64.1" in req_text
    assert "pytest-playwright==0.10.0" in req_text


def test_e2e_tournament_navigation(page, live_server_url):
    """SPA loads successfully and user can navigate between World Cup, UCL, and LaLiga."""
    page.goto(live_server_url, wait_until="domcontentloaded")

    # Document title check
    title = page.title()
    assert "FOOTBALL" in title, f"Expected FOOTBALL in document title, got: {title}"

    # Brand mark check
    brand_text = page.locator(".brand-mark-swiss").text_content()
    assert "FOOTBALL" in brand_text

    # 1. World Cup 2026 Navigation
    page.click("#btn-comp-worldcup")
    body_classes = page.locator("body").get_attribute("class") or ""
    assert "theme-worldcup" in body_classes
    assert "WORLD CUP" in (page.locator("#hero-title").text_content() or "").upper()

    # Switch to Standings tab
    page.click("#tab-btn-standings")
    assert "active" in (page.locator("#pane-standings").get_attribute("class") or "")
    standings_html = page.locator("#pane-standings").inner_html()
    assert "GROUP" in standings_html or "table" in standings_html

    # Switch to Bracket tab
    page.click("#tab-btn-bracket")
    assert "active" in (page.locator("#pane-bracket").get_attribute("class") or "")

    # 2. UEFA Champions League Navigation
    page.click("#btn-comp-ucl")
    body_classes = page.locator("body").get_attribute("class") or ""
    assert "theme-ucl" in body_classes
    assert "CHAMPIONS LEAGUE" in (page.locator("#hero-title").text_content() or "").upper()

    page.click("#tab-btn-standings")
    assert "active" in (page.locator("#pane-standings").get_attribute("class") or "")

    # 3. LaLiga EA Sports Navigation
    page.click("#btn-comp-laliga")
    body_classes = page.locator("body").get_attribute("class") or ""
    assert "theme-laliga" in body_classes
    assert "LALIGA" in (page.locator("#hero-title").text_content() or "").upper()


def test_e2e_monte_carlo_simulation_execution(page, live_server_url):
    """User can switch to simulation tab and trigger Monte Carlo multiverse run."""
    page.goto(live_server_url, wait_until="domcontentloaded")

    # Go to World Cup and open Simulation tab
    page.click("#btn-comp-worldcup")
    page.click("#tab-btn-simulation")
    assert "active" in (page.locator("#pane-simulation").get_attribute("class") or "")

    # Locate trigger button
    btn = page.locator("#btn-run-simulation")
    assert btn.is_visible()

    # Click Execute Simulation
    btn.click()

    # Wait for simulation to finish and mode pill to update
    page.wait_for_selector("#masthead-mode-pill.simulated-active", timeout=5000)

    # Verify simulation mode text
    mode_text = page.locator("#mode-text").text_content()
    assert "MODE: SIMULATION" in mode_text

    # Verify progression table is populated with non-empty rows
    rows = page.locator("#sim-progression-body tr")
    assert rows.count() > 0
