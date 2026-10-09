"""OQ9: the World Cup pipeline must PIN ``season=2026`` on its provider fetch.

Without the pin, a provider's current-season default can silently serve the
prior season, so the canonical WC 2026 corpus would be wrong.  This test is
fully offline: a recording provider stub captures the kwargs the pipeline
passes to ``fetch_matches``, and a lite seed copies the committed WC data
files while creating EMPTY runtime stores.

Companion coverage for the provider half of the seam lives in
``tests/test_fdo_provider.py::test_fdo_fetch_matches_builds_season_query``
(asserts ``params["season"]`` reaches the request URL), so it is not
duplicated here.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import arch_util as au

#: Committed data files; the two runtime stores are created EMPTY below.
WC_DATA_FILES = (
    "teams.json",
    "groups.json",
    "bracket.json",
    "team_aliases.json",
    "annex_c.json",
)


def _seed_empty_wc_dir(dst: Path) -> Path:
    """Copy committed WC data and create EMPTY runtime stores (offline-safe)."""
    dst.mkdir(parents=True, exist_ok=True)
    for name in WC_DATA_FILES:
        src = au.WC_REPO / name
        if not src.exists():
            pytest.skip(f"repo data fixture missing (fresh clone?): {src}")
        shutil.copy2(src, dst / name)
    (dst / "played.json").write_text("{}", encoding="utf-8")
    (dst / "played_groups.json").write_text("{}", encoding="utf-8")
    return dst


class _RecordingProvider:
    """Provider stub that records exactly how ``fetch_matches`` was called."""

    last_error = None

    def __init__(self, payload: list | None = None):
        self.payload = list(payload) if payload is not None else []
        self.calls: list[dict] = []

    def fetch_matches(self, *a, **k):
        self.calls.append({"args": a, "kwargs": k})
        return list(self.payload)


def test_fetch_live_data_pins_season_2026(tmp_path, monkeypatch):
    """``fetch_live_data`` must request ``competition_id="WC", season=2026``."""
    import competitions.worldcup.src.pipeline as wc_pipeline
    from football_core import runtime_support

    data_dir = _seed_empty_wc_dir(tmp_path / "wcdata")
    prov = _RecordingProvider([])
    monkeypatch.setattr(
        "football_core.runtime_support.get_data_provider",
        lambda b, f, l=None: prov,
    )
    monkeypatch.setattr(runtime_support, "is_snapshot_mode", lambda: False)
    monkeypatch.setattr(
        wc_pipeline, "_last_refresh_report_path",
        lambda: tmp_path / "last_refresh.json",
    )

    wc_pipeline.fetch_live_data("", "", data_dir)

    assert prov.calls, "provider.fetch_matches was never reached"
    kwargs = prov.calls[0]["kwargs"]
    assert kwargs.get("competition_id") == "WC"
    assert kwargs.get("season") == 2026, (
        f"WC fetch must pin season=2026 (OQ9); got kwargs={kwargs!r}"
    )
