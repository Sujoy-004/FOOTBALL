"""Benchmark simulation performance at various iteration counts.

Usage:
    python -m competitions.worldcup.benchmarks.benchmark_simulation

Measures wall-clock time for run_full_simulation() at 1K, 10K, 50K, and 100K
iterations with the same seed for reproducibility.
"""

import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BENCHMARKS_DIR = os.path.dirname(SCRIPT_DIR)
WC_DIR = os.path.dirname(BENCHMARKS_DIR)
COMPETITIONS_DIR = os.path.dirname(WC_DIR)
REPO_ROOT = os.path.dirname(COMPETITIONS_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from competitions.worldcup.src.state import (
    load_teams, load_groups, load_bracket, load_annex_c,
    load_played, load_played_groups,
)
from competitions.worldcup.src.knockout import run_full_simulation


def run_benchmark(data_dir: str | None = None) -> None:
    """Run simulation benchmark at multiple iteration counts."""
    if data_dir is None:
        data_dir = os.path.join(WC_DIR, "data")

    print("Loading data files...")
    teams = load_teams(data_dir)
    groups = load_groups(data_dir)
    bracket = load_bracket(data_dir)
    annex_c = load_annex_c(data_dir)
    played = load_played(data_dir)
    played_groups = load_played_groups(data_dir)

    if not teams:
        print("Error: No team data found. Run normal polling first to populate data files.")
        sys.exit(1)

    iteration_counts = [1000, 10000, 50000, 100000]
    seed = 42

    print(f"\n{'Iterations':<15} {'Time (s)':<12} {'Teams/s':<12}")
    print("-" * 39)

    for n_iter in iteration_counts:
        if n_iter == 1000:
            _ = run_full_simulation(
                teams, groups, bracket, annex_c, played, played_groups,
                seed=seed, iterations=100,
            )

        start = time.perf_counter()
        result = run_full_simulation(
            teams, groups, bracket, annex_c, played, played_groups,
            seed=seed, iterations=n_iter,
        )
        elapsed = time.perf_counter() - start

        team_count = len(result)
        teams_per_sec = (team_count * n_iter) / elapsed if elapsed > 0 else 0
        print(f"{n_iter:<15} {elapsed:<12.3f} {teams_per_sec:<12.0f}")

    print("\nBenchmark complete.")


if __name__ == "__main__":
    data_dir = sys.argv[1] if len(sys.argv) > 1 else None
    run_benchmark(data_dir)
