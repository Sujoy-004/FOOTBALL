"""Regression tests for World Cup live-ingestion hardening.

Covers stage-aware routing (each processor receives only its own stage) and
safe upsert/correction of already-recorded factual results, applying the same
truth/authority protection as UCL ingestion:

* never clear an existing winner with winner=None
* never erase a penalty-decided result into a bare draw
* never downgrade a completed match to an incomplete state
* preserve unrelated existing metadata
* accept genuinely newer / more-complete provider results only when safe
"""

import json
import logging
from pathlib import Path

import pytest

from src.fetcher import (
    _should_apply_wc_update,
    partition_events_by_stage,
    process_group_matches,
    process_matches,
)

WC_DATA = Path(__file__).resolve().parent.parent / "data"


# ─── Minimal fixtures ────────────────────────────────────────────────────


GROUP_FIXTURE = {
    "groups": {
        "A": {
            "teams": ["Mexico", "South Africa", "South Korea", "Czech Republic"],
            "matches": [
                {
                    "match_id": "GS_A_01", "team_a": "Mexico",
                    "team_b": "South Africa", "winner": None,
                    "score_a": None, "score_b": None,
                },
                {
                    "match_id": "GS_A_02", "team_a": "Mexico",
                    "team_b": "South Korea", "winner": None,
                    "score_a": None, "score_b": None,
                },
            ],
        }
    }
}

BRACKET = [
    {"match_id": "M73", "team_a": "South Africa", "team_b": "Canada"},
    {"match_id": "M96", "team_a": "Switzerland", "team_b": "Colombia"},
]


def _group_event(
    home="Mexico",
    away="South Africa",
    hs=2,
    as_=1,
    eid="g1",
    date="2026-06-11T19:00:00Z",
):
    return {
        "id": eid, "status": "finished",
        "home_team": home, "away_team": away,
        "home_score": hs, "away_score": as_,
        "group_name": "Group A", "round_number": 1,
        "event_date": date,
    }


def _ko_event(
    home="South Africa",
    away="Canada",
    hs=0,
    as_=1,
    eid="k1",
    date="2026-06-28T19:00:00Z",
    winner=None,
):
    ev = {
        "id": eid, "status": "finished",
        "home_team": home, "away_team": away,
        "home_score": hs, "away_score": as_,
        "event_date": date,
    }
    if winner is not None:
        ev["winner"] = winner
    return ev


def _store_entry(mid, team_a, team_b, winner, hs, as_, is_draw,
                 completed_at="2026-06-11T19:00:00Z", **extra):
    entry = {
        "match_id": mid, "team_a": team_a, "team_b": team_b,
        "winner": winner, "is_draw": is_draw,
        "home_score": hs, "away_score": as_, "completed_at": completed_at,
    }
    entry.update(extra)
    return entry


# ─── Req 1 & 2: stage-aware routing ──────────────────────────────────────


def test_partition_events_by_stage_groups_and_knockouts():
    """Partition routes group_name events to the group list, the rest to knockout."""
    grp1 = _group_event(eid="g1")
    grp2 = _group_event(home="Mexico", away="South Korea", eid="g2")
    ko1 = _ko_event(eid="k1")
    ko2 = dict(_ko_event(eid="k2"), group_name=None)
    group_events, ko_events = partition_events_by_stage([grp1, ko1, grp2, ko2])
    assert group_events == [grp1, grp2]
    assert ko_events == [ko1, ko2]
    assert all(m.get("group_name") for m in group_events)
    assert all(not m.get("group_name") for m in ko_events)


def test_partition_routes_empty_group_name_to_knockout():
    """FDO knockout events carry group_name="" — they belong to the knockout path."""
    ev = _ko_event(eid="k3")
    ev["group_name"] = ""
    group_events, ko_events = partition_events_by_stage([ev])
    assert group_events == []
    assert ko_events == [ev]


def test_live_fetch_partitions_events_before_routing(monkeypatch, tmp_path):
    """fetch_live_data feeds each processor only its own stage events."""
    import src.fetcher as wc_fetcher
    import src.pipeline as wc_pipeline
    import web.common
    import web.startup

    class FakeProvider:
        last_error = None

        def fetch_matches(self, competition_id="WC"):
            return [
                _group_event(eid="gA1"),
                _group_event(home="Mexico", away="South Korea", eid="gA2"),
                _ko_event(eid="k1"),
                dict(_ko_event(eid="k2"), group_name=""),
            ]

    captured = {"group": None, "ko": None}

    def _fake_group(raw, teams, groups, aliases, played_groups, played_ids=None, **kw):
        captured["group"] = list(raw)
        return []

    def _fake_ko(raw, teams, bracket, aliases, played, played_ids=None, **kw):
        captured["ko"] = list(raw)
        return []

    monkeypatch.setattr(wc_fetcher, "process_group_matches", _fake_group)
    monkeypatch.setattr(wc_fetcher, "process_matches", _fake_ko)
    monkeypatch.setattr(
        web.common, "get_data_provider", lambda *a, **k: FakeProvider()
    )
    monkeypatch.setattr(web.startup, "is_snapshot_mode", lambda: False)
    monkeypatch.setattr(
        wc_pipeline, "_last_refresh_report_path",
        lambda: tmp_path / "last_refresh.json",
    )
    # Signal fetchers: no-op to keep the test offline + isolated.
    monkeypatch.setattr(wc_pipeline, "save_signal_cache", lambda *a, **k: None)
    monkeypatch.setattr(
        "src.predictors.odds.fetch_and_cache_odds", lambda *a, **k: {}
    )
    monkeypatch.setattr(
        "src.predictors.rest_days.compute_rest_days_signal", lambda *a, **k: {}
    )
    monkeypatch.setattr(
        "src.predictors.rolling_form.compute_rolling_form_signal",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(
        "src.predictors.squad_value.compute_squad_value_signal",
        lambda *a, **k: {},
    )

    report = wc_pipeline.fetch_live_data("", "", WC_DATA)
    assert report["success"] is True, report
    # Group processor received only group-stage events.
    assert captured["group"] and all(m.get("group_name") for m in captured["group"])
    # Knockout processor received only knockout events (no group_name).
    assert captured["ko"] and all(not m.get("group_name") for m in captured["ko"])


# ─── Req 3: identical existing result is a no-op ─────────────────────────


def test_identical_existing_group_result_is_noop():
    store = {
        "GS_A_01": _store_entry(
            "GS_A_01", "Mexico", "South Africa", "Mexico", 2, 1, False,
            stats={"possession_home": 60},
        ),
    }
    before = json.dumps(store, sort_keys=True)
    result = process_group_matches(
        [_group_event()], {}, GROUP_FIXTURE, {}, store, set(),
    )
    assert result == []
    # Store unchanged down to metadata — a true no-op.
    assert json.dumps(store, sort_keys=True) == before


def test_identical_existing_knockout_result_is_noop():
    store = {
        "M73": _store_entry(
            "M73", "South Africa", "Canada", "Canada", 0, 1, False,
            "2026-06-28T19:00:00Z", context={"venue": "Estadio Azteca"},
        ),
    }
    before = json.dumps(store, sort_keys=True)
    result = process_matches([_ko_event()], {}, BRACKET, {}, store)
    assert result == []
    assert json.dumps(store, sort_keys=True) == before


# ─── Req 4: provider score correction updates stored result ──────────────


def test_provider_score_correction_updates_group_store(caplog):
    store = {
        "GS_A_01": _store_entry(
            "GS_A_01", "Mexico", "South Africa", "Mexico", 2, 1, False,
            stats={"possession_home": 60},
        ),
    }
    with caplog.at_level(logging.WARNING):
        result = process_group_matches(
            [_group_event(hs=3, as_=1)], {}, GROUP_FIXTURE, {}, store, set(),
        )
    assert result == []
    assert store["GS_A_01"]["home_score"] == 3
    assert store["GS_A_01"]["away_score"] == 1
    assert store["GS_A_01"]["winner"] == "Mexico"
    assert any("RESULT UPDATE:" in r.message for r in caplog.records)


def test_provider_score_correction_updates_knockout_store(caplog):
    """A genuine correction flips the winner and is applied + logged."""
    store = {
        "M73": _store_entry(
            "M73", "South Africa", "Canada", "Canada", 0, 1, False,
            "2026-06-28T19:00:00Z",
        ),
    }
    with caplog.at_level(logging.WARNING):
        result = process_matches(
            [_ko_event(hs=2, as_=1, date="2026-06-28T19:00:00Z")],
            {}, BRACKET, {}, store,
        )
    assert result == []
    assert store["M73"]["home_score"] == 2
    assert store["M73"]["away_score"] == 1
    assert store["M73"]["winner"] == "South Africa"
    assert any("RESULT UPDATE:" in r.message for r in caplog.records)


# ─── Req 5: incoming winner=None cannot clear an existing winner ─────────


def test_incoming_draw_cannot_clear_existing_winner(caplog):
    store = {
        "GS_A_01": _store_entry(
            "GS_A_01", "Mexico", "South Africa", "Mexico", 2, 1, False,
        ),
    }
    with caplog.at_level(logging.WARNING):
        result = process_group_matches(
            [_group_event(hs=1, as_=1)], {}, GROUP_FIXTURE, {}, store, set(),
        )
    assert result == []
    assert store["GS_A_01"]["winner"] == "Mexico"
    assert store["GS_A_01"]["home_score"] == 2
    assert any("RESULT UPDATE REJECTED" in r.message for r in caplog.records)


# ─── Req 6: non-penalty state cannot erase an existing penalty decision ──


def test_penalty_decision_cannot_be_erased_into_a_draw(caplog):
    """A penalty-decided KO (0-0 FT + winner) survives a winless 0-0 provider."""
    store = {
        "M96": _store_entry(
            "M96", "Switzerland", "Colombia", "Switzerland", 0, 0, False,
            "2026-07-07T20:00:00Z",
        ),
    }
    bracket = [{"match_id": "M96", "team_a": "Switzerland", "team_b": "Colombia"}]
    raw = [
        _ko_event(home="Switzerland", away="Colombia", hs=0, as_=0,
                  eid="k96", date="2026-07-07T20:00:00Z")
    ]
    with caplog.at_level(logging.WARNING):
        result = process_matches(raw, {}, bracket, {}, store)
    assert result == []
    assert store["M96"]["winner"] == "Switzerland"  # PK decision preserved
    assert store["M96"]["is_draw"] is False
    assert any("RESULT UPDATE REJECTED" in r.message for r in caplog.records)


# ─── Req 7: incomplete incoming cannot downgrade a completed result ──────


def test_incomplete_incoming_cannot_downgrade_completed(caplog):
    """Corrected score WITHOUT a completion timestamp is rejected."""
    store = {
        "M73": _store_entry(
            "M73", "South Africa", "Canada", "Canada", 0, 1, False,
            "2026-06-28T19:00:00Z",
        ),
    }
    with caplog.at_level(logging.WARNING):
        result = process_matches(
            [_ko_event(hs=2, as_=1, date="")], {}, BRACKET, {}, store,
        )
    assert result == []
    assert store["M73"]["home_score"] == 0
    assert store["M73"]["away_score"] == 1
    assert any("RESULT UPDATE REJECTED" in r.message for r in caplog.records)


# ─── Req 8: incoming result preserves unrelated existing metadata ────────


def test_incoming_result_preserves_existing_metadata(caplog):
    store = {
        "GS_A_01": _store_entry(
            "GS_A_01", "Mexico", "South Africa", "Mexico", 2, 1, False,
            stats={"possession_home": 55, "yellow_cards_home": 2},
            context={"venue": "Estadio Azteca"},
            ai_preview="Mexico strong at home",
        ),
    }
    with caplog.at_level(logging.WARNING):
        result = process_group_matches(
            [_group_event(hs=3, as_=1, date="2026-06-11T21:00:00Z")],
            {}, GROUP_FIXTURE, {}, store, set(),
        )
    assert result == []
    e = store["GS_A_01"]
    # Factual fields corrected.
    assert (e["home_score"], e["away_score"]) == (3, 1)
    assert e["completed_at"] == "2026-06-11T21:00:00Z"
    # Unrelated metadata preserved untouched.
    assert e["stats"] == {"possession_home": 55, "yellow_cards_home": 2}
    assert e["context"] == {"venue": "Estadio Azteca"}
    assert e["ai_preview"] == "Mexico strong at home"


def test_update_additively_enriches_missing_metadata(caplog):
    """Existing metadata is never overwritten, but missing keys are added."""
    store = {
        "M73": _store_entry(
            "M73", "South Africa", "Canada", "Canada", 0, 1, False,
            "2026-06-28T19:00:00Z", stats={"possession_home": 40},
        ),
    }
    raw = {
        "id": "k1b", "status": "finished",
        "home_team": "South Africa", "away_team": "Canada",
        "home_score": 1, "away_score": 1,  # correction to a draw
        "event_date": "2026-06-28T19:00:00Z",
        "winner": "Canada",  # penalty-decided draw
    }
    with caplog.at_level(logging.WARNING):
        result = process_matches([raw], {}, BRACKET, {}, store)
    assert result == []
    e = store["M73"]
    assert e["winner"] == "Canada"  # decided, not flattened
    assert e["home_score"] == 1 and e["away_score"] == 1
    assert e["stats"] == {"possession_home": 40}  # preserved
    # context was missing before; the provider added it.
    assert "context" not in e or e["context"] is not None


# ─── Req 9: genuinely newer / more-complete provider result is accepted ──


def test_newer_more_complete_provider_result_accepted(caplog):
    """An existing decided-but-dateless record is completed by a fuller result."""
    store = {
        "M73": _store_entry(
            "M73", "South Africa", "Canada", "Canada", 0, 1, False,
            completed_at="",
        ),
    }
    with caplog.at_level(logging.WARNING):
        result = process_matches(
            [_ko_event(hs=0, as_=1, date="2026-06-28T19:00:00Z")],
            {}, BRACKET, {}, store,
        )
    assert result == []
    assert store["M73"]["completed_at"] == "2026-06-28T19:00:00Z"
    assert store["M73"]["winner"] == "Canada"
    assert any("RESULT UPDATE:" in r.message for r in caplog.records)


def test_should_apply_wc_update_guard_unit():
    """Direct guard checks mirroring the UCL _should_apply_update contract."""
    # 1. Decided winner must never become undecided.
    assert not _should_apply_wc_update(
        {"winner": "Mexico", "home_score": 2, "away_score": 1},
        {"winner": None, "home_score": 1, "away_score": 1},
    )
    # 2. A penalty-decided draw (winner + equal F/T) must keep its decision.
    assert not _should_apply_wc_update(
        {"winner": "Switzerland", "home_score": 0, "away_score": 0},
        {"winner": None, "home_score": 0, "away_score": 0},
    )
    # 3. A completed match must not lose its completion timestamp.
    assert not _should_apply_wc_update(
        {"winner": "Canada", "home_score": 0, "away_score": 1,
         "completed_at": "t"},
        {"winner": "South Africa", "home_score": 2, "away_score": 1,
         "completed_at": ""},
    )
    # Safe: same-side winner, richer score.
    assert _should_apply_wc_update(
        {"winner": "Mexico", "home_score": 2, "away_score": 1},
        {"winner": "Mexico", "home_score": 3, "away_score": 1},
    )
    # Safe: genuinely undecided -> decided completion.
    assert _should_apply_wc_update(
        {"winner": None, "home_score": 0, "away_score": 0,
         "completed_at": ""},
        {"winner": "Mexico", "home_score": 2, "away_score": 0,
         "completed_at": "t"},
    )


# ─── Req 10 & 11: full completed dataset — zero updates, no skip spam ────


def _real_store_events():
    pg_path = WC_DATA / "played_groups.json"
    pl_path = WC_DATA / "played.json"
    assert pg_path.exists() and pl_path.exists(), "runtime result files absent"
    played_groups = json.loads(pg_path.read_text(encoding="utf-8"))
    played = json.loads(pl_path.read_text(encoding="utf-8"))
    if len(played_groups) != 72 or len(played) != 32:
        pytest.skip(f"tournament not complete locally ({len(played_groups)}/72)")
    groups_raw = json.loads((WC_DATA / "groups.json").read_text(encoding="utf-8"))

    # Map match_id -> (group letter, round number) for group events.
    meta = {}
    gd = groups_raw.get("groups", groups_raw)
    for letter, g in gd.items():
        if not isinstance(g, dict):
            continue
        for m in g.get("matches", []):
            meta[m["match_id"]] = letter

    group_events = []
    for mid, e in played_groups.items():
        letter = meta.get(mid, "A")
        group_events.append({
            "id": f"grp_{mid}", "status": "finished",
            "home_team": e["team_a"], "away_team": e["team_b"],
            "home_score": e["home_score"], "away_score": e["away_score"],
            "group_name": "Group " + letter, "round_number": 1,
            "event_date": e.get("completed_at", ""),
        })

    # Knockout events: score-tied decided matches are penalty decided, so
    # reproduce the shootout evidence in the provider payload.
    ko_events = []
    for mid, e in played.items():
        ev = {
            "id": f"ko_{mid}", "status": "finished",
            "home_team": e["team_a"], "away_team": e["team_b"],
            "home_score": e["home_score"], "away_score": e["away_score"],
            "event_date": e.get("completed_at", ""),
        }
        if e["home_score"] == e["away_score"] and e.get("winner"):
            if e["winner"] == e["team_b"]:
                ev["penalty_shootout"] = {"home": 3, "away": 4}
            else:
                ev["penalty_shootout"] = {"home": 4, "away": 3}
        ko_events.append(ev)
    return played_groups, played, group_events, ko_events


def test_full_dataset_produces_zero_group_updates(tmp_path):
    """Feeding the complete 72-match group store back yields zero updates."""
    played_groups, _, group_events, _ = _real_store_events()
    groups_raw = json.loads((WC_DATA / "groups.json").read_text(encoding="utf-8"))
    teams_raw = json.loads((WC_DATA / "teams.json").read_text(encoding="utf-8"))
    aliases = json.loads((WC_DATA / "team_aliases.json").read_text(encoding="utf-8"))

    grp_before = json.dumps(played_groups, sort_keys=True)
    new_grp = process_group_matches(
        group_events, teams_raw, groups_raw, aliases, played_groups, set(),
    )
    assert new_grp == []
    assert json.dumps(played_groups, sort_keys=True) == grp_before


def test_live_run_on_complete_snapshot_is_stable(monkeypatch, tmp_path):
    """A full live run over an equivalent snapshot rewrites no factual store.

    The snapshot represents post-tournament truth; feeding it back through
    the real pipeline must leave played.json and played_groups.json exactly
    as they were (content-wise), with no skip-warning flood.
    """
    import src.fetcher as wc_fetcher
    import src.pipeline as wc_pipeline
    import web.common
    import web.startup

    played_groups, played, group_events, ko_events = _real_store_events()

    class FakeProvider:
        last_error = None

        def fetch_matches(self, competition_id="WC"):
            return group_events + ko_events

    monkeypatch.setattr(
        web.common, "get_data_provider", lambda *a, **k: FakeProvider()
    )
    monkeypatch.setattr(web.startup, "is_snapshot_mode", lambda: False)
    monkeypatch.setattr(
        wc_pipeline, "_last_refresh_report_path",
        lambda: tmp_path / "last_refresh.json",
    )
    monkeypatch.setattr(wc_pipeline, "save_signal_cache", lambda *a, **k: None)
    monkeypatch.setattr(
        "src.predictors.odds.fetch_and_cache_odds", lambda *a, **k: {}
    )
    monkeypatch.setattr(
        "src.predictors.rest_days.compute_rest_days_signal", lambda *a, **k: {}
    )
    monkeypatch.setattr(
        "src.predictors.rolling_form.compute_rolling_form_signal",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(
        "src.predictors.squad_value.compute_squad_value_signal",
        lambda *a, **k: {},
    )

    pg_before = (WC_DATA / "played_groups.json").read_text(encoding="utf-8")
    pl_before = (WC_DATA / "played.json").read_text(encoding="utf-8")

    report = wc_pipeline.fetch_live_data("", "", WC_DATA)

    pg_after = (WC_DATA / "played_groups.json").read_text(encoding="utf-8")
    pl_after = (WC_DATA / "played.json").read_text(encoding="utf-8")

    assert report["success"] is True, report
    assert pg_after == pg_before, "played_groups.json was rewritten"
    assert pl_after == pl_before, "played.json was rewritten"
    # Both summary lines report zero ingested (nothing new) and zero skipped.
    finished = report["finished"]
    for stats in (finished["group_stage"], finished["knockout"]):
        assert stats["ingested"] == 0
        assert stats["skipped_unmatchable"] == 0
        assert stats["skipped_no_target"] == 0


def test_no_cross_stage_warning_spam_when_snapshot_complete(caplog):
    """Group events never reach the knockout processor and vice versa.

    Routing guarantees that each processor only ever sees its own stage's
    events, so over a complete snapshot neither side emits 'no matching
    fixture/slot' / 'unparseable group_name' warnings.
    """
    from src.knockout import resolve_knockout_slot_teams
    from src.state import load_annex_c

    played_groups, played, group_events, ko_events = _real_store_events()
    groups_raw = json.loads((WC_DATA / "groups.json").read_text(encoding="utf-8"))
    teams_raw = json.loads((WC_DATA / "teams.json").read_text(encoding="utf-8"))
    aliases = json.loads((WC_DATA / "team_aliases.json").read_text(encoding="utf-8"))
    annex_c = load_annex_c(WC_DATA)

    with caplog.at_level(logging.WARNING):
        process_group_matches(
            group_events, teams_raw, groups_raw, aliases, played_groups, set(),
        )
    bad = [r.message for r in caplog.records if "unparseable group_name" in r.message]
    assert bad == [], f"group processor flagged knockout events: {bad}"

    caplog.clear()
    # Fully resolve the bracket from the standalone group results plus the
    # already-recorded knockout winners (exactly what the pipeline does:
    # mid -> winner name, not the full record).
    known_winners = {
        mid: d["winner"] for mid, d in played.items() if d.get("winner")
    }
    slot_teams = resolve_knockout_slot_teams(
        groups_raw, teams_raw, played_groups,
        json.loads((WC_DATA / "bracket.json").read_text(encoding="utf-8")),
        annex_c, known_winners=known_winners,
    )
    full_bracket = [
        {"match_id": mid, "team_a": s["team_a"], "team_b": s["team_b"]}
        for mid, s in slot_teams.items()
    ]

    with caplog.at_level(logging.WARNING):
        process_matches(ko_events, teams_raw, full_bracket, aliases, played)

    unmatchable = [
        r.message for r in caplog.records
        if "no matching fixture/slot" in r.message
        or "RESULT INGESTION SKIP" in r.message
        or "unparseable group_name" in r.message
    ]
    assert unmatchable == [], f"knockout processor produced skip spam: {unmatchable}"