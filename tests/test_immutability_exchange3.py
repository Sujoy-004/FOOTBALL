"""Exchange 3: real-match immutability guarantees under simulation.

Proves the truth invariant end-to-end:
- canonical inputs are byte-identical before/after simulation runs
- played matches are never resampled (scores frozen across many universes)
- simulations never write canonical result files
"""

from __future__ import annotations

import copy
import json
import random
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WC_DATA = ROOT / "competitions" / "worldcup" / "data"
UCL_DATA = ROOT / "competitions" / "ucl" / "data"


# ── WC: input immutability ──────────────────────────────────────────────────

def _load_wc():
    return (
        json.loads((WC_DATA / "teams.json").read_text("utf-8")),
        json.loads((WC_DATA / "groups.json").read_text("utf-8")),
        json.loads((WC_DATA / "bracket.json").read_text("utf-8")),
        json.loads((WC_DATA / "annex_c.json").read_text("utf-8")),
    )


def test_wc_simulation_leaves_canonical_inputs_unchanged():
    from competitions.worldcup.src.knockout import run_full_simulation
    teams, groups, bracket, annex = _load_wc()
    before = {n: copy.deepcopy(o) for n, o in
              [("teams", teams), ("groups", groups),
               ("bracket", bracket), ("annex", annex)]}
    run_full_simulation(teams, groups, bracket, annex, {},
                        iterations=15, seed=42, played_groups={})
    assert teams == before["teams"]
    assert groups == before["groups"]
    assert bracket == before["bracket"]
    assert annex == before["annex"]


def test_wc_played_group_scores_never_resampled_across_universes():
    """A real group result must appear verbatim in every sampled universe."""
    from football_core.groups import precompute_matchup_lambdas, simulate_group_matches
    from competitions.worldcup.src.constants import EXPECTED_GOALS_BASE_RATE

    _, groups, _, _ = _load_wc()
    teams = json.loads((WC_DATA / "teams.json").read_text("utf-8"))
    elo = {n: d["elo"] for n, d in teams.items()}
    real = {
        "GS_A_01": {"team_a": "Mexico", "team_b": "South Africa",
                    "home_score": 3, "away_score": 1, "winner": "Mexico"},
    }
    lambdas = precompute_matchup_lambdas(groups, elo,
                                         base_rate=EXPECTED_GOALS_BASE_RATE)
    for seed in range(25):
        results = simulate_group_matches(
            groups, {}, elo, random.Random(seed),
            base_rate=EXPECTED_GOALS_BASE_RATE,
            matchup_lambdas=lambdas, played_groups=real)
        got = results["A"]["GS_A_01"]
        assert (got["score_a"], got["score_b"]) == (3, 1)
        assert got["winner"] == "Mexico"


def test_wc_completed_tournament_yields_real_champion_with_certainty():
    """When every match is a real fact, the champion probability is exactly
    1.0 for the historical winner - simulation cannot replace it."""
    from competitions.worldcup.src.knockout import run_full_simulation
    teams, groups, bracket, annex = _load_wc()
    played = json.loads((WC_DATA / "played.json").read_text("utf-8"))
    pg_raw = (WC_DATA / "played_groups.json").read_text("utf-8")
    played_groups = json.loads(pg_raw) if pg_raw.strip() else {}
    real_champion = played.get("FINAL", {}).get("winner")
    assert real_champion, "fixture data must contain a FINAL winner"
    out = run_full_simulation(teams, groups, bracket, annex, played,
                              iterations=40, seed=42,
                              played_groups=played_groups)
    for team, probs in out.items():
        if team == "_meta":
            continue
        expected = 1.0 if team == real_champion else 0.0
        assert probs["champion"] == expected, team


# ── UCL: input immutability + conditioning ─────────────────────────────────

def test_ucl_draw_steps_no_longer_mutate_caller_data():
    """Regression: the playoff/R16 draw shuffles used to write position and
    seed fields back into the caller's structures, leaking state across
    Monte Carlo iterations."""
    from competitions.ucl.src.knockout import build_r16_bracket, simulate_playoff_round

    pairings = json.loads((UCL_DATA / "playoff_pairings.json").read_text("utf-8"))
    bracket_rules = json.loads((UCL_DATA / "bracket_rules.json").read_text("utf-8"))
    fixtures = json.loads((UCL_DATA / "fixtures.json").read_text("utf-8"))
    from football_core.provider import FixtureSchedule
    sched = FixtureSchedule.from_dict(fixtures["schedule"])
    coeffs = {t.name: t.coefficient for t in sched.teams}
    mx = max(coeffs.values())
    elo = {t.name: 1400.0 + (coeffs[t.name] / mx) * 400.0 for t in sched.teams}

    # Build standings once via one league realization
    from competitions.ucl.src.simulation import simulate_league_phase
    from football_core.groups import precompute_matchup_lambdas_league
    lambdas = precompute_matchup_lambdas_league(
        {"schedule": fixtures["schedule"]}, elo, 1.25)
    standings = simulate_league_phase({"schedule": fixtures["schedule"]},
                                      elo, random.Random(5), matchup_lambdas=lambdas)

    pairings_before = copy.deepcopy(pairings)
    bracket_before = copy.deepcopy(bracket_rules)
    playoff = simulate_playoff_round(standings, elo, random.Random(6),
                                     pairings_data=pairings)
    build_r16_bracket(standings, playoff, bracket_data=bracket_rules,
                      rng=random.Random(7))
    assert pairings == pairings_before
    assert bracket_rules == bracket_before


def test_ucl_engine_run_leaves_rule_inputs_unchanged():
    from dataclasses import asdict
    from football_core.provider import FixtureSchedule
    from competitions.ucl.src.rules import UCLRules
    from football_core.simulation import MonteCarloEngine, SimulationRequest

    fixtures = json.loads((UCL_DATA / "fixtures.json").read_text("utf-8"))
    sched = FixtureSchedule.from_dict(fixtures["schedule"])
    fd = {"schedule": asdict(sched)}
    coeffs = {t.name: t.coefficient for t in sched.teams}
    mx = max(coeffs.values())
    elo = {t.name: 1400.0 + (coeffs[t.name] / mx) * 400.0 for t in sched.teams}
    pairings = json.loads((UCL_DATA / "playoff_pairings.json").read_text("utf-8"))
    rules_file = json.loads((UCL_DATA / "bracket_rules.json").read_text("utf-8"))
    before_p = copy.deepcopy(pairings)
    before_b = copy.deepcopy(rules_file)

    rules = UCLRules(fd, elo, pairings_data=pairings,
                     bracket_rules_data=rules_file)
    MonteCarloEngine().run(
        SimulationRequest("ucl", "test", 12, seed=42), rules)
    assert pairings == before_p
    assert rules_file == before_b


def test_ucl_all_played_league_matches_conditioned_exactly():
    """With all 144 real league matches locked as facts, every iteration's
    league table IS the real table - avg_pts equals actual season points."""
    from dataclasses import asdict
    from football_core.provider import FixtureSchedule
    from competitions.ucl.src.simulation import run_monte_carlo
    from competitions.ucl.src.orchestrator import _load_league_played_pairs

    pairs = _load_league_played_pairs(str(UCL_DATA))
    assert pairs, "real league results must exist for this test"
    fixtures = json.loads((UCL_DATA / "fixtures.json").read_text("utf-8"))
    sched = FixtureSchedule.from_dict(fixtures["schedule"])
    fd = {"schedule": asdict(sched)}
    coeffs = {t.name: t.coefficient for t in sched.teams}
    mx = max(coeffs.values())
    elo = {t.name: 1400.0 + (coeffs[t.name] / mx) * 400.0 for t in sched.teams}

    out = run_monte_carlo(fd, elo_ratings=elo, n_iterations=10, seed=42,
                          played_matches=pairs)
    # Real points per team derived directly from the ledger.
    real_pts: dict[str, int] = {}
    # Use the tracked league bootstrap instead of private runtime results.json
    rows = json.loads((UCL_DATA / "bootstrap" / "league_results_2025_26.json").read_text("utf-8"))["matches"]
    for r in rows:
        hs, aw = r["home_score"], r["away_score"]
        ta, tb = r["team_a"], r["team_b"]
        real_pts.setdefault(ta, 0)
        real_pts.setdefault(tb, 0)
        if hs > aw:
            real_pts[ta] += 3
        elif aw > hs:
            real_pts[tb] += 3
        else:
            real_pts[ta] += 1
            real_pts[tb] += 1
    for team, pts in real_pts.items():
        got = out["teams"][team]["avg_pts"]
        assert abs(got - pts) < 1e-9, f"{team}: avg_pts {got} != real {pts}"
        # Zone membership is decided factually too.
        zone_probs = (out["teams"][team]["top_8_prob"],
                      out["teams"][team]["playoff_prob"],
                      out["teams"][team]["eliminated_prob"])
        decided = sum(1 for p in zone_probs if p in (0.0, 1.0))
        assert decided == 3, f"{team} league-zone probabilities must be factual"


def test_ucl_simulation_writes_only_snapshot_not_canonical_files(tmp_path):
    from competitions.ucl.src.pipeline import run_mc_simulation
    for f in ("fixtures.json", "team_aliases.json"):
        shutil.copy(UCL_DATA / f, tmp_path / f)
    canonical = tmp_path / "results.json"
    canonical.write_text('{"matches": []}', encoding="utf-8")

    fixtures = json.loads((UCL_DATA / "fixtures.json").read_text("utf-8"))
    teams = fixtures["schedule"]["teams"]
    coeffs = {t["name"]: t["coefficient"] for t in teams}
    mx = max(coeffs.values())
    elo = {n: 1400.0 + (c / mx) * 400.0 for n, c in coeffs.items()}
    run_mc_simulation(str(tmp_path), n_iterations=5, seed=42,
                      elo_ratings_override=elo)
    assert canonical.read_bytes() == b'{"matches": []}'
    assert not (tmp_path / "knockout_results.json").exists()
