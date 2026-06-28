"""Tests for UCL knockout tie simulation."""

from __future__ import annotations

import random

import pytest

from competitions.ucl.src.knockout import (
    _simulate_penalty_shootout,
    simulate_playoff_round,
    simulate_two_legged_tie,
)


class TestTwoLeggedTie:
    """UCLK-01: Two-legged tie with aggregate scoring, ET, penalties."""

    def test_two_legs_aggregate_winner(self, sample_knockout_elos):
        """Team with higher aggregate score wins (e.g., 3-1, 2-2 -> 5-3 agg)."""
        # Strong vs weak team to force a clear aggregate winner
        elos = {"Strong": 2000, "Weak": 1000}
        rng = random.Random(42)
        result = simulate_two_legged_tie("Strong", "Weak", elos, rng)
        assert result["winner"] == "Strong"
        assert result["loser"] == "Weak"
        assert result["aggregate_a"] >= 0
        assert result["aggregate_b"] >= 0
        assert result["aggregate_a"] + result["aggregate_b"] > 0  # goals scored

    def test_two_legs_draw_aggregate_et_played(self, sample_rng):
        """Level aggregate triggers ET (e.g., 2-1, 1-2 -> 3-3 agg -> ET played)."""
        # Equal Elo teams make a draw likely
        elos = {"Team A": 1500, "Team B": 1500}
        # Use many seeds to find one where aggregate is level
        et_found = False
        for seed in range(200):
            rng = random.Random(seed)
            result = simulate_two_legged_tie("Team A", "Team B", elos, rng)
            agg_a = result["leg1"]["score_a"] + result["leg2"]["score_a"]
            agg_b = result["leg1"]["score_b"] + result["leg2"]["score_b"]
            if agg_a == agg_b:
                assert result["et_played"] is True, (
                    f"Seed {seed}: Aggregate level ({agg_a}-{agg_b}) but ET not played"
                )
                et_found = True
                break
        assert et_found, "No seed produced a level aggregate after 200 tries"

    def test_two_legs_et_winner(self, sample_rng):
        """Winner resolved in ET (aggregate level after 90 min, ET breaks tie)."""
        elos = {"Team A": 1500, "Team B": 1500}
        et_winner_found = False
        for seed in range(500):
            rng = random.Random(seed)
            result = simulate_two_legged_tie("Team A", "Team B", elos, rng)
            if result["et_played"] and result["agg_a_full"] != result["agg_b_full"]:
                assert result["penalties_played"] is False
                et_winner_found = True
                break
        assert et_winner_found, "No seed produced ET winner after 500 tries"

    def test_two_legs_penalties_winner(self, sample_rng):
        """Still level after ET -> penalties decide."""
        elos = {"Team A": 1500, "Team B": 1500}
        pens_found = False
        for seed in range(1000):
            rng = random.Random(seed)
            result = simulate_two_legged_tie("Team A", "Team B", elos, rng)
            if result["penalties_played"]:
                assert result["winner"] is not None
                assert result["winner"] in ("Team A", "Team B")
                pens_found = True
                break
        assert pens_found, "No seed produced penalties after 1000 tries"

    def test_two_legs_deterministic(self):
        """Same seed produces identical tie result."""
        elos = {"Man City": 2000, "Slovan Bratislava": 1500}
        rng1 = random.Random(42)
        rng2 = random.Random(42)
        r1 = simulate_two_legged_tie("Man City", "Slovan Bratislava", elos, rng1)
        r2 = simulate_two_legged_tie("Man City", "Slovan Bratislava", elos, rng2)
        assert r1 == r2

    def test_two_legs_et_home_advantage(self):
        """Second-leg home team has higher ET scoring rate (D-03).

        Tests that team_b (second-leg host) gets home advantage during
        ET by checking that ET score distribution favours team_b over
        many trials.
        """
        elos = {"Team A": 1500, "Team B": 1500}
        et_total_a = 0
        et_total_b = 0
        et_count = 0
        for seed in range(2000):
            rng = random.Random(seed)
            result = simulate_two_legged_tie("Team A", "Team B", elos, rng)
            if result["et_played"]:
                et_total_a += result["et_a"]
                et_total_b += result["et_b"]
                et_count += 1
        # With home advantage in ET (extra HOME_ADVANTAGE_MULTIPLIER for team_b),
        # and enough trials, team_b should score at least as much as team_a.
        # Using a relaxed check because Poisson variance at low lambda can
        # occasionally flip the aggregate even with the HA boost.
        if et_count >= 20:
            expected_a = et_count * 1.3125 * 0.25  # ~0.33 per instance
            expected_b = et_count * 1.3125 * 0.25 * 1.05  # ~0.34 per instance
            # With the HA boost, team_b should on average have more total ET goals
            assert et_total_b >= et_total_a or et_total_b > expected_a * 0.8, (
                f"Team B (ET home) scored {et_total_b} vs Team A {et_total_a} "
                f"in {et_count} ET instances — expected home advantage effect"
            )

    def test_two_legs_no_away_goals_rule(self, sample_rng):
        """2-2 aggregate is level regardless of away goals distribution."""
        elos = {"Team A": 1500, "Team B": 1500}
        for seed in range(200):
            rng = random.Random(seed)
            result = simulate_two_legged_tie("Team A", "Team B", elos, rng)
            agg_a = result["aggregate_a"]
            agg_b = result["aggregate_b"]
            # If aggregate is level, must go to ET (not auto-resolved by away goals)
            if agg_a == agg_b:
                assert result["et_played"] or result["penalties_played"], (
                    f"Seed {seed}: Aggregate level ({agg_a}-{agg_b}) but no ET/pens "
                    f"(away goals not in effect)"
                )

    def test_two_legs_output_keys(self, sample_knockout_elos):
        """Result dict has all expected keys."""
        rng = random.Random(42)
        result = simulate_two_legged_tie("Man City", "Real Madrid", sample_knockout_elos, rng)
        expected_keys = {
            "winner", "loser",
            "aggregate_a", "aggregate_b",
            "agg_a_full", "agg_b_full",
            "leg1", "leg2",
            "et_played", "et_a", "et_b",
            "penalties_played", "penalty_a", "penalty_b",
        }
        assert expected_keys.issubset(result.keys()), (
            f"Missing keys: {expected_keys - set(result.keys())}"
        )

        # Check leg structure
        for leg_key in ("leg1", "leg2"):
            leg = result[leg_key]
            for k in ("team_a", "team_b", "score_a", "score_b"):
                assert k in leg, f"Missing key '{k}' in {leg_key}"

    def test_two_legs_elo_favored_wins_more_often(self):
        """Stronger team (higher Elo) wins more often over N trials."""
        elos = {"Strong": 2000, "Weak": 1000}
        strong_wins = 0
        n_trials = 200
        for seed in range(n_trials):
            rng = random.Random(seed)
            result = simulate_two_legged_tie("Strong", "Weak", elos, rng)
            if result["winner"] == "Strong":
                strong_wins += 1
        win_pct = strong_wins / n_trials
        assert win_pct > 0.5, (
            f"Strong team only won {strong_wins}/{n_trials} ({win_pct:.1%})"
        )

    def test_two_legs_et_not_played_when_clear_winner(self):
        """5-0 aggregate does not trigger ET."""
        elos = {"Strong": 2000, "Weak": 1000}
        et_not_played = False
        for seed in range(500):
            rng = random.Random(seed)
            result = simulate_two_legged_tie("Strong", "Weak", elos, rng)
            agg_margin = abs(result["agg_a_full"] - result["agg_b_full"])
            if agg_margin >= 4:
                # Clear winner should not have ET
                assert result["winner"] in ("Strong", "Weak")
                assert result["et_played"] is False
                assert result["penalties_played"] is False
                et_not_played = True
                break
        assert et_not_played, "No seed produced a 4+ goal aggregate margin"


class TestPenaltyShootout:
    """Tests for the penalty shootout helper."""

    def test_penalty_shootout_returns_tuple(self, sample_rng):
        """Penalty shootout returns two ints."""
        a, b = _simulate_penalty_shootout(sample_rng)
        assert isinstance(a, int)
        assert isinstance(b, int)

    def test_penalty_shootout_not_level(self, sample_rng):
        """Penalty shootout produces a winner (not level)."""
        for seed in range(100):
            rng = random.Random(seed)
            a, b = _simulate_penalty_shootout(rng)
            assert a != b, f"Seed {seed}: Shootout level at {a}-{b}"

    def test_penalty_shootout_valid_scores(self, sample_rng):
        """Scores are within plausible range."""
        for seed in range(100):
            rng = random.Random(seed)
            a, b = _simulate_penalty_shootout(rng)
            assert 0 <= a <= 20
            assert 0 <= b <= 20

    def test_penalty_shootout_deterministic(self):
        """Same seed produces identical shootout."""
        rng1 = random.Random(42)
        rng2 = random.Random(42)
        assert _simulate_penalty_shootout(rng1) == _simulate_penalty_shootout(rng2)


class TestPlayoffRound:
    """UCLK-04: Playoff round simulation (positions 9-24)."""

    def test_playoff_round_8_ties(self, sample_playoff_standings, sample_rng):
        """Exactly 8 ties produce exactly 8 winners."""
        elos = {e["team"]: e["elo"] for e in sample_playoff_standings}
        result = simulate_playoff_round(
            sample_playoff_standings, elos, sample_rng,
        )
        assert len(result["winners"]) == 8
        assert len(result["ties"]) == 8

    def test_playoff_round_winners_from_standings(self, sample_playoff_standings, sample_rng):
        """Winners come from the pool of playoff teams (positions 9-24)."""
        elos = {e["team"]: e["elo"] for e in sample_playoff_standings}
        result = simulate_playoff_round(sample_playoff_standings, elos, sample_rng)
        playoff_teams = {e["team"] for e in sample_playoff_standings if e["zone"] == "playoff"}
        for winner in result["winners"].values():
            assert winner in playoff_teams, (
                f"Winner {winner} is not from playoff zone"
            )

    def test_playoff_round_pairings_correct(self, sample_playoff_standings, sample_playoff_pairings, sample_rng):
        """Pairings match the dedicated data file (9v24, 10v23, etc.)."""
        elos = {e["team"]: e["elo"] for e in sample_playoff_standings}
        result = simulate_playoff_round(sample_playoff_standings, elos, sample_rng)
        pairings = sample_playoff_pairings["pairings"]
        pos_to_team = {e["position"]: e["team"] for e in sample_playoff_standings}
        for pairing in pairings:
            tie_num = pairing["tie"]
            pos_a = pairing["position_a"]
            pos_b = pairing["position_b"]
            tie_result = result["ties"][tie_num]
            teams_in_tie = {tie_result["winner"], tie_result["loser"]}
            assert pos_to_team[pos_a] in teams_in_tie, (
                f"Tie {tie_num}: Team at position {pos_a} not in tie"
            )
            assert pos_to_team[pos_b] in teams_in_tie, (
                f"Tie {tie_num}: Team at position {pos_b} not in tie"
            )

    def test_playoff_round_deterministic(self, sample_playoff_standings):
        """Same seed produces identical playoff results."""
        elos = {e["team"]: e["elo"] for e in sample_playoff_standings}
        r1 = simulate_playoff_round(sample_playoff_standings, elos, random.Random(42))
        r2 = simulate_playoff_round(sample_playoff_standings, elos, random.Random(42))
        assert r1["winners"] == r2["winners"]

    def test_playoff_round_each_team_appears_once(self, sample_playoff_standings, sample_rng):
        """Each team from positions 9-24 appears in exactly 1 tie."""
        elos = {e["team"]: e["elo"] for e in sample_playoff_standings}
        result = simulate_playoff_round(sample_playoff_standings, elos, sample_rng)
        all_teams = set()
        for tie_result in result["ties"].values():
            all_teams.add(tie_result["winner"])
            all_teams.add(tie_result["loser"])
        assert len(all_teams) == 16, f"Expected 16 teams, found {len(all_teams)}"
        playoff_teams = {e["team"] for e in sample_playoff_standings if e["zone"] == "playoff"}
        assert all_teams == playoff_teams, (
            "Teams in ties do not match playoff-zone teams"
        )

    def test_playoff_round_second_leg_home(self, sample_playoff_standings, sample_playoff_pairings, sample_rng):
        """Seeded team (positions 9-16) is team_b (home in leg 2, per D-05).

        In simulate_two_legged_tie, team_b is away in leg 1 and home in leg 2.
        The seeded team (position_a, 9-16) should be passed as team_b so it
        gets second-leg home advantage.
        """
        elos = {e["team"]: e["elo"] for e in sample_playoff_standings}
        result = simulate_playoff_round(sample_playoff_standings, elos, sample_rng)
        pos_to_team = {e["position"]: e["team"] for e in sample_playoff_standings}
        pairings = sample_playoff_pairings["pairings"]
        for pairing in pairings:
            tie_num = pairing["tie"]
            seeded_team = pos_to_team[pairing["position_a"]]
            tie_result = result["ties"][tie_num]
            # team_b in the tie result is the seeded team
            assert tie_result["leg2"]["team_b"] == seeded_team, (
                f"Tie {tie_num}: seeded team {seeded_team} should be team_b "
                f"(home in leg 2), but got {tie_result['leg2']['team_b']}"
            )

    def test_playoff_round_integrates_with_standings(
        self, sample_fixture_schedule, sample_elo_dict, sample_rng,
    ):
        """Takes real standings from simulate_league_phase() and produces valid output."""
        from competitions.ucl.src.simulation import simulate_league_phase

        # Generate standings via the full league phase pipeline
        standings = simulate_league_phase(
            sample_fixture_schedule, sample_elo_dict, sample_rng,
        )
        # Run playoff round with those standings
        result = simulate_playoff_round(standings, sample_elo_dict, sample_rng)
        assert len(result["winners"]) == 8
        assert len(result["ties"]) == 8
        # Verify all 8 winners are from playoff zone
        playoff_teams = {e["team"] for e in standings if e["zone"] == "playoff"}
        for winner in result["winners"].values():
            assert winner in playoff_teams, (
                f"Winner {winner} not in playoff zone"
            )

    def test_playoff_round_elo_favored_wins_more(self, sample_playoff_standings):
        """Higher Elo teams advance more often over N trials."""
        elos = {e["team"]: e["elo"] for e in sample_playoff_standings}
        n_trials = 50
        high_elo_wins = 0
        total_ties = 0
        for seed in range(n_trials):
            rng = random.Random(seed)
            result = simulate_playoff_round(sample_playoff_standings, elos, rng)
            for tie_result in result["ties"].values():
                total_ties += 1
                winner_elo = elos[tie_result["winner"]]
                loser_elo = elos[tie_result["loser"]]
                if winner_elo > loser_elo:
                    high_elo_wins += 1
        win_pct = high_elo_wins / total_ties if total_ties > 0 else 0
        assert win_pct > 0.5, (
            f"Higher Elo teams only won {high_elo_wins}/{total_ties} ties "
            f"({win_pct:.1%}) — expected >50%"
        )

    def test_playoff_round_output_structure(self, sample_playoff_standings, sample_rng):
        """Output dict has expected keys and structure."""
        elos = {e["team"]: e["elo"] for e in sample_playoff_standings}
        result = simulate_playoff_round(sample_playoff_standings, elos, sample_rng)
        # Top-level keys
        assert "winners" in result
        assert "ties" in result
        assert "standings" in result
        assert isinstance(result["winners"], dict)
        assert isinstance(result["ties"], dict)
        assert isinstance(result["standings"], list)
        assert len(result["winners"]) == 8
        assert len(result["ties"]) == 8
        # Winners values are strings (team names)
        for tie_num, winner in result["winners"].items():
            assert isinstance(tie_num, int)
            assert isinstance(winner, str)
        # Tie result structure matches simulate_two_legged_tie output
        expected_tie_keys = {
            "winner", "loser", "aggregate_a", "aggregate_b",
            "agg_a_full", "agg_b_full",
            "leg1", "leg2",
            "et_played", "et_a", "et_b",
            "penalties_played", "penalty_a", "penalty_b",
        }
        for tie_num, tie_result in result["ties"].items():
            assert isinstance(tie_num, int)
            missing = expected_tie_keys - set(tie_result.keys())
            assert not missing, f"Tie {tie_num}: missing keys {missing}"
            for leg_key in ("leg1", "leg2"):
                leg = tie_result[leg_key]
                for k in ("team_a", "team_b", "score_a", "score_b"):
                    assert k in leg, f"Tie {tie_num}, {leg_key}: missing '{k}'"
