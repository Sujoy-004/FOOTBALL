"""UCL startup-ingestion classification regressions."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from competitions.ucl.src.seasons import set_current_season

ROOT = Path(__file__).resolve().parent.parent
UCL_DATA = ROOT / "competitions" / "ucl" / "data"


class _Provider:
    def __init__(self, events):
        self.events = events
        self.last_error = None

    def fetch_matches(self, competition_id="CL", **kwargs):
        return list(self.events)


def _active_runtime(tmp_path: Path) -> Path:
    data_dir = tmp_path / "ucl_data"
    shutil.copytree(UCL_DATA, data_dir)
    set_current_season(data_dir, "2026/27", basis="draw", provider="test")
    return data_dir


def test_scheduled_unmatchable_event_is_fixture_diagnostic_not_result_warning(
    tmp_path, caplog
):
    import logging

    from competitions.ucl.src.pipeline import fetch_live_data

    data_dir = _active_runtime(tmp_path)
    before = json.loads(
        (data_dir / "seasons" / "2026_27" / "results.json").read_text()
    )
    event = {
        "status": "scheduled",
        "season": "2026/27",
        "match_id": "provider-scheduled-unknown",
        "home_team": "Unknown A",
        "away_team": "Unknown B",
        "home_score": None,
        "away_score": None,
        "stage": "LEAGUE_STAGE",
    }

    with caplog.at_level(logging.INFO):
        summary = fetch_live_data(
            data_dir, "", "", provider=_Provider([event])
        )

    messages = [record.message for record in caplog.records]
    assert any("FIXTURE INGESTION IGNORE reason=optional_metadata_unresolved" in m for m in messages)
    assert not any("RESULT INGESTION SKIP" in m for m in messages)
    assert summary["report"]["finished"]["received"] == 0
    after = json.loads(
        (data_dir / "seasons" / "2026_27" / "results.json").read_text()
    )
    assert after == before


def test_finished_event_without_scores_is_classified_and_never_written(tmp_path, caplog):
    import logging

    from competitions.ucl.src.pipeline import fetch_live_data

    data_dir = _active_runtime(tmp_path)
    event = {
        "status": "finished",
        "season": "2026/27",
        "match_id": "provider-no-score",
        "home_team": "Club Brugge",
        "away_team": "Aston Villa",
        "home_score": None,
        "away_score": None,
        "stage": "LEAGUE_STAGE",
    }

    with caplog.at_level(logging.WARNING):
        summary = fetch_live_data(
            data_dir, "", "", provider=_Provider([event])
        )

    report = summary["report"]["finished"]
    assert report["received"] == 1
    assert report["normalized"] == 1
    assert report["skipped_missing_score"] == 1
    assert report["ingested"] == 0
    assert any("reason=missing_score" in r.message for r in caplog.records)
    results = json.loads(
        (data_dir / "seasons" / "2026_27" / "results.json").read_text()
    )
    assert all(
        not (m["match_id"] == "provider-no-score" and m["home_score"] == 0 and m["away_score"] == 0)
        for m in results.get("matches", [])
    )


def test_finished_scored_event_outside_complete_active_catalog_is_no_target(
    tmp_path, caplog
):
    import logging

    from competitions.ucl.src.pipeline import fetch_live_data

    data_dir = _active_runtime(tmp_path)
    event = {
        "status": "finished",
        "season": "2026/27",
        "match_id": "provider-phantom-result",
        "home_team": "Club Brugge",
        "away_team": "Manchester United",
        "home_score": 1,
        "away_score": 0,
        "stage": "LEAGUE_STAGE",
    }

    with caplog.at_level(logging.WARNING):
        summary = fetch_live_data(
            data_dir, "", "", provider=_Provider([event])
        )

    season = summary["per_season"]["2026/27"]
    assert season["skipped_no_target"] == 1
    assert season["results_added"] == 0
    assert any("reason=no_active_season_target" in r.message for r in caplog.records)
    results = json.loads(
        (data_dir / "seasons" / "2026_27" / "results.json").read_text()
    )
    assert all(m.get("match_id") != "provider-phantom-result" for m in results["matches"])


def test_observed_active_provider_spellings_attach_and_preserve_matchday(tmp_path):
    from competitions.ucl.src.pipeline import fetch_live_data

    data_dir = _active_runtime(tmp_path)
    events = [
        {
            "status": "finished", "season": "2026/27", "match_id": "fdo-aek",
            "home_team": "PAE AEK", "away_team": "LASK Linz",
            "home_score": 1, "away_score": 0, "stage": "LEAGUE_STAGE",
            "round_number": 8,
        },
        {
            "status": "finished", "season": "2026/27", "match_id": "fdo-lille",
            "home_team": "Lille OSC", "away_team": "Real Betis Balompié",
            "home_score": 2, "away_score": 3, "stage": "LEAGUE_STAGE",
            "round_number": 2,
        },
    ]

    summary = fetch_live_data(data_dir, "", "", provider=_Provider(events))
    season = summary["per_season"]["2026/27"]
    assert season["results_added"] == 0  # both results already in the base store
    assert season["skipped_no_target"] == 0

    fixtures = json.loads(
        (data_dir / "seasons" / "2026_27" / "fixtures.json").read_text()
    )["fixtures"]
    by_pair = {(f["team_a"], f["team_b"]): f for f in fixtures}
    # Authoritative rule: provider spellings attach, and the existing
    # authoritative official_matchday=1 is preserved over round_number=8/2.
    assert by_pair[("AEK Athens", "LASK")]["official_matchday"] == 1
    assert by_pair[("Lille", "Real Betis")]["official_matchday"] == 1

    results = json.loads(
        (data_dir / "seasons" / "2026_27" / "results.json").read_text()
    )["matches"]
    assert {m["match_id"] for m in results} >= {
        "gen-f4b6285469c3b0e0", "gen-2ce302d883e61826"
    }

    from competitions.ucl.src.state import build_competition_state
    state = build_competition_state(data_dir, active_season="2026/27")
    matchdays = state["stages"]["league"]["matchdays"]
    assert set(matchdays) == {"MD01"}
    assert {m["match_id"] for m in matchdays["MD01"]} >= {
        "gen-f4b6285469c3b0e0", "gen-2ce302d883e61826"
    }


def test_existing_official_matchday_survives_conflicting_round_number(tmp_path, caplog):
    """Regression: official_matchday=1 + provider round_number=8 remains 1.

    The on-disk 2026/27 catalog ships authoritative official_matchday=1 for
    all six completed (real) MD1 fixtures. Re-ingesting live provider events
    whose round_number would re-group those fixtures must NOT overwrite the
    established matchday; a conflict diagnostic is emitted instead.
    """
    import logging

    from competitions.ucl.src.pipeline import fetch_live_data

    data_dir = _active_runtime(tmp_path)

    fixtures = json.loads(
        (data_dir / "seasons" / "2026_27" / "fixtures.json").read_text()
    )["fixtures"]
    by_pair = {(f["team_a"], f["team_b"]): f for f in fixtures}
    assert by_pair[("AEK Athens", "LASK")]["official_matchday"] == 1

    events = [
        {
            "status": "scheduled", "season": "2026/27", "match_id": "fdo-aek",
            "home_team": "PAE AEK", "away_team": "LASK Linz",
            "home_score": None, "away_score": None, "stage": "LEAGUE_STAGE",
            "round_number": 8,
        },
    ]

    with caplog.at_level(logging.WARNING):
        summary = fetch_live_data(data_dir, "", "", provider=_Provider(events))

    season = summary["per_season"]["2026/27"]
    del season  # status/event_date may legitimately update; matchday is the invariant

    fixtures = json.loads(
        (data_dir / "seasons" / "2026_27" / "fixtures.json").read_text()
    )["fixtures"]
    by_pair = {(f["team_a"], f["team_b"]): f for f in fixtures}
    assert by_pair[("AEK Athens", "LASK")]["official_matchday"] == 1
    messages = [r.message for r in caplog.records]
    assert any(
        "FIXTURE MATCHDAY CONFLICT PRESERVED" in m and "existing_official_matchday=1" in m
        for m in messages
    )
