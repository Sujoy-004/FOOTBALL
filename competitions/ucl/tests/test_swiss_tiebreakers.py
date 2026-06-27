"""Tests for Swiss standings with 10-step UCL tiebreaker chain (UCLT-02).

Covers all 10 tiebreaker steps per UEFA Article 18, zone classification,
opponent stat correctness, and H2H absence.
"""

from __future__ import annotations

import pytest

from competitions.ucl.src.groups import compute_swiss_standings


# ── Helpers ──────────────────────────────────────────────────────────────


def _r(mid, ta, tb, sa, sb, yca=0, rca=0, ycb=0, rcb=0):
    """Build a match result dict with minimal boilerplate."""
    return {
        "team_a": ta,
        "team_b": tb,
        "score_a": sa,
        "score_b": sb,
        "winner": ta if sa > sb else (tb if sb > sa else None),
        "yellow_cards_a": yca,
        "red_cards_a": rca,
        "yellow_cards_b": ycb,
        "red_cards_b": rcb,
    }


def _teams_in(matches):
    teams: set[str] = set()
    for r in matches.values():
        teams.add(r["team_a"])
        teams.add(r["team_b"])
    return teams


def _standings(matches, uefa_coeffs=None):
    """Shorthand: compute standings with default coefficients."""
    if uefa_coeffs is None:
        uefa_coeffs = {t: 0.0 for t in _teams_in(matches)}
    return compute_swiss_standings(matches, uefa_coefficients=uefa_coeffs)


# ═══════════════════════════════════════════════════════════════════════════════
# ── Tiebreaker Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestSwissTiebreakers:
    """18 tests covering the full UCL 10-step tiebreaker chain and zones."""

    # ── Test 1: Primary sort by points ──────────────────────────────────

    def test_order_by_points(self):
        """Teams sorted by points descending."""
        matches = {
            "M1": _r("M1", "A", "C", 3, 0),  # A: 3pts
            "M2": _r("M2", "B", "C", 1, 1),  # B: 1pt
        }
        st = _standings(matches)
        assert st[0]["team"] == "A"
        assert st[1]["team"] == "B"
        assert st[0]["pts"] == 3

    # ── Test 2: Step 1 — Goal difference ────────────────────────────────

    def test_tiebreaker_gd_decides(self):
        """Equal points resolved by goal difference (step 1)."""
        # Both 3pts. A: +3 GD, B: +1 GD.
        matches = {
            "M1": _r("M1", "A", "C", 3, 0),
            "M2": _r("M2", "B", "D", 2, 1),
        }
        st = _standings(matches)
        assert st[0]["team"] == "A"
        assert st[1]["team"] == "B"
        assert st[0]["pts"] == st[1]["pts"]
        assert st[0]["gd"] > st[1]["gd"]

    # ── Test 3: Step 2 — Goals scored ───────────────────────────────────

    def test_tiebreaker_gs_decides(self):
        """Equal GD resolved by goals scored (step 2)."""
        # Both 3pts, +2 GD. A: 2 GS, B: 3 GS.
        matches = {
            "M1": _r("M1", "A", "C", 2, 0),
            "M2": _r("M2", "B", "D", 3, 1),
        }
        st = _standings(matches)
        assert st[0]["team"] == "B"
        assert st[1]["team"] == "A"
        assert st[0]["pts"] == st[1]["pts"]
        assert st[0]["gd"] == st[1]["gd"]
        assert st[0]["gs"] > st[1]["gs"]

    # ── Test 4: Step 3 — Away goals scored ──────────────────────────────

    def test_tiebreaker_away_gs_decides(self):
        """Equal GS resolved by away goals scored (step 3)."""
        # Both 4pts (W+D), +2 GD, 2 GS.
        # A's GS came at home (team_a), B's GS came away (team_b).
        matches = {
            "M1": _r("M1", "A", "C", 2, 0),  # A home: +2 GD, 2 GS, 0 away_gs
            "M2": _r("M2", "A", "D", 0, 0),  # A home: draw
            "M3": _r("M3", "E", "B", 0, 2),  # B away: +2 GD, 2 GS, 2 away_gs
            "M4": _r("M4", "F", "B", 0, 0),  # B away: draw
        }
        st = _standings(matches)
        assert st[0]["team"] == "B", "B has 2 away_gs, should rank higher"
        assert st[1]["team"] == "A"
        assert st[0]["pts"] == st[1]["pts"]
        assert st[0]["gd"] == st[1]["gd"]
        assert st[0]["gs"] == st[1]["gs"]
        assert st[0]["away_gs"] > st[1]["away_gs"]

    # ── Test 5: Step 4 — Wins (field correctness) ───────────────────────

    def test_tiebreaker_wins_field(self):
        """Wins field is correctly computed from match results."""
        matches = {
            "M1": _r("M1", "A", "B", 2, 0),  # A wins
            "M2": _r("M2", "A", "C", 1, 0),  # A wins
            "M3": _r("M3", "B", "C", 0, 0),  # draw
            "M4": _r("M4", "B", "D", 3, 1),  # B wins
        }
        st = _standings(matches)
        a_stats = next(s for s in st if s["team"] == "A")
        b_stats = next(s for s in st if s["team"] == "B")
        assert a_stats["wins"] == 2, "A won 2 matches"
        assert b_stats["wins"] == 1, "B won 1 match"

    # ── Test 6: Step 5 — Away wins (field correctness) ──────────────────

    def test_tiebreaker_away_wins_field(self):
        """Away wins field is correctly computed."""
        matches = {
            # B is away, wins
            "M1": _r("M1", "C", "B", 0, 1),
            # A is home, wins
            "M2": _r("M2", "A", "D", 2, 0),
            # A is away, draws
            "M3": _r("M3", "E", "A", 1, 1),
        }
        st = _standings(matches)
        a_stats = next(s for s in st if s["team"] == "A")
        b_stats = next(s for s in st if s["team"] == "B")
        assert a_stats["away_wins"] == 0
        assert b_stats["away_wins"] == 1

    # ── Test 7: Step 6 — Opponent points ────────────────────────────────

    def test_tiebreaker_opponent_pts_field(self):
        """Opponent points field computed from pre-tiebreak raw aggregates."""
        # A beats C (C gets 0pts). B beats D (D gets 0pts).
        # opp_pts for A = C's points = 0. opp_pts for B = D's points = 0.
        # Make it more interesting: C also beats E, so C has 3pts.
        matches = {
            "M1": _r("M1", "A", "C", 2, 0),  # A:3pts, C:0pts
            "M2": _r("M2", "B", "D", 1, 0),  # B:3pts, D:0pts
            "M3": _r("M3", "C", "E", 1, 0),  # C:3pts, E:0pts
        }
        st = _standings(matches)
        a_stats = next(s for s in st if s["team"] == "A")
        b_stats = next(s for s in st if s["team"] == "B")
        # A's opponent C has 3pts. B's opponent D has 0pts.
        assert a_stats["opp_pts"] == 3
        assert b_stats["opp_pts"] == 0

    # ── Test 8: Step 7 — Opponent GD ────────────────────────────────────

    def test_tiebreaker_opponent_gd_field(self):
        """Opponent GD field computed from pre-tiebreak raw aggregates."""
        matches = {
            "M1": _r("M1", "A", "C", 2, 0),  # A:3pts, C:0pts,-2GD
            "M2": _r("M2", "B", "D", 3, 0),  # B:3pts, D:0pts,-3GD
            "M3": _r("M3", "C", "E", 1, 0),  # C:3pts,+1GD
        }
        st = _standings(matches)
        a_stats = next(s for s in st if s["team"] == "A")
        b_stats = next(s for s in st if s["team"] == "B")
        # A's opponent C: total GD = (-2) + (+1) = -1.
        # B's opponent D: total GD = -3.
        assert a_stats["opp_gd"] == -1
        assert b_stats["opp_gd"] == -3

    # ── Test 9: Step 8 — Opponent GS ────────────────────────────────────

    def test_tiebreaker_opponent_gs_field(self):
        """Opponent GS field computed from pre-tiebreak raw aggregates."""
        matches = {
            "M1": _r("M1", "A", "C", 0, 2),  # A:0pts,-2GD, C:3pts,+2GD,2GS
            "M2": _r("M2", "C", "D", 3, 0),  # C:3pts,+3GD,3GS
            "M3": _r("M3", "B", "E", 1, 0),  # B:3pts,+1GD, E:0pts,-1GD
        }
        st = _standings(matches)
        a_stats = next(s for s in st if s["team"] == "A")
        b_stats = next(s for s in st if s["team"] == "B")
        # A's opponent C: GS = 2 + 3 = 5.
        # B's opponent E: GS = 0.
        assert a_stats["opp_gs"] == 5
        assert b_stats["opp_gs"] == 0

    # ── Test 10: Step 9 — Conduct score ─────────────────────────────────

    def test_tiebreaker_conduct_score_decides(self):
        """Equal opp_GS resolved by disciplinary (step 9, lower is better)."""
        # A and B identical stats except conduct_score:
        # A: 1 YC, 0 RC = 1 conduct point
        # B: 2 YC, 0 RC = 2 conduct points
        matches = {
            "M1": _r("M1", "A", "C", 2, 0, yca=1),  # A: 1YC
            "M2": _r("M2", "B", "D", 2, 0, yca=2),  # B: 2YC
        }
        uefa = {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0}
        st = compute_swiss_standings(matches, uefa_coefficients=uefa)
        assert st[0]["team"] == "A", "A has fewer conduct points (1 < 2)"
        assert st[1]["team"] == "B"
        assert st[0]["conduct_score"] == 1
        assert st[1]["conduct_score"] == 2

    # ── Test 11: Step 10 — UEFA coefficient ─────────────────────────────

    def test_tiebreaker_uefa_coefficient_decides(self):
        """Equal conduct resolved by UEFA coefficient (step 10)."""
        matches = {
            "M1": _r("M1", "A", "C", 1, 0),
            "M2": _r("M2", "B", "D", 1, 0),
        }
        uefa = {"A": 100.0, "B": 50.0, "C": 0.0, "D": 0.0}
        st = compute_swiss_standings(matches, uefa_coefficients=uefa)
        assert st[0]["team"] == "A", "A has higher coefficient (100 > 50)"
        assert st[1]["team"] == "B"
        assert st[0]["uefa_coefficient"] == 100.0

    # ── Test 12: All 10 steps exhausted (stable sort) ───────────────────

    def test_tiebreaker_all_10_steps_exhausted(self):
        """All 10 steps equal — order preserved (stable sort)."""
        # A and B identical in every metric. Input order is A then B.
        matches = {
            "M1": _r("M1", "A", "C", 1, 0),
            "M2": _r("M2", "B", "C", 1, 0),
        }
        uefa = {"A": 0.0, "B": 0.0, "C": 0.0}
        st = compute_swiss_standings(matches, uefa_coefficients=uefa)
        # With identical stats, Python's sort is stable → input order preserved
        assert st[0]["team"] == "A"
        assert st[1]["team"] == "B"

    # ── Test 13: No H2H ─────────────────────────────────────────────────

    def test_no_h2h_used(self):
        """Verify _compute_h2h and _tiebreak_group NOT used."""
        import inspect
        from competitions.ucl.src import groups as groups_mod

        src = inspect.getsource(groups_mod)
        assert "_compute_h2h" not in src, "H2H must not be in groups.py"
        assert "_tiebreak_group" not in src, "_tiebreak_group must not be in groups.py"

    # ═══════════════════════════════════════════════════════════════════════════
    # ── Zone Classification Tests
    # ═══════════════════════════════════════════════════════════════════════════

    def test_qualification_zones_top8(
        self, sample_standings_results,
    ):
        """Positions 1-8 get zone='top_8'."""
        for entry in sample_standings_results[:8]:
            assert entry["zone"] == "top_8", f"{entry['team']} (pos {entry['position']}) should be top_8"

    def test_qualification_zones_playoff(
        self, sample_standings_results,
    ):
        """Positions 9-24 get zone='playoff'."""
        for entry in sample_standings_results[8:24]:
            assert entry["zone"] == "playoff", f"{entry['team']} (pos {entry['position']}) should be playoff"

    def test_qualification_zones_eliminated(
        self, sample_standings_results,
    ):
        """Positions 25-36 get zone='eliminated'."""
        for entry in sample_standings_results[24:]:
            assert entry["zone"] == "eliminated", f"{entry['team']} (pos {entry['position']}) should be eliminated"

    # ═══════════════════════════════════════════════════════════════════════════
    # ── Full Standings Tests
    # ═══════════════════════════════════════════════════════════════════════════

    def test_36_team_full_standings(
        self, sample_fixture_schedule, sample_36_teams, sample_rng, sample_uefa_coefficients,
    ):
        """36 teams with different scores produce correct ranking."""
        from competitions.ucl.src.groups import simulate_swiss_matches

        elos = {n: d["elo"] for n, d in sample_36_teams.items()}
        results = simulate_swiss_matches(sample_fixture_schedule, elos, sample_rng)
        uefa = {n: d["coefficient"] for n, d in sample_36_teams.items()}
        standings = compute_swiss_standings(results, elo_ratings=elos, uefa_coefficients=uefa)

        assert len(standings) == 36
        assert standings[0]["position"] == 1
        assert standings[35]["position"] == 36
        # Positions are sequential
        for i, entry in enumerate(standings):
            assert entry["position"] == i + 1
        # First 8 are top_8
        assert all(s["zone"] == "top_8" for s in standings[:8])
        # Next 16 are playoff
        assert all(s["zone"] == "playoff" for s in standings[8:24])
        # Last 12 are eliminated
        assert all(s["zone"] == "eliminated" for s in standings[24:])
        # All required fields present
        required = {"team", "position", "zone", "pts", "gd", "gs", "away_gs",
                     "wins", "away_wins", "opp_pts", "opp_gd", "opp_gs",
                     "conduct_score", "uefa_coefficient", "elo"}
        for entry in standings:
            missing = required - set(entry.keys())
            assert not missing, f"{entry['team']} missing: {missing}"

    # ── Test: Opponent stats correctness ─────────────────────────────────

    def test_opponent_stats_correctness(self):
        """Opponent stats (steps 6-8) use pre-tiebreak raw aggregates, not post-rank values."""
        # 4 teams: A beats C 3-0, B beats D 1-0, C beats D 2-0.
        # Raw aggregates:
        #   A: 3pts, +3GD, 3GS, opponent=C
        #   B: 3pts, +1GD, 1GS, opponent=D
        #   C: 3pts (from beating D), -1GD (lost to A 3-0, beat D 2-0 = -1+2=+1GD), 2GS
        #   D: 0pts, -3GD (lost to B 1-0 and C 2-0)
        matches = {
            "M1": _r("M1", "A", "C", 3, 0),
            "M2": _r("M2", "B", "D", 1, 0),
            "M3": _r("M3", "C", "D", 2, 0),
        }
        st = _standings(matches)

        a_stats = next(s for s in st if s["team"] == "A")
        b_stats = next(s for s in st if s["team"] == "B")

        # Pre-tiebreak raw aggregates:
        # C's raw stats: 3pts (W vs D 2-0), -1 GD (lost 3-0 to A, won 2-0 vs D), 2 GS
        # D's raw stats: 0pts, -3 GD (lost 1-0 to B, 2-0 to C), 0 GS
        # A's opponent C has: pts=3, gd=-1, gs=2
        # B's opponent D has: pts=0, gd=-3, gs=0
        assert a_stats["opp_pts"] == 3
        assert a_stats["opp_gd"] == -1
        assert a_stats["opp_gs"] == 2
        assert b_stats["opp_pts"] == 0
        assert b_stats["opp_gd"] == -3
        assert b_stats["opp_gs"] == 0
