"""End-to-end headless browser test suite for FOOTBALL SPA.

Covers Task 2 / EDGE-03:
- Playwright dependency verification in requirements.txt
- Live FastAPI background server fixture on ephemeral port
- Headless browser navigation across World Cup 2026, UCL, and LaLiga
- UI-triggered Monte Carlo simulation execution and DOM reactivity
"""

from __future__ import annotations

import os
import re
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

SECRET_PATTERNS = [
    re.compile(
        r"(?:api[_-]?key|secret[_-]?key|auth[_-]?token|access[_-]?token|private[_-]?key|password)\s*[:=]\s*['\"][A-Za-z0-9_\-\.]{12,}['\"]",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:FOOTBALL_DATA_ORG_KEY|THE_ODDS_API_KEY|BSD_API_KEY|ADMIN_KEY)\s*[:=]\s*['\"][^'\"]+['\"]",
        re.IGNORECASE,
    ),
    re.compile(r"postgres(?:ql)?://[^:]+:[^@]+@", re.IGNORECASE),
]

# Collect any live environment secret values that should never appear on wire or in DOM
ENV_SECRETS = [
    val for key, val in os.environ.items()
    if any(k in key for k in ("FOOTBALL_DATA_ORG_KEY", "THE_ODDS_API_KEY", "BSD_API_KEY", "ADMIN_KEY", "DATABASE_URL"))
    and len(val.strip()) >= 8
]

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


def test_zero_secret_leakage_on_wire_and_dom(page, live_server_url):
    """Wire sniffer intercepts all responses and live DOM, asserting zero secrets leak."""
    wire_errors: list[str] = []

    def on_response(response):
        content_type = response.headers.get("content-type", "")
        if any(t in content_type for t in ("json", "text", "javascript", "html")):
            try:
                body = response.text()
                for pat in SECRET_PATTERNS:
                    match = pat.search(body)
                    if match:
                        wire_errors.append(
                            f"Secret leak on wire from {response.url}: pattern {pat.pattern} matched '{match.group(0)}'"
                        )
                for sec in ENV_SECRETS:
                    if sec in body:
                        wire_errors.append(
                            f"Live environment secret leaked on wire from {response.url}"
                        )
            except Exception:
                pass

    page.on("response", on_response)

    # 1. Load root SPA and inspect initial load wire responses
    page.goto(live_server_url, wait_until="networkidle")

    # 2. Cycle through all tournaments
    for comp in ("worldcup", "ucl", "laliga"):
        page.click(f"#btn-comp-{comp}")
        for tab in ("overview", "standings", "bracket", "simulation"):
            page.click(f"#tab-btn-{tab}")

    # 3. Trigger simulation and wait for completion
    page.click("#btn-comp-worldcup")
    page.click("#tab-btn-simulation")
    page.click("#btn-run-simulation")
    page.wait_for_selector("#masthead-mode-pill.simulated-active", timeout=5000)

    # 4. Assert zero wire interception leaks
    assert not wire_errors, "Secret leakage detected on wire:\n" + "\n".join(wire_errors)

    # 5. Assert zero secret leaks in live rendered DOM
    dom_content = page.content()
    for pat in SECRET_PATTERNS:
        match = pat.search(dom_content)
        assert not match, f"Secret leak in live DOM: pattern {pat.pattern} matched '{match.group(0)}'"

    for sec in ENV_SECRETS:
        assert sec not in dom_content, "Live environment secret value detected in rendered DOM"


def test_static_assets_zero_secret_tokens():
    """All static assets in web/static/ contain zero credentials or private key tokens."""
    static_dir = ROOT / "web" / "static"
    assert static_dir.exists(), "web/static must exist"

    scanned_files = 0
    for p in static_dir.rglob("*"):
        if p.is_file() and p.suffix in (".js", ".html", ".css", ".json"):
            scanned_files += 1
            text = p.read_text(encoding="utf-8", errors="ignore")
            for pat in SECRET_PATTERNS:
                match = pat.search(text)
                assert not match, (
                    f"Secret pattern {pat.pattern} matched in static asset {p.name}: '{match.group(0)}'"
                )
            for sec in ENV_SECRETS:
                assert sec not in text, f"Environment secret detected in static asset {p.name}"

    assert scanned_files >= 5, f"Expected at least 5 static assets scanned, got {scanned_files}"

