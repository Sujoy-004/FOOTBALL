"""Exchange 2: shared match-intelligence kernel (football_core.insight).

The WC and UCL insight implementations now delegate here; these tests pin
the shared behavior, including the union winner rule (level score + explicit
winner = shootout decision) and the exact sentence templates.
"""

from __future__ import annotations

import pytest

from football_core.insight import (
    draw_estimate,
    form_trend,
    head_to_head,
    insight_text,
    ko_signal_probs,
    outcome_distribution,
)


ROWS = [
    {"match_id": "M1", "team_a": "A", "team_b": "B",
     "home_score": 2, "away_score": 1},                       # A beats B
    {"match_id": "M2", "team_a": "C", "team_b": "A",
     "home_score": 0, "away_score": 0},                       # A draws away
    {"match_id": "M3", "team_a": "A", "team_b": "D",
     "home_score": 1, "away_score": 1, "winner": "A"},        # pens decider
    {"match_id": "M4", "team_a": "E", "team_b": "F",
     "home_score": 3, "away_score": 0},                       # unrelated
]


class TestFormTrend:
    def test_filters_and_mirrors_scores(self):
        ft = form_trend(ROWS, "A")
        assert [e["result"] for e in ft] == ["W", "D", "W"]
        assert ft[0]["gf"] == 2 and ft[0]["ga"] == 1
        assert ft[1]["gf"] == 0 and ft[1]["ga"] == 0

    def test_pens_winner_is_not_a_draw(self):
        ft = form_trend(ROWS, "A")
        assert ft[2]["result"] == "W"
        assert ft[2]["result"] not in ("D",)

    def test_level_score_without_winner_is_draw(self):
        assert form_trend(ROWS, "C")[0]["result"] == "D"

    def test_limit_boundary(self):
        assert len(form_trend(ROWS, "A", limit=2)) == 2
        assert form_trend(ROWS, "A", limit=0) == []
        assert len(form_trend(ROWS, "A", limit=99)) == 3

    def test_empty_and_absent_team(self):
        assert form_trend([], "A") == []
        assert form_trend(ROWS, "ZZZ") == []

    def test_opponent_correct_for_away_rows(self):
        assert form_trend(ROWS, "C")[0]["opponent"] == "A"


class TestHeadToHead:
    def test_orientation_and_counts(self):
        rows = ROWS + [{"match_id": "M5", "team_a": "B", "team_b": "A",
                        "home_score": 2, "away_score": 0}]
        h2h = head_to_head(rows, "A", "B")
        assert h2h["a_wins"] == 1 and h2h["b_wins"] == 1 and h2h["total"] == 2
        assert h2h["matches"][0]["score"] == "2-1"   # queried-team orientation
        assert h2h["matches"][1]["score"] == "0-2"

    def test_zero_meetings(self):
        h2h = head_to_head(ROWS, "A", "F")
        assert h2h == {"matches": [], "a_wins": 0, "b_wins": 0,
                       "draws": 0, "total": 0}


class TestOutcomeDistribution:
    def test_band_boundaries(self):
        assert draw_estimate(49.9) == 0.26
        assert draw_estimate(50) == 0.20
        assert draw_estimate(149.9) == 0.20
        assert draw_estimate(150) == 0.14
        assert draw_estimate(299.9) == 0.14
        assert draw_estimate(300) == 0.09

    def test_two_arg_and_three_arg_forms_agree(self):
        assert outcome_distribution(0.62, 1650, 1500) == outcome_distribution(0.62, 150)
        assert outcome_distribution(0.62, 1500, 1650) == outcome_distribution(0.62, 150)

    def test_sums_to_one(self):
        dist = outcome_distribution(0.55, 1600, 1450)
        assert abs(dist["a_win"] + dist["draw"] + dist["b_win"] - 1.0) <= 0.001


class TestKoSignalProbs:
    def test_ratio_blend_with_elo_fallback(self):
        strengths = {"market_odds": {"A": 0.7, "B": 0.3}}
        sigs, elo_prob = ko_signal_probs(
            "A", "B", strengths, {"A": 1700, "B": 1500},
            signals=("market_odds", "rest_days"))
        assert sigs["market_odds"] == pytest.approx(round(0.7 / 1.0, 4))
        assert sigs["rest_days"] == elo_prob  # missing strength -> Elo fallback

    def test_clamping(self):
        sigs, _ = ko_signal_probs(
            "A", "B", {"rolling_form": {"A": 99.0, "B": 0.0001}}, {},
            signals=("rolling_form",))
        assert sigs["rolling_form"] <= 0.99


class TestInsightText:
    EVAL = {
        "refined_elo": {"accuracy": 0.61, "brier": 0.19, "n_matches": 100},
        "market_odds": {"accuracy": 0.52, "brier": 0.27, "n_matches": 90},
        "weak": {"accuracy": 0.9, "brier": 0.01, "n_matches": 3},   # excluded: n<=5
    }

    def test_templates_are_shared_contract(self):
        text = insight_text(
            "Arsenal", "Inter",
            signals={"refined_elo": {"probability": 0.58, "weight": 0.24}},
            form_trends={"Arsenal": [{"result": "W"}, {"result": "D"}],
                         "Inter": []},
            h2h={"a_wins": 2, "draws": 1, "b_wins": 0, "total": 3},
            outcome={"a_win": 0.51, "draw": 0.26, "b_win": 0.23},
            eval_data=self.EVAL,
        )
        assert "led by Refined Elo (P=58%)" in text
        assert "Arsenal form: WD in last 2." in text
        assert "H2H: Arsenal 2-1-0 Inter (3 meetings)." in text
        assert "Predicted: Arsenal 51% / Draw 26% / Inter 23%." in text
        assert "Most reliable: Refined Elo (61% accuracy)." in text
        assert "Warning: Market Odds signal unreliable (Brier 0.27)." in text

    def test_fallback_when_no_data(self):
        assert insight_text("A", "B", {}, {}, {}, {}, {}) == \
            "A vs B: no insight data available."
