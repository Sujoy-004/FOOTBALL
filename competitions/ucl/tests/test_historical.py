"""Tests for the shared leak-free historical primitives."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from competitions.ucl.src.historical import (
    ReplayResultProvider,
    available_signals,
    build_context_for_match,
    chronological_key,
    distinct_keys,
    frequency_baseline,
    gate_verdict,
    load_replay_matches,
    order_matches,
    outcome_index,
    prior_matches,
    result_row,
    split_chronological,
)


def make_match(match_id, team_a, team_b, home_score=None, away_score=None,
               event_date=None, **extra):
    m = {
        "match_id": match_id,
        "team_a": team_a,
        "team_b": team_b,
        "home_score": home_score,
        "away_score": away_score,
    }
    if event_date is not None:
        m["event_date"] = event_date
    m.update(extra)
    return m


class TestOutcome:
    def test_home_away_draw_max(self):
        assert outcome_index({"home_score": 2, "away_score": 1}) == 0
        assert outcome_index({"home_score": 0, "away_score": 3}) == 2
        assert outcome_index({"home_score": 1, "away_score": 1}) == 1

    def test_missing_scores_returns_none(self):
        assert outcome_index({"home_score": None, "away_score": 1}) is None

    def test_result_row_derives_winner(self):
        row = result_row({"team_a": "A", "team_b": "B",
                          "home_score": 2, "away_score": 0})
        assert row["winner"] == "A"
        assert row["is_draw"] is False
        row = result_row({"team_a": "A", "team_b": "B",
                          "home_score": 0, "away_score": 1})
        assert row["winner"] == "B"
        row = result_row({"team_a": "A", "team_b": "B",
                          "home_score": 1, "away_score": 1})
        assert row["winner"] is None
        assert row["is_draw"] is True


class TestChronology:
    def test_chronological_key_priority(self):
        assert chronological_key({"event_date": "2026-10-21"}, 5)[0] == "date"
        assert chronological_key({"match_id": "MD06_15"}, 5)[0] == "matchday"
        assert chronological_key({"match_id": "gen-abc"}, 5)[0] == "position"

    def test_matchday_value_parsed(self):
        key = chronological_key({"match_id": "MD08_01"})
        assert key == ("matchday", 8)

    def test_order_matches_by_matchday(self):
        matches = [
            make_match("MD03_01", "A", "B", 1, 0),
            make_match("MD01_01", "A", "B", 1, 0),
            make_match("MD02_01", "A", "B", 1, 0),
        ]
        ordered = order_matches(matches)
        assert [m["match_id"] for m in ordered] == [
            "MD01_01", "MD02_01", "MD03_01",
        ]

    def test_prior_matches_excludes_future_and_self(self):
        matches = [
            make_match("MD01_01", "A", "B", 1, 0),
            make_match("MD02_01", "C", "D", 0, 1),
            make_match("MD03_01", "E", "F", 2, 2),
        ]
        target = matches[1]
        prior = prior_matches(matches, target)
        assert [m["match_id"] for m in prior] == ["MD01_01"]

    def test_prior_matches_by_id_lookup(self):
        matches = [
            make_match("MD01_01", "A", "B", 1, 0),
            make_match("MD02_01", "C", "D", 0, 1),
        ]
        target = {"match_id": "MD02_01", "team_a": "C", "team_b": "D"}
        assert len(prior_matches(matches, target)) == 1

    def test_distinct_keys_dedupes(self):
        matches = [
            make_match("MD01_01", "A", "B", 1, 0),
            make_match("MD01_02", "C", "D", 0, 1),
            make_match("MD02_01", "E", "F", 1, 1),
        ]
        keys = distinct_keys(matches)
        assert len(keys) == 2


class TestBuildContext:
    def test_context_only_contains_prior_information(self):
        matches = [
            make_match("MD01_01", "A", "B", 1, 0, event_date="2026-10-01"),
            make_match("MD02_01", "C", "D", 0, 1, event_date="2026-10-15"),
            make_match("MD03_01", "A", "C", None, None, event_date="2026-10-22"),
        ]
        target = matches[2]
        ctx = build_context_for_match(
            target, matches, squad_values={"A": 100.0, "B": 50.0},
        )
        # Fixtures contain only the two prior matches
        assert len(ctx.fixtures) == 2
        assert [f["match_id"] for f in ctx.fixtures] == [
            "MD01_01", "MD02_01",
        ]
        # Played results carry only completed prior matches
        assert len(ctx.played_results) == 2
        assert ctx.played_results[0]["winner"] == "A"
        assert ctx.played_results[1]["is_draw"] is False
        # Squad values passed through untouched
        assert ctx.squad_values == {"A": 100.0, "B": 50.0}

    def test_context_never_fabricates_elo(self):
        matches = [make_match("MD02_01", "C", "D", 0, 1)]
        ctx = build_context_for_match(matches[0], matches)
        assert ctx.elo_ratings == {}

    def test_unplayed_target_has_no_self_result(self):
        matches = [
            make_match("MD01_01", "A", "B", 1, 0),
            make_match("MD02_01", "A", "C", None, None),
        ]
        ctx = build_context_for_match(matches[1], matches)
        assert len(ctx.played_results) == 1


class TestSplitChronological:
    def test_matchday_split(self):
        matches = [
            make_match(mid, f"T{i}a", f"T{i}b", 1, 0)
            for i, mid in enumerate(f"MD{n:02d}_01" for n in range(1, 9))
        ]
        fit, oos, meta = split_chronological(matches, oos_matchdays=3)
        assert len(fit) == 5
        assert len(oos) == 3
        assert meta["chronology"] == "matchday"
        assert meta["splittable"] is True
        assert {m["match_id"] for m in oos} == {
            "MD06_01", "MD07_01", "MD08_01",
        }

    def test_matchday_split_too_few_raises(self):
        matches = [
            make_match(mid, f"T{i}a", f"T{i}b", 1, 0)
            for i, mid in enumerate(f"MD{n:02d}_01" for n in range(1, 4))
        ]
        with pytest.raises(ValueError, match="out-of-sample"):
            split_chronological(matches, oos_matchdays=3)

    def test_date_split(self):
        matches = [
            make_match("m1", "A", "B", 1, 0, event_date="2026-10-01"),
            make_match("m2", "C", "D", 0, 1, event_date="2026-10-15"),
            make_match("m3", "E", "F", 1, 1, event_date="2026-10-22"),
            make_match("m4", "G", "H", 2, 0, event_date="2026-10-29"),
        ]
        fit, oos, meta = split_chronological(matches, oos_fraction=0.5)
        assert meta["chronology"] == "date"
        assert [m["match_id"] for m in fit] == ["m1", "m2"]
        assert [m["match_id"] for m in oos] == ["m3", "m4"]

    def test_positional_split_flagged(self):
        matches = [
            make_match(mid, f"T{i}a", f"T{i}b", 1, 0)
            for i, mid in enumerate(["m1", "m2", "m3", "m4"])
        ]
        fit, oos, meta = split_chronological(matches, oos_fraction=0.5)
        assert meta["chronology"] == "position"
        assert len(fit) == 2
        assert len(oos) == 2

    def test_too_few_matches_raises(self):
        with pytest.raises(ValueError, match="need >= 2"):
            split_chronological([make_match("m1", "A", "B", 1, 0)])


class TestFrequencyBaseline:
    def test_rates_from_fit_set(self):
        matches = [
            make_match("m1", "A", "B", 1, 0),
            make_match("m2", "C", "D", 0, 1),
            make_match("m3", "E", "F", 1, 1),
            make_match("m4", "G", "H", 2, 1),
        ]
        baseline = frequency_baseline(matches)
        assert baseline == pytest.approx({"home": 0.5, "draw": 0.25, "away": 0.25})

    def test_empty_fit_returns_uniform(self):
        assert frequency_baseline([]) == pytest.approx({"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3})


class TestAvailableSignals:
    def test_requires_real_inputs(self):
        matches = [make_match("MD01_01", "A", "B", 1, 0)]
        has_avail = available_signals(
            matches, squad_values={"A": 10.0}, elo_ratings={"A": 1500.0}
        )
        assert has_avail["refined_elo"] == "available"
        assert has_avail["squad_value"] == "available"
        assert has_avail["market_odds"].startswith("insufficient_data")
        assert has_avail["rolling_form"].startswith("insufficient_data")
        assert has_avail["rest_days"].startswith("insufficient_data")

    def test_missing_squad_values_reported(self):
        matches = [make_match("MD01_01", "A", "B", 1, 0)]
        has_avail = available_signals(matches)
        assert has_avail["squad_value"].startswith("insufficient_data")

    def test_odds_present_marks_market_available(self):
        matches = [make_match(
            "MD01_01", "A", "B", 1, 0,
            odds_home=1.5, odds_draw=4.0, odds_away=6.0,
        )]
        has_avail = available_signals(matches)
        assert has_avail["market_odds"] == "available"


class TestReplayResultProvider:
    """Leak-free result-history provider.

    Date-anchored strictly-before filtering, team scoping, ordering and
    conservative behavior when no date anchor exists.
    """

    def _matches(self):
        return [
            make_match("MD01_01", "A", "B", 1, 0, event_date="2026-09-10"),
            make_match("MD02_01", "A", "C", 2, 1, event_date="2026-09-17"),
            make_match("MD02_02", "B", "C", 0, 2, event_date="2026-09-18"),
            make_match("MD03_01", "C", "A", 1, 1, event_date="2026-09-24"),
        ]

    def test_returns_strictly_before_filtered_by_team(self):
        prov = ReplayResultProvider(self._matches())
        rows = prov.get_team_results("A", "2026-09-20")
        assert [r["event_date"] for r in rows] == ["2026-09-17", "2026-09-10"]
        assert all(r["team_a"] == "A" or r["team_b"] == "A" for r in rows)

    def test_excludes_same_day(self):
        prov = ReplayResultProvider(self._matches())
        rows = prov.get_team_results("A", "2026-09-17")
        assert [r["event_date"] for r in rows] == ["2026-09-10"]

    def test_empty_before_date_returns_nothing(self):
        prov = ReplayResultProvider(self._matches())
        assert prov.get_team_results("A", "") == []

    def test_limit_respected(self):
        prov = ReplayResultProvider(self._matches())
        rows = prov.get_team_results("A", "2026-09-25", limit=1)
        assert len(rows) == 1
        assert rows[0]["event_date"] == "2026-09-24"

    def test_rows_carry_winner_and_is_draw(self):
        prov = ReplayResultProvider(self._matches())
        rows = prov.get_team_results("C", "2026-09-25")
        assert rows[0]["is_draw"] is True
        assert rows[0]["winner"] is None

    def test_undated_matches_excluded_with_date_anchor(self):
        m = make_match("MD01_01", "A", "B", 1, 0)  # no event_date
        prov = ReplayResultProvider([m])
        assert prov.get_team_results("A", "2026-09-10") == []


class TestLoadReplayMatches:
    def test_loads_list_or_dict(self):
        fd, path = tempfile.mkstemp(suffix=".json", text=True)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"matches": [{"team_a": "A", "team_b": "B"}]}, f)
            matches = load_replay_matches(path)
            assert matches == [{"team_a": "A", "team_b": "B"}]
        finally:
            os.remove(path)

    def test_rejects_unknown_format(self, tmp_path):
        path = str(tmp_path / "bad.json")
        with open(path, "w") as f:
            json.dump({"foo": "bar"}, f)
        with pytest.raises(ValueError, match="Unknown replay data"):
            load_replay_matches(path)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_replay_matches("/nonexistent/replay.json")


class TestGateVerdict:
    def test_pass_when_all_conditions_met(self):
        v = gate_verdict(
            n_oos=60, chronology="date", ensemble_ll=0.90,
            uniform_ll=1.10, freq_ll=1.02, n_real_signals=3,
        )
        assert v["status"] == "PASS"
        assert v["reasons"] == []

    def test_fails_below_min_oos(self):
        v = gate_verdict(
            n_oos=10, chronology="date", ensemble_ll=0.90,
            uniform_ll=1.10, freq_ll=1.02, n_real_signals=3,
        )
        assert v["status"] == "UNVERIFIED"

    def test_fails_on_unsafe_chronology(self):
        v = gate_verdict(
            n_oos=60, chronology="position", ensemble_ll=0.90,
            uniform_ll=1.10, freq_ll=1.02, n_real_signals=3,
        )
        assert v["status"] == "UNVERIFIED"
        assert any("chronology" in r for r in v["reasons"])

    def test_fails_when_not_beating_baselines(self):
        v = gate_verdict(
            n_oos=60, chronology="date", ensemble_ll=1.12,
            uniform_ll=1.10, freq_ll=1.05, n_real_signals=3,
        )
        assert v["status"] == "UNVERIFIED"
        assert any("uniform" in r for r in v["reasons"])
        assert any("frequency" in r for r in v["reasons"])

    def test_fails_when_few_real_signals(self):
        v = gate_verdict(
            n_oos=60, chronology="date", ensemble_ll=0.90,
            uniform_ll=1.10, freq_ll=1.02, n_real_signals=1,
        )
        assert v["status"] == "UNVERIFIED"
        assert any("signal" in r for r in v["reasons"])

    def test_none_baselines_are_ignored_not_fatal(self):
        v = gate_verdict(
            n_oos=60, chronology="matchday", ensemble_ll=0.90,
            uniform_ll=None, freq_ll=None, n_real_signals=2,
        )
        assert v["status"] == "PASS"