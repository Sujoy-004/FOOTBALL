#!/usr/bin/env python3
"""Validate frontend static asset integrity before Cloudflare Pages deployment."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "web" / "static"
ASSETS_IGNORE = STATIC_DIR / ".assetsignore"

SECRET_PATTERNS = [
    re.compile(
        r"(?:api[_-]?key|secret[_-]?key|auth[_-]?token|access[_-]?token|private[_-]?key|password|DATABASE_URL)\s*[:=]\s*['\"][A-Za-z0-9_\-\.]{8,}['\"]",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:FOOTBALL_DATA_ORG_KEY|THE_ODDS_API_KEY|BSD_API_KEY|ADMIN_KEY)\s*[:=]\s*['\"][^'\"]+['\"]",
        re.IGNORECASE,
    ),
    re.compile(r"postgres(?:ql)?://[^:]+:[^@]+@", re.IGNORECASE),
]


def verify_packaging() -> bool:
    errors: list[str] = []

    # 1. Verify .assetsignore presence and required exclusion patterns
    if not ASSETS_IGNORE.exists():
        errors.append("Missing web/static/.assetsignore")
    else:
        ignore_content = ASSETS_IGNORE.read_text(encoding="utf-8")
        if "*.test.mjs" not in ignore_content:
            errors.append(".assetsignore missing *.test.mjs pattern")
        if "*.md" not in ignore_content:
            errors.append(".assetsignore missing *.md pattern")

    # 2. Verify index.html includes config.js
    index_html_path = STATIC_DIR / "index.html"
    if not index_html_path.exists():
        errors.append("Missing web/static/index.html")
    else:
        index_html = index_html_path.read_text(encoding="utf-8")
        if 'src="/config.js"' not in index_html and 'src="config.js"' not in index_html:
            errors.append("index.html missing /config.js script tag")

    # 3. Secret scanning for inadvertent credentials
    for file_path in STATIC_DIR.rglob("*"):
        if file_path.is_file() and file_path.suffix in (".js", ".html", ".css", ".json"):
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            for pattern in SECRET_PATTERNS:
                matches = pattern.findall(text)
                if matches:
                    errors.append(f"Potential secret detected in static asset {file_path.name}: {matches}")

    if errors:
        for err in errors:
            print(f"[ERROR] {err}", file=sys.stderr)
        return False

    print("[OK] Frontend static assets verified clean for Cloudflare Pages.")
    return True


if __name__ == "__main__":
    if not verify_packaging():
        sys.exit(1)
