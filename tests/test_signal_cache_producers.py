"""World Cup signal-cache producers (plan 02-09, D-08/D-20).

The four producer functions rebuild the caches that ``fetch_live_data`` used
to write before ``worldcup/src/predictors/`` was deleted (plan 01-06). This
module proves, entirely offline:

* local producers write the exact engine-consumable cache shape;
* a fresh cache inside its TTL is not recomputed (with ``count: None``);
* the odds producer degrades truthfully with no provider and never clobbers a
  good cache with an empty result;
* injected BSD-style events map onto canonical fixtures (finished skipped);
* snapshot mode returns four truthful not-attempted rows and writes nothing;
* importing the module performs no credential read or network call.
"""

from __future__ import annotations

import ast
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WC_DATA = ROOT / "competitions" / "worldcup" / "data"

#: Committed fixtures (+ the tracked squad-value file); runtime stores are
#: created EMPTY so these tests run on a clean clone.
_COMMITTED = (
    "teams.json",
    "groups.json",
    "bracket.json",
    "team_aliases.json",
    "annex_c.json",
    "team_values.json",
)

STAGE_ROW_KEYS = {"key", "label", "state", "count", "detail"}
CACHE_KEYS = {"fetched_at", "expires_at", "matches"}


def _seed(tmp_path: Path) -> Path:
    """Throwaway WC data dir: committed fixtures + EMPTY runtime stores."""
    dst = tmp_path / "wc"
    dst.mkdir(parents=True, exist_ok=True)
    for name in _COMMITTED:
        src = WC_DATA / name
        if not src.exists():
            pytest.skip(f"repo data fixture missing (fresh clone?): {src}")
        shutil.copy2(src, dst / name)
    (dst / "played.json").write_text("{}", encoding="utf-8")
    (dst / "played_groups.json").write_text("{}", encoding="utf-8")
    return dst


def _group_match(dst: Path) -> dict:
    groups = json.loads((dst / "groups.json").read_text(encoding="utf-8"))
    data = groups.get("groups", groups)
    return data["A"]["matches"][0]


# ── test 1: local producer shape ─────────────────────────────────────────


def test_local_producers_write_engine_shaped_caches(tmp_path):
    from src import constants
    from src.signal_caches import (
        produce_rest_days_cache,
        produce_rolling_form_cache,
        produce_squad_value_cache,
    )
    from src.state import load_signal_cache

    dst = _seed(tmp_path)
    now = datetime.now(timezone.utc)

    cases = (
        (produce_rolling_form_cache, constants.ROLLING_FORM_CACHE_FILE),
        (produce_squad_value_cache, constants.SQUAD_VALUE_CACHE_FILE),
        (produce_rest_days_cache, constants.REST_DAYS_CACHE_FILE),
    )
    for producer, filename in cases:
        row = producer(dst, now=now)
        assert set(row) == STAGE_ROW_KEYS, row
        assert row["state"] == "ok", row
        assert isinstance(row["count"], int) and row["count"] > 0, row

        cache = load_signal_cache(filename, dst)
        assert set(cache) == CACHE_KEYS, cache
        assert cache["matches"], "producer wrote no match entries"

        expected_ids = {
            m["match_id"]
            for g in json.loads((dst / "groups.json").read_text(encoding="utf-8"))
            .get("groups", {})
            .values()
            for m in g.get("matches", [])
        }
        assert set(cache["matches"]) == expected_ids

        for entry in cache["matches"].values():
            assert isinstance(entry["available"], bool)
            assert "timestamp" in entry
            if entry["available"]:
                assert entry["probability"] is not None
                assert 0.0 < float(entry["probability"]) < 1.0
                assert "draw_probability" in entry
            else:
                assert entry["probability"] is None
                assert entry.get("reason")


def test_squad_value_marks_missing_team_value_unavailable(tmp_path):
    """A team absent from team_values.json abstains with an explicit reason."""
    import json as _json

    from src import constants
    from src.signal_caches import produce_squad_value_cache
    from src.state import load_signal_cache

    dst = _seed(tmp_path)
    values = _json.loads((dst / "team_values.json").read_text(encoding="utf-8"))
    # Emulate a clean clone without the tracked squad-value file.
    (dst / "team_values.json").write_text("{}", encoding="utf-8")

    row = produce_squad_value_cache(dst, now=datetime.now(timezone.utc))
    assert row["state"] == "ok"
    cache = load_signal_cache(constants.SQUAD_VALUE_CACHE_FILE, dst)
    assert cache["matches"]
    assert all(
        entry["available"] is False
        and str(entry.get("reason", "")).startswith("team_value_not_found:")
        for entry in cache["matches"].values()
    ), values


# ── test 2: TTL skip ─────────────────────────────────────────────────────


def test_producer_skips_within_ttl_and_recomputes_when_expired(tmp_path):
    from src import constants
    from src.signal_caches import produce_rolling_form_cache
    from src.state import load_signal_cache, save_signal_cache

    dst = _seed(tmp_path)
    now = datetime.now(timezone.utc)
    filename = constants.ROLLING_FORM_CACHE_FILE

    row1 = produce_rolling_form_cache(dst, now=now)
    assert isinstance(row1["count"], int) and row1["count"] > 0
    first = load_signal_cache(filename, dst)

    # Second run: the cache still expires in the future -> skip.
    row2 = produce_rolling_form_cache(dst, now=now)
    assert row2["state"] == "ok"
    assert row2["count"] is None
    assert "fresh" in row2["detail"].lower()
    assert load_signal_cache(filename, dst)["fetched_at"] == first["fetched_at"]

    # Force expiry: the producer must recompute and advance fetched_at.
    first["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat()
    save_signal_cache(first, filename, dst)

    row3 = produce_rolling_form_cache(dst, now=now + timedelta(hours=2))
    assert isinstance(row3["count"], int) and row3["count"] > 0
    assert load_signal_cache(filename, dst)["fetched_at"] != first["fetched_at"]


# ── test 3: odds, no provider ────────────────────────────────────────────


def test_odds_producer_without_provider_writes_nothing(tmp_path, monkeypatch):
    from src import constants
    from src.signal_caches import produce_odds_cache

    dst = _seed(tmp_path)
    monkeypatch.delenv("ODDS_PROVIDER", raising=False)
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    monkeypatch.delenv("BSD_API_KEY", raising=False)

    odds_path = dst / constants.ODDS_CACHE_FILE
    assert not odds_path.exists()

    row = produce_odds_cache(dst, now=datetime.now(timezone.utc))
    assert row["state"] == "unavailable"
    assert row["count"] is None
    assert "odds provider" in row["detail"].lower()
    assert not odds_path.exists(), "no-provider run must not create an odds cache"


# ── test 4: odds, injected events ────────────────────────────────────────


def test_odds_producer_maps_injected_events_and_skips_finished(tmp_path):
    from src import constants
    from src.signal_caches import produce_odds_cache
    from src.state import load_signal_cache

    dst = _seed(tmp_path)
    match = _group_match(dst)
    scheduled = {
        "id": match["match_id"],
        "status": "scheduled",
        "group_name": "Group A",
        "home_team": match["team_a"],
        "away_team": match["team_b"],
        "odds_home": 1.5,
        "odds_draw": 4.0,
        "odds_away": 6.0,
        "event_date": "2026-06-12T16:00:00Z",
    }
    finished = dict(scheduled, id="finished", status="finished")

    row = produce_odds_cache(
        dst, now=datetime.now(timezone.utc), fetch_fn=lambda: [scheduled, finished]
    )
    assert row["state"] == "ok"
    assert row["count"] == 1

    cache = load_signal_cache(constants.ODDS_CACHE_FILE, dst)
    assert set(cache["matches"]) == {match["match_id"]}
    entry = cache["matches"][match["match_id"]]
    assert entry["available"] is True
    assert 0.0 < float(entry["probability"]) < 1.0
    assert "draw_probability" in entry


# ── test 5: snapshot rows ────────────────────────────────────────────────


def test_produce_signal_caches_snapshot_returns_four_not_attempted_rows(tmp_path):
    from src.signal_caches import produce_signal_caches

    dst = _seed(tmp_path)
    rows = produce_signal_caches(
        dst, now=datetime.now(timezone.utc), mode="snapshot"
    )
    assert [r["key"] for r in rows] == [
        "signals.odds",
        "signals.rolling_form",
        "signals.squad_value",
        "signals.rest_days",
    ]
    for row in rows:
        assert set(row) == STAGE_ROW_KEYS, row
        assert row["state"] == "unavailable"
        assert row["count"] is None
        assert "snapshot" in row["detail"].lower()
    assert list(dst.glob("*_cache.json")) == [], "snapshot mode must not write"


# ── test 6: no import-time credential/network reads ──────────────────────


def _seed_and_run_wc(tmp_path, monkeypatch, *, with_team_values=True):
    """One offline live ``fetch_live_data`` pass over an R16 payload."""
    import arch_util as au
    from test_knockout_ingest_chain import bracket_events, seed_empty_wc_dir

    wc_dir = seed_empty_wc_dir(tmp_path / "wc")
    if with_team_values:
        shutil.copy2(WC_DATA / "team_values.json", wc_dir / "team_values.json")
    events = bracket_events(wc_dir, ("R16",), seed_r32_winners=True)

    stub = au.StubProvider(events, competition="WC")
    _, get_data_provider = au.recording_provider(stub)
    au.patch_wc_offline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "football_core.runtime_support.get_data_provider", get_data_provider
    )
    monkeypatch.delenv("ODDS_PROVIDER", raising=False)
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    monkeypatch.delenv("BSD_API_KEY", raising=False)

    from competitions.worldcup.src.pipeline import fetch_live_data

    return wc_dir, fetch_live_data("", "", wc_dir)


def test_fetch_live_data_appends_signal_rows_on_live_success(tmp_path, monkeypatch):
    """One refresh = one report with a results row PLUS the four signal rows."""
    wc_dir, report = _seed_and_run_wc(tmp_path, monkeypatch)

    assert report["success"] is True, report
    keys = [row["key"] for row in report["stages"]]
    assert keys[0] == "results", keys
    assert keys[1:] == [
        "signals.odds",
        "signals.rolling_form",
        "signals.squad_value",
        "signals.rest_days",
    ], keys

    by_key = {row["key"]: row for row in report["stages"]}
    assert by_key["signals.odds"]["state"] == "unavailable"
    assert by_key["signals.odds"]["count"] is None
    for key in ("signals.rolling_form", "signals.squad_value", "signals.rest_days"):
        assert by_key[key]["state"] == "ok", by_key[key]
        assert isinstance(by_key[key]["count"], int)
        assert by_key[key]["count"] > 0


def test_single_live_fetch_writes_all_local_caches(tmp_path, monkeypatch):
    """A single acquisition pass writes the three local caches and records them."""
    wc_dir, report = _seed_and_run_wc(tmp_path, monkeypatch)
    assert report["success"] is True, report

    for name in (
        "rolling_form_cache.json",
        "squad_value_cache.json",
        "rest_days_cache.json",
    ):
        assert (wc_dir / name).exists(), f"{name} not written"
    # No odds provider is configured in this environment: no odds overwrite.
    assert not (wc_dir / "odds_cache.json").exists()

    written = set(report["written_files"])
    for name in (
        "rolling_form_cache.json",
        "squad_value_cache.json",
        "rest_days_cache.json",
    ):
        assert str(wc_dir / name) in written, (name, report["written_files"])
    assert not any("odds_cache.json" in path for path in written)


def test_fetch_live_data_snapshot_appends_not_attempted_rows(tmp_path, monkeypatch):
    """Snapshot refresh publishes four unavailable rows and writes nothing."""
    from test_knockout_ingest_chain import seed_empty_wc_dir

    wc_dir = seed_empty_wc_dir(tmp_path / "wc")
    import competitions.worldcup.src.pipeline as wc_pipeline

    monkeypatch.setattr(
        "football_core.runtime_support.is_snapshot_mode", lambda: True
    )
    monkeypatch.setattr(
        wc_pipeline, "_last_refresh_report_path", lambda: tmp_path / "freshness.json"
    )

    report = wc_pipeline.fetch_live_data("", "", wc_dir)

    assert report["attempted"] is False
    assert [row["key"] for row in report["stages"]] == [
        "signals.odds",
        "signals.rolling_form",
        "signals.squad_value",
        "signals.rest_days",
    ]
    for row in report["stages"]:
        assert row["state"] == "unavailable", row
        assert row["count"] is None, row
        assert "snapshot" in row["detail"].lower(), row
    assert list(wc_dir.glob("*_cache.json")) == [], "snapshot must not write caches"


def test_signal_caches_has_no_import_time_credential_or_network_reads():
    """Credentials and transport are touched ONLY inside producer calls.

    Asserted structurally: no module-level statement may reach ``os.environ``
    (or a transport primitive). Reads inside function bodies are exactly where
    the call-time contract puts them.
    """
    src_path = ROOT / "competitions" / "worldcup" / "src" / "signal_caches.py"
    tree = ast.parse(src_path.read_text(encoding="utf-8"))

    def _reaches_env(node: ast.AST) -> bool:
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute) and child.attr == "environ":
                return True
            if isinstance(child, ast.Name) and child.id in {"urlopen"}:
                return True
        return False

    offenders: list[int] = []
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if _reaches_env(stmt):
            offenders.append(getattr(stmt, "lineno", -1))
    assert not offenders, (
        f"module-level credential/network access found at lines {offenders}"
    )
