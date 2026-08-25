"""Benchmark: canonical ensemble + Monte Carlo simulation performance.

Usage (from repo root):
    python -m competitions.worldcup.benchmarks.benchmark_simulation

Measures the real production path — EnsembleEngine blended match
probabilities feeding run_full_simulation() — at 1K / 10K / 50K / 100K
iterations, 3 repeats each, fixed seed for reproducibility.
"""

import os
import platform
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WC_DIR = os.path.dirname(SCRIPT_DIR)                # competitions/worldcup
COMPETITIONS_DIR = os.path.dirname(WC_DIR)
REPO_ROOT = os.path.dirname(COMPETITIONS_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from football_core.state import load_played, load_played_groups, load_teams  # noqa: E402
from competitions.worldcup.src.engine import build_engine_from_caches  # noqa: E402
from competitions.worldcup.src.knockout import run_full_simulation  # noqa: E402
from competitions.worldcup.src.pipeline import build_blend_params  # noqa: E402
from competitions.worldcup.src.state import load_annex_c, load_bracket, load_groups  # noqa: E402

DATA_DIR = os.path.join(WC_DIR, "data")
SEED = 42
REPEATS = 3


def _collect_matches(groups_data: dict, bracket: list[dict]) -> list[dict]:
    matches = []
    inner = groups_data.get("groups", groups_data) if isinstance(groups_data, dict) else groups_data
    for g in inner.values():
        for m in g.get("matches", []):
            matches.append(m)
    matches.extend(bracket)
    return matches


def main() -> None:
    print("Environment:")
    print(f"  python   : {sys.version.split()[0]} ({platform.architecture()[0]})")
    print(f"  platform : {platform.platform()}")

    teams = load_teams(DATA_DIR)
    groups_data = load_groups(DATA_DIR, teams=teams)
    bracket = load_bracket(DATA_DIR)
    annex_c = load_annex_c(DATA_DIR)
    played = load_played(DATA_DIR)
    played_groups = load_played_groups(DATA_DIR)
    if not teams:
        sys.exit("No team data found.")

    # Canonical ensemble -> match probabilities (same as production path)
    engine = build_engine_from_caches()
    from football_core.signal import PredictionContext
    all_matches = _collect_matches(groups_data, bracket)
    ctx = PredictionContext(
        fixtures=all_matches,
        elo_ratings={n: d["elo"] for n, d in teams.items()},
        played_results=list(played.values()) + list(played_groups.values()),
    )
    preds = [engine.evaluate(m, ctx) for m in all_matches]
    blend_params = build_blend_params(preds, all_matches, engine)
    print(f"\nEnsemble: {len(preds)} matches blended, "
          f"signals={sorted(engine.weights)}\n")

    print(f"{'Iterations':<12} {'Run':<6} {'Time (s)':<10} {'Matches/s':<12}")
    print("-" * 44)
    results = {}
    for n_iter in [1000, 10000, 50000, 100000]:
        times = []
        for r in range(REPEATS):
            if n_iter == 1000 and r == 0:
                run_full_simulation(  # warm-up
                    teams, groups_data, bracket, annex_c, played,
                    iterations=200, seed=SEED, played_groups=played_groups,
                    blend_params=blend_params,
                )
            start = time.perf_counter()
            out = run_full_simulation(
                teams, groups_data, bracket, annex_c, played,
                iterations=n_iter, seed=SEED, played_groups=played_groups,
                blend_params=blend_params,
            )
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            champ_sum = sum(v["champion"] for k, v in out.items()
                            if not k.startswith("_"))
            assert abs(champ_sum - 1.0) < 0.05, "probabilities must sum to ~1"
        best = min(times)
        median = sorted(times)[len(times) // 2]
        results[n_iter] = {"best": best, "median": median}
        rate = len(teams) * n_iter / best
        print(f"{n_iter:<12} {f'x{REPEATS}':<6} {best:<10.3f} {rate:<12.0f}"
              f"   (median {median:.3f}s)")

    print("\nSummary (best of %d):" % REPEATS)
    for n_iter, r in results.items():
        print(f"  {n_iter:>7} iterations : {r['best']:.3f}s")
    print("\nBenchmark complete.")


if __name__ == "__main__":
    main()
