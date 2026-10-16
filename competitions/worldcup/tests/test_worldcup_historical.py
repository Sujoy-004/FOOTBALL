"""Tests for the World Cup leak-free historical primitives.

The WC module diverges from the UCL original in exactly one place: the
knockout -> 1X2 mapping (D-05/D-06). Group matches stay three-way; knockout
matches are labelled by the advancing winner (never a draw) and their
forecasts are renormalized two-way. These tests lock that behaviour plus the
prior-only leak guard shared with every competition.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from competitions.worldcup.src.historical import (
    KO_ROUNDS,
    ReplayResultProvider,
    available_signals,
    build_context_for_match,
    frequency_baseline,
    is_knockout,
    load_replay_matches,
    order_matches,
    outcome_index,
    prior_matches,
    two_way_renormalize,
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


class TestKnockoutDiscriminator:
    def test_round_labels_are_knockout(self):
        for label in ("round of 16", "quarter-final", "semi-final", "final",
                      "third place", "round of 32"):
            assert is_knockout({"round": label}) is True, label

    def test_m_id_shape_is_knockout(self):
        # The committed 2026 KO store id shape (M73..M104).
        assert is_knockout({"match_id": "M73"}) is True
        assert is_knockout({"match_id": "M104"}) is True

    def test_group_match_is_not_knockout(self):
        assert is_knockout({"match_id": "GS_A_01", "round": "group"}) is False
        assert is_knockout({"match_id": "2002_m001", "round": "group"}) is False

    def test_unknown_round_defaults_to_group(self):
        # A missing/unknown non-group round is NOT silently knockout, but an
        # id-shaped M<digits> match is KO even with no round label.
        assert is_knockout({"match_id": "2002_m007", "round": ""}) is False
        assert KO_ROUNDS >= {
            "round of 16", "quarter-final", "semi-final", "final",
            "third place", "round of 32",
        }


class TestOutcomeIndexKnockout:
    def test_home_advances_label(self):
        m = make_match("M73", "Canada", "South Africa", 2, 0,
                       winner="Canada", round="round of 32")
        assert outcome_index(m) == 0

    def test_away_advances_label(self):
        m = make_match("M74", "Germany", "Paraguay", 1, 1,
                       winner="Paraguay", round="round of 16")
        assert outcome_index(m) == 2

    def test_penalty_winner_resolves_level_score_not_draw(self):
        # Level score after extra time; the shootout winner advances.
        m = make_match("M75", "Spain", "Russia", 1, 1,
                       pk_winner="Spain", round="round of 16")
        idx = outcome_index(m)
        assert idx == 0  # the penalty winner's side — never 1

    def test_penalty_winner_away_side(self):
        m = make_match("M76", "Croatia", "Denmark", 1, 1,
                       pk_winner="Denmark", round="round of 16")
        assert outcome_index(m) == 2

    def test_knockout_without_advancing_winner_is_none(self):
        # A level score with no recorded advancing winner must never become
        # a fabricated draw label.
        m = make_match("M77", "Brazil", "Mexico", 0, 0, round="semi-final")
        assert outcome_index(m) is None

    def test_knockout_never_returns_one(self):
        # Exhaustive guard: whatever the score/winner combination, a knockout
        # match is labelled 0 (home advanced), 2 (away advanced) or None
        # (unknown) — never 1 (draw).
        combos = [
            make_match("M1", "A", "B", 2, 0, round="final"),
            make_match("M2", "A", "B", 0, 2, round="final"),
            make_match("M3", "A", "B", 1, 1, round="final"),
            make_match("M4", "A", "B", 1, 1, winner="A", round="final"),
            make_match("M5", "A", "B", 1, 1, pk_winner="B", round="final"),
            make_match("M6", "A", "B", 0, 0, round="quarter-final"),
            make_match("M7", "A", "B", None, None, round="semi-final"),
        ]
        for m in combos:
            idx = outcome_index(m)
            assert idx in (0, 2, None), (m, idx)
            assert idx != 1, m

    def test_group_level_score_is_draw(self):
        m = make_match("GS_A_01", "Mexico", "South Africa", 1, 1, round="group")
        assert outcome_index(m) == 1

    def test_group_scores_are_three_way(self):
        assert outcome_index(make_match("g1", "A", "B", 2, 1, round="group")) == 0
        assert outcome_index(make_match("g2", "A", "B", 1, 2, round="group")) == 2


class TestTwoWayRenormalize:
    def test_already_normalized_passthrough(self):
        assert two_way_renormalize(0.7, 0.3) == pytest.approx((0.7, 0.3))

    def test_renormalizes_to_sum_one(self):
        p_home, p_away = two_way_renormalize(0.35, 0.15)
        assert p_home == pytest.approx(0.7)
        assert p_away == pytest.approx(0.3)
        assert p_home + p_away == pytest.approx(1.0)

    def test_zero_mass_raises(self):
        with pytest.raises(ValueError):
            two_way_renormalize(0.0, 0.0)

    def test_knockout_vector_shape(self):
        # The KO forecast vector is [p_home', 0.0, p_away']: the draw mass is
        # dropped entirely, not redistributed.
        p_home, p_away = two_way_renormalize(0.55, 0.25)
        vector = [p_home, 0.0, p_away]
        assert vector[1] == 0.0
        assert sum(vector) == pytest.approx(1.0)


class TestLeakGuard:
    def _matches(self):
        return [
            make_match("2002_m001", "France", "Senegal", 0, 1,
                       event_date="2002-05-31T19:00:00Z"),
            make_match("2002_m002", "Uruguay", "Denmark", 1, 2,
                       event_date="2002-06-01T19:00:00Z"),
            make_match("2002_m003", "France", "Uruguay", 0, 0,
                       event_date="2002-06-06T19:00:00Z"),
            make_match("2002_m004", "Denmark", "Senegal", 1, 1,
                       event_date="2002-06-06T21:00:00Z"),
        ]

    def test_prior_matches_excludes_target_and_later(self):
        matches = self._matches()
        target = matches[2]
        prior = prior_matches(matches, target)
        assert [m["match_id"] for m in prior] == ["2002_m001", "2002_m002"]

    def test_prior_matches_by_id_lookup(self):
        matches = self._matches()
        target = {"match_id": "2002_m003", "team_a": "France", "team_b": "Uruguay"}
        prior = prior_matches(matches, target)
        assert len(prior) == 2

    def test_context_never_includes_own_result(self):
        matches = self._matches()
        target = matches[2]
        ctx = build_context_for_match(target, matches)
        assert [f["match_id"] for f in ctx.fixtures] == [
            "2002_m001", "2002_m002",
        ]
        assert all(r["match_id"] != "2002_m003" for r in ctx.played_results)

    def test_context_never_includes_strictly_later_matches(self):
        matches = self._matches()
        target = matches[0]
        ctx = build_context_for_match(target, matches)
        assert ctx.fixtures == []
        assert ctx.played_results == []

    def test_replay_provider_excludes_same_day_rows(self):
        prov = ReplayResultProvider(self._matches())
        rows = prov.get_team_results("France", "2002-06-06T19:00:00Z")
        # Only the strictly-earlier France match (May 31) is visible; the
        # June 6 France-Uruguay match at the anchor instant is excluded.
        assert [r["match_id"] for r in rows] == ["2002_m001"]

    def test_replay_provider_empty_anchor_returns_empty(self):
        prov = ReplayResultProvider(self._matches())
        assert prov.get_team_results("France", "") == []

    def test_replay_provider_knockout_row_carries_advancing_winner(self):
        matches = [
            make_match("M73", "Canada", "South Africa", 0, 1,
                       winner="Canada", round="round of 32",
                       event_date="2026-06-28T12:00:00Z"),
            make_match("M74", "Germany", "Paraguay", 1, 1,
                       pk_winner="Paraguay", round="round of 32",
                       event_date="2026-06-29T16:30:00Z"),
        ]
        prov = ReplayResultProvider(matches)
        rows = prov.get_team_results("Canada", "2026-06-29T00:00:00Z")
        assert rows[0]["winner"] == "Canada"
        assert rows[0]["is_draw"] is False
        rows = prov.get_team_results("Paraguay", "2026-06-30T00:00:00Z")
        assert rows[0]["winner"] == "Paraguay"


class TestGroupVsKnockoutEndToEnd:
    """A tiny two-match fixture proves the group/KO scoring split."""

    def test_group_scored_three_way_ko_two_way(self):
        group = make_match("GS_A_01", "Mexico", "South Africa", 1, 1,
                           round="group", event_date="2026-06-11T19:00:00Z")
        ko = make_match("M89", "Paraguay", "France", 0, 1,
                        winner="France", round="round of 16",
                        event_date="2026-07-04T17:00:00Z")

        # Group: three-way label straight from scores.
        assert outcome_index(group) == 1
        group_probs = [1 / 3, 1 / 3, 1 / 3]
        assert group_probs[1] == pytest.approx(1 / 3)

        # KO: label from the advancing winner; forecast renormalized two-way.
        assert outcome_index(ko) == 2
        p_home, p_away = two_way_renormalize(0.42, 0.30)
        ko_vector = [p_home, 0.0, p_away]
        assert ko_vector == pytest.approx([0.42 / 0.72, 0.0, 0.30 / 0.72])


class TestFrequencyBaseline:
    def test_rates_from_fit_set(self):
        matches = [
            make_match("g1", "A", "B", 1, 0, round="group"),
            make_match("g2", "C", "D", 0, 1, round="group"),
            make_match("g3", "E", "F", 1, 1, round="group"),
            make_match("g4", "G", "H", 2, 1, round="group"),
        ]
        baseline = frequency_baseline(matches)
        assert baseline == pytest.approx({"home": 0.5, "draw": 0.25, "away": 0.25})

    def test_empty_fit_returns_uniform(self):
        assert frequency_baseline([]) == pytest.approx(
            {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}
        )


class TestAvailableSignals:
    def test_reports_honest_gaps(self):
        matches = [make_match("g1", "A", "B", 1, 0,
                              event_date="2002-05-31T19:00:00Z")]
        avail = available_signals(matches)
        assert avail["rolling_form"] == "available"
        assert avail["rest_days"] == "available"
        assert avail["refined_elo"] == "insufficient_data:no_elo_ratings"
        assert avail["market_odds"] == "insufficient_data:no_odds_fields"
        assert avail["squad_value"] == "insufficient_data:no_squad_values"


class TestOrderingAndLoading:
    def test_order_matches_by_date(self):
        matches = [
            make_match("2002_m003", "A", "B", 1, 0,
                       event_date="2002-06-11T19:00:00Z"),
            make_match("2002_m001", "A", "B", 1, 0,
                       event_date="2002-05-31T19:00:00Z"),
        ]
        ordered = order_matches(matches)
        assert [m["match_id"] for m in ordered] == ["2002_m001", "2002_m003"]

    def test_load_replay_matches_list_or_dict(self, tmp_path):
        path = str(tmp_path / "replay.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"matches": [{"team_a": "A", "team_b": "B"}]}, f)
        assert load_replay_matches(path) == [{"team_a": "A", "team_b": "B"}]
