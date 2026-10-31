"""Counter integrity + fail/success report-shape parity (02-03, D-14/INGEST-02).

Pins the four counter/report behaviors of the World Cup ingest path:

1. Idempotent receipts — an already-known payload re-offered on a second run
   must not re-ingest (store churn) and must not break the invariant.
2. Single-bucket rule — a received-but-unmatchable event lands in exactly one
   ``skipped_*`` bucket, never also in ``ingested``.
3. Shape parity — the ``_fail`` path and the success path emit the SAME key
   set (top level and ``finished`` sub-dicts), built through one shared
   report helper.
4. Derived success — the success report's verdict is recomputable from its
   own counters; ``_fail`` carries the literal failure verdict (success=False,
   stale=True).

D-14 counter contract exercised here: ``received`` counts PROVIDER-side
finished events (unique per run), ``ingested`` counts STORE-side changes, and
``skipped_no_change`` absorbs re-offers of already-recorded fixtures so
``received == normalized == ingested + skipped_*`` holds on every run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from test_knockout_ingest_chain import (  # shared offline harness
    bracket_events,
    seed_empty_wc_dir,
    _run,
)

#: Every bucket name allowed inside ``finished`` counters (D-14 vocabulary).
COUNTER_KEYS = (
    "received",
    "normalized",
    "ingested",
    "skipped_unmatchable",
    "skipped_no_target",
    "skipped_missing_score",
    "skipped_no_change",
)


def _flat(finished: dict) -> dict:
    """Sum nested per-stage counters into one flat dict (flat input passes through)."""
    if "group_stage" in finished:
        return {
            key: finished["group_stage"].get(key, 0)
            + finished["knockout"].get(key, 0)
            for key in COUNTER_KEYS
        }
    return {key: finished.get(key, 0) for key in COUNTER_KEYS}


def _assert_invariant(finished: dict, label: str) -> None:
    flat = _flat(finished)
    skips = (
        flat["skipped_unmatchable"]
        + flat["skipped_no_target"]
        + flat["skipped_missing_score"]
        + flat["skipped_no_change"]
    )
    assert flat["received"] == flat["normalized"], (
        f"{label}: received != normalized — {flat}"
    )
    assert flat["normalized"] == flat["ingested"] + skips, (
        f"{label}: normalized != ingested + skipped_* — {flat}"
    )


def _group_event(wc_dir: Path) -> dict:
    """One valid group-stage event (GS_A_01: Mexico vs South Africa)."""
    groups = json.loads((wc_dir / "groups.json").read_text(encoding="utf-8"))
    match = groups["groups"]["A"]["matches"][0]
    return {
        "id": "EVT_G1",
        "match_id": "EVT_G1",
        "status": "finished",
        "group_name": "Group A",
        "home_team": match["team_a"],
        "away_team": match["team_b"],
        "home_score": 2,
        "away_score": 1,
        "event_date": "2026-06-15T16:00:00Z",
    }


@pytest.fixture
def wc_dir(tmp_path: Path) -> Path:
    return seed_empty_wc_dir(tmp_path / "wc")


# ── 1. idempotent receipts ─────────────────────────────────────────────────


def test_idempotent_second_run_never_churns_counters_or_store(
    wc_dir, monkeypatch, tmp_path
):
    events = bracket_events(wc_dir, ("R16", "QF"), seed_r32_winners=True)
    events.append(_group_event(wc_dir))
    assert len(events) == 13

    report1 = _run(wc_dir, events, monkeypatch, tmp_path)
    assert report1["success"] is True, report1
    _assert_invariant(report1["finished"], "run1")
    assert _flat(report1["finished"])["ingested"] == 13

    ko_bytes = (wc_dir / "played.json").read_bytes()
    grp_bytes = (wc_dir / "played_groups.json").read_bytes()

    report2 = _run(wc_dir, events, monkeypatch, tmp_path)
    assert report2["success"] is True, report2
    assert report2["stale"] is False
    _assert_invariant(report2["finished"], "run2")

    flat2 = _flat(report2["finished"])
    assert flat2["ingested"] == 0, (
        f"idempotent re-run must re-ingest nothing: {flat2}"
    )
    # D-14: receipts are provider-side — the payload was received again,
    # it just all matched already-known fixtures (skipped_no_change).
    assert flat2["received"] == len(events), flat2

    assert (wc_dir / "played.json").read_bytes() == ko_bytes, "store churned"
    assert (wc_dir / "played_groups.json").read_bytes() == grp_bytes, (
        "group store churned"
    )


# ── 2. single-bucket rule ──────────────────────────────────────────────────


def test_unmatchable_event_lands_in_exactly_one_bucket(
    wc_dir, monkeypatch, tmp_path
):
    good = bracket_events(wc_dir, ("R16",), seed_r32_winners=True)[0]
    bad = {
        "id": "EVT_BAD",
        "match_id": "EVT_BAD",
        "status": "finished",
        "home_team": "FC Nowhere United",
        "away_team": "Atlantis Olympic",
        "home_score": 3,
        "away_score": 1,
        "event_date": "2026-07-01T16:00:00Z",
    }

    report = _run(wc_dir, [good, bad], monkeypatch, tmp_path)

    _assert_invariant(report["finished"], "unmatchable")
    flat = _flat(report["finished"])
    assert flat["received"] == 2, flat
    assert flat["normalized"] == 2, flat
    assert flat["skipped_unmatchable"] == 1, flat
    assert flat["ingested"] == 1, flat
    assert report["success"] is True, report


# ── 3. shape parity between _fail and success ──────────────────────────────


def _shape(report: dict) -> set[str]:
    """Top-level keys plus one level of ``finished`` sub-dict keys."""
    keys = set(report)
    finished = report.get("finished") or {}
    if "group_stage" in finished:
        keys |= {f"finished.{k}" for k in finished["group_stage"]}
        keys |= {f"finished.{k}" for k in finished["knockout"]}
    else:
        keys |= {f"finished.{k}" for k in finished}
    return keys


def test_fail_and_success_reports_share_one_shape(wc_dir, monkeypatch, tmp_path):
    events = bracket_events(wc_dir, ("R16",), seed_r32_winners=True)

    ok = _run(wc_dir, events, monkeypatch, tmp_path)

    boom = au_stub_raises(events)
    monkeypatch.setattr(
        "football_core.runtime_support.get_data_provider", boom
    )
    from competitions.worldcup.src.pipeline import fetch_live_data

    fail = fetch_live_data("", "", wc_dir)

    assert _shape(fail) == _shape(ok), (
        "report shape drifted — symmetric difference: "
        f"{sorted(_shape(fail) ^ _shape(ok))}"
    )
    for key in ("last_success_at", "stages", "written_files", "deferred"):
        assert key in fail, f"_fail path missing {key}"
        assert key in ok, f"success path missing {key}"
    # D-14 vocabulary only; the retired spelling must never reappear.
    blob = json.dumps(fail, default=str) + json.dumps(ok, default=str)
    assert "finished_received" not in blob
    assert "received" in ok["finished"]["group_stage"]
    assert "received" in fail["finished"]["group_stage"]


def au_stub_raises(events: list[dict]):
    """A provider whose fetch raises, driving the ``_fail`` report path."""
    import arch_util as au

    stub = au.StubProvider(events, raises=RuntimeError("provider exploded"),
                           competition="WC")
    _, get_data_provider = au.recording_provider(stub)
    return get_data_provider


# ── 4. success verdict is derived, never literal ───────────────────────────


def test_success_verdict_is_derived_from_counters(wc_dir, monkeypatch, tmp_path):
    from football_core.fetcher import derive_success

    events = bracket_events(wc_dir, ("R16",), seed_r32_winners=True)

    ok = _run(wc_dir, events, monkeypatch, tmp_path)
    assert ok["success"] is True, ok
    assert derive_success(ok["provider"], True, _flat(ok["finished"])) == (
        ok["success"],
        ok["reason"],
    ), "report success must be recomputeable from its own counters"

    # The failure path carries the literal failure verdict...
    boom = au_stub_raises(events)
    monkeypatch.setattr(
        "football_core.runtime_support.get_data_provider", boom
    )
    from competitions.worldcup.src.pipeline import fetch_live_data

    fail = fetch_live_data("", "", wc_dir)
    assert fail["success"] is False
    assert fail["stale"] is True
    # ...and even its zeroed counters derive the same verdict.
    derived = derive_success(fail["provider"], True, _flat(fail["finished"]))
    assert derived[0] is fail["success"]
