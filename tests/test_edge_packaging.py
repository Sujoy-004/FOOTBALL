"""Tests for Cloudflare Pages packaging, asset ignore hygiene, and validation tooling.

Covers Task 2 / EDGE-01:
- wrangler.toml configuration for Cloudflare Pages static edge hosting
- web/static/.assetsignore rules preventing test files and markdown from edge uploads
- scripts/package_frontend.py execution and verification
- Matching logic asserting test suites are ignored while production assets are preserved
"""

from __future__ import annotations

import fnmatch
import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "web" / "static"
WRANGLER_TOML = ROOT / "wrangler.toml"
ASSETS_IGNORE = STATIC_DIR / ".assetsignore"
PACKAGE_SCRIPT = ROOT / "scripts" / "package_frontend.py"


def test_wrangler_toml_configuration():
    """Verify wrangler.toml specifies Cloudflare Pages static output directory."""
    assert WRANGLER_TOML.exists(), "wrangler.toml must exist at repo root"
    content = WRANGLER_TOML.read_text(encoding="utf-8")
    assert 'name = "football-frontend"' in content
    assert 'pages_build_output_dir = "web/static"' in content
    assert "compatibility_date" in content


def test_assetsignore_rules_present():
    """Verify web/static/.assetsignore exists and specifies strict edge exclusions."""
    assert ASSETS_IGNORE.exists(), "web/static/.assetsignore must exist"
    lines = [
        line.strip()
        for line in ASSETS_IGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    
    assert "*.test.mjs" in lines
    assert "*.test.js" in lines
    assert "*.md" in lines
    assert ".git*" in lines
    assert "*.py" in lines
    assert "*.pyc" in lines
    assert "__pycache__" in lines


def test_assetsignore_pattern_matching():
    """Assert fnmatch against .assetsignore patterns matches test files and retains assets."""
    lines = [
        line.strip()
        for line in ASSETS_IGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    def is_ignored(filename: str) -> bool:
        return any(fnmatch.fnmatch(filename, pattern) for pattern in lines)

    # Test and dev artifacts must be ignored
    assert is_ignored("refresh.test.mjs")
    assert is_ignored("api.test.js")
    assert is_ignored("README.md")
    assert is_ignored("test_script.py")
    assert is_ignored("module.pyc")
    assert is_ignored(".gitignore")

    # Production frontend assets must NOT be ignored
    assert not is_ignored("index.html")
    assert not is_ignored("config.js")
    assert not is_ignored("api.js")
    assert not is_ignored("shared.js")
    assert not is_ignored("shared.css")
    assert not is_ignored("wc.js")
    assert not is_ignored("ucl.js")
    assert not is_ignored("laliga.js")
    assert not is_ignored("inter.woff2")
    assert not is_ignored("poster.webp")


def test_package_frontend_script_execution():
    """Execute scripts/package_frontend.py and verify clean verification."""
    assert PACKAGE_SCRIPT.exists(), "scripts/package_frontend.py must exist"
    res = subprocess.run(
        [sys.executable, str(PACKAGE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"package_frontend.py failed:\n{res.stdout}\n{res.stderr}"
    assert "[OK]" in res.stdout


def test_static_js_syntax_integrity():
    """Verify that all production JavaScript files in web/static have valid syntax."""
    js_files = [
        p for p in STATIC_DIR.glob("*.js")
        if not p.name.endswith(".test.js")
    ]
    assert len(js_files) >= 5, f"Expected at least 5 JS files in web/static, found {len(js_files)}"

    for js_path in js_files:
        # Check node syntax using node --check
        res = subprocess.run(
            ["node", "--check", str(js_path)],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"Syntax error in {js_path.name}:\n{res.stderr}"
