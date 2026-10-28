"""Full knockout dependency chain lands in ONE refresh (02-03, INGEST-02/04).

The World Cup bracket is a dependency graph: R16 slots resolve only from R32
winners, QF from R16 winners, and so on down to the Final.  A pass loop
hard-capped at 3 therefore strands later-round fixtures silently.  These tests
pin the four behaviors of the fixed loop:

1. a complete R16->Final chain (plus TPP) ingests in a single fetch,
2. a no-progress payload stops the loop early and reports payload counts,
3. a score correction propagates to downstream slots within one refresh,
4. ``MAX_KNOCKOUT_PASSES`` bounds the work and strands (never fabricates)
   the slots it cannot reach.

Runs entirely offline: a lite seed copies the committed repo data files and
creates EMPTY runtime stores (``played.json``/``played_groups.json`` are
gitignored artifacts, so ``arch_util.seed_wc_dir`` skips on fresh clones).
"""

from __future__ import annotations

import json
import shutil
import time
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


def seed_empty_wc_dir(dst: Path) -> Path:
    """Copy committed WC data and create EMPTY runtime stores.

    Lighter than ``arch_util.seed_wc_dir`` (which skips when the gitignored
    ``played.json``/``played_groups.json`` are absent) so offline ingestion
    tests run in every environment.
    """
    dst.mkdir(parents=True, exist_ok=True)
    for name in WC_DATA_FILES:
        src = au.WC_REPO / name
        if not src.exists():
            pytest.skip(f"repo data fixture missing (fresh clone?): {src}")
        shutil.copy2(src, dst / name)
    (dst / "played.json").write_text("{}", encoding="utf-8")
    (dst / "played_groups.json").write_text("{}", encoding="utf-8")
    return dst


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def bracket_events(
    wc_dir: Path,
    rounds: tuple[str, ...],
    *,
    seed_r32_winners: bool = False,
) -> list[dict]:
    """Deterministic finished knockout events for the given bracket rounds.

    Walks the bracket in dependency order, resolving each round's slot teams
    exactly the way the pipeline does (``resolve_knockout_slot_teams``), and
    always lets the home side win 2-0 — so later rounds' teams are knowable
    only from earlier winners, which is the dependency under test.

    With ``seed_r32_winners=True`` the R32 winners are written into
    ``played.json`` first.  R16 slots resolve from R32 *winners* (not from
    group data), so this is the synthesized seed a R16->Final payload needs
    against an otherwise empty store.
    """
    from src.knockout import resolve_knockout_slot_teams
    from src.state import load_annex_c

    groups = _load(wc_dir / "groups.json")
    teams = _load(wc_dir / "teams.json")
    bracket = _load(wc_dir / "bracket.json")
    annex_c = load_annex_c(wc_dir)

    played: dict[str, dict] = {}
    if seed_r32_winners:
        r32_slots = resolve_knockout_slot_teams(
            groups, teams, {}, bracket, annex_c, {}, allow_simulation=True
        )
        for entry in bracket:
            if entry["round"] != "R32":
                continue
            slot = r32_slots.get(entry["match_id"])
            if not slot or not slot.get("team_a"):
                continue
            played[entry["match_id"]] = {
                "match_id": entry["match_id"],
                "team_a": slot["team_a"],
                "team_b": slot["team_b"],
                "winner": slot["team_a"],
                "is_draw": False,
                "home_score": 2,
                "away_score": 0,
                "completed_at": "2026-06-30T16:00:00Z",
            }
        (wc_dir / "played.json").write_text(
            json.dumps(played, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    events: list[dict] = []
    settled = set(played)
    for _ in range(8):
        known = {mid: d["winner"] for mid, d in played.items() if d.get("winner")}
        slots = resolve_knockout_slot_teams(
            groups, teams, {}, bracket, annex_c, known, allow_simulation=True
        )
        progressed = False
        for entry in bracket:
            mid, rnd = entry["match_id"], entry["round"]
            if rnd not in rounds or mid in settled:
                continue
            slot = slots.get(mid)
            if not slot or not slot.get("team_a") or not slot.get("team_b"):
                continue
            events.append(
                {
                    "id": mid,
                    "match_id": mid,
                    "status": "finished",
                    "home_team": slot["team_a"],
                    "away_team": slot["team_b"],
                    "home_score": 2,
                    "away_score": 0,
                    "event_date": "2026-07-04T16:00:00Z",
                }
            )
            # Simulate the home win so downstream rounds can resolve.
            played[mid] = {
                "match_id": mid,
                "team_a": slot["team_a"],
                "team_b": slot["team_b"],
                "winner": slot["team_a"],
                "is_draw": False,
                "home_score": 2,
                "away_score": 0,
                "completed_at": "2026-07-04T16:00:00Z",
            }
            settled.add(mid)
            progressed = True
        if not progressed:
            break
    return events


def _run(wc_dir: Path, events: list[dict], monkeypatch, tmp_path) -> dict:
    """One offline ``fetch_live_data`` pass over the given payload."""
    stub = au.StubProvider(events, competition="WC")
    _, get_data_provider = au.recording_provider(stub)
    au.patch_wc_offline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "football_core.runtime_support.get_data_provider", get_data_provider
    )
    from competitions.worldcup.src.pipeline import fetch_live_data

    return fetch_live_data("", "", wc_dir)


def _played(wc_dir: Path) -> dict:
    return _load(wc_dir / "played.json")


@pytest.fixture
def wc_dir(tmp_path: Path) -> Path:
    return seed_empty_wc_dir(tmp_path / "wc")


def test_full_knockout_chain_lands_in_one_refresh(wc_dir, monkeypatch, tmp_path):
    """Behavior 1: R16->Final (+TPP) complete after a SINGLE fetch."""
    events = bracket_events(
        wc_dir, ("R16", "QF", "SF", "TPP", "FINAL"), seed_r32_winners=True
    )
    assert len(events) == 16, "fixture must cover 8 R16 + 4 QF + 2 SF + TPP + F"

    report = _run(wc_dir, events, monkeypatch, tmp_path)

    played = _played(wc_dir)
    missing = [e["id"] for e in events if e["id"] not in played]
    assert missing == [], (
        f"slots stranded by the pass loop (must all land in one refresh): {missing}"
    )
    assert report["success"] is True, report
    ko = report["finished"]["knockout"]
    assert ko["received"] == 16, report["finished"]
    assert ko["ingested"] == 16, report["finished"]


def test_r16_only_payload_stops_early_and_counts_match_payload(
    wc_dir, monkeypatch, tmp_path
):
    """Behavior 2: a payload that cannot progress stops the loop fast."""
    events = bracket_events(wc_dir, ("R16",), seed_r32_winners=True)
    assert len(events) == 8

    started = time.perf_counter()
    report = _run(wc_dir, events, monkeypatch, tmp_path)
    elapsed = time.perf_counter() - started

    assert elapsed < 10.0, f"pass loop ran away: {elapsed:.1f}s"
    ko = report["finished"]["knockout"]
    assert ko["received"] == 8, (
        "receipts must equal the unique payload events, never re-counted "
        f"per pass: {ko}"
    )
    assert ko["ingested"] == 8, ko
    assert report["success"] is True, report


def test_qf_correction_propagates_to_sf_within_one_refresh(
    wc_dir, monkeypatch, tmp_path
):
    """Behavior 3: a corrected already-played QF re-resolves its SF slot."""
    events1 = bracket_events(wc_dir, ("R16", "QF"), seed_r32_winners=True)
    report1 = _run(wc_dir, events1, monkeypatch, tmp_path)
    assert report1["success"] is True, report1

    by_id = {e["id"]: e for e in events1}
    qf1, qf2, qf3, qf4 = by_id["QF_1"], by_id["QF_2"], by_id["QF_3"], by_id["QF_4"]

    # Flip QF_1: the AWAY side now wins, changing the SF_1 pairing.
    corrected = dict(qf1)
    corrected["home_score"], corrected["away_score"] = 0, 2
    events2 = [
        corrected,
        # SF_1 = (new QF_1 winner, QF_3 winner); SF_2 unchanged pairing.
        {
            "id": "SF_1", "match_id": "SF_1", "status": "finished",
            "home_team": qf1["away_team"], "away_team": qf3["home_team"],
            "home_score": 2, "away_score": 1,
            "event_date": "2026-07-09T16:00:00Z",
        },
        {
            "id": "SF_2", "match_id": "SF_2", "status": "finished",
            "home_team": qf2["home_team"], "away_team": qf4["home_team"],
            "home_score": 1, "away_score": 0,
            "event_date": "2026-07-09T20:00:00Z",
        },
    ]

    report2 = _run(wc_dir, events2, monkeypatch, tmp_path)

    played = _played(wc_dir)
    assert (played["QF_1"]["home_score"], played["QF_1"]["away_score"]) == (0, 2)
    assert played["QF_1"]["winner"] == qf1["away_team"], "correction not applied"
    assert played["SF_1"]["team_a"] == qf1["away_team"], (
        "corrected QF_1 winner did not propagate to the SF_1 slot "
        f"in the same refresh: {played.get('SF_1')}"
    )
    assert played["SF_1"]["winner"] == qf1["away_team"]
    assert "SF_2" in played
    assert report2["success"] is True, report2


def test_pass_cap_bounds_work_and_strands_unresolvable_slots(
    wc_dir, monkeypatch, tmp_path
):
    """Behavior 4: the cap stops the loop; absent slots stay absent."""
    from competitions.worldcup.src import pipeline as wc_pipeline

    monkeypatch.setattr(wc_pipeline, "MAX_KNOCKOUT_PASSES", 1, raising=False)

    events = bracket_events(
        wc_dir, ("R16", "QF", "SF", "TPP", "FINAL"), seed_r32_winners=True
    )
    report = _run(wc_dir, events, monkeypatch, tmp_path)

    assert report["success"] is True, report
    played = _played(wc_dir)
    # One pass can only ingest the round resolvable from the seeded R32
    # winners; everything downstream must be STRANDED, never fabricated.
    for mid in ("M89", "M90", "M91", "M92", "M93", "M94", "M95", "M96"):
        assert mid in played, f"R16 fixture missing after pass 1: {mid}"
    assert "QF_1" not in played, "progress was possible but the cap must stop it"
    assert "SF_1" not in played
    assert "FINAL" not in played
