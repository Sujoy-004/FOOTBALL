#!/usr/bin/env python3
"""Benchmark the Monte Carlo simulation performance.

Measures elapsed time for N iterations and reports PASS/FAIL
against the 5-second threshold. Run from worldcup_predictor/:
    python scripts/benchmark_simulation.py
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.constants import DATA_DIR
from src.knockout import run_full_simulation
from src.state import load_annex_c, load_bracket, load_groups, load_played, load_teams


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark Monte Carlo simulation performance"
    )
    parser.add_argument(
        "--iterations", type=int, default=50000,
        help="Number of simulation iterations (default: 50000)",
    )
    args = parser.parse_args()

    teams = load_teams(DATA_DIR)
    bracket = load_bracket(DATA_DIR)
    played = load_played(DATA_DIR)
    groups = load_groups(DATA_DIR, teams=teams)
    annex_c = load_annex_c(DATA_DIR)

    _ = run_full_simulation(teams, groups, bracket, annex_c, played, iterations=100)

    start = time.perf_counter()
    probs = run_full_simulation(teams, groups, bracket, annex_c, played, iterations=args.iterations)
    elapsed = time.perf_counter() - start

    rate = args.iterations / elapsed
    threshold = 5.0
    status = "PASS" if elapsed < threshold else "FAIL"

    print("Monte Carlo Simulation Benchmark")
    print("-" * 48)
    print(f"  Iterations:    {args.iterations:>8}")
    print(f"  Elapsed:       {elapsed:>8.3f}s")
    print(f"  Rate:          {rate:>8.0f} sims/sec")
    print(f"  Threshold:     {threshold:>8.3f}s")
    print(f"  Status:        {status:>8}")
    print("-" * 48)

    champion_sum = sum(p["champion"] for p in probs.values())
    print(f"  Champion sum:  {champion_sum:>8.4f}")

    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
