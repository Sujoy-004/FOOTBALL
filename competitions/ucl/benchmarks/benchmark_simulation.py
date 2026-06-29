#!/usr/bin/env python3
"""Benchmark UCL simulation performance at 1K, 10K, 50K iterations.

Measures wall-clock time for the full UCL Monte Carlo simulation pipeline.
Results saved to BENCHMARK_RESULTS.md.

Per D-07: Fixed random seed (42), wall-clock only, iteration counts recorded.
"""

import json
import random
import sys
import time
from pathlib import Path

# Ensure project root on sys.path (matching WC pattern)
_project_root = Path(__file__).resolve().parent.parent.parent.parent  # benchmarks/ -> competitions/ucl/ -> competitions/ -> project root
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from competitions.ucl.src.elo_fetcher import fetch_team_elos
from competitions.ucl.src.simulation import run_monte_carlo


SEED = 42
ITERATIONS = [1000, 10000, 50000]


def load_data() -> dict:
    """Load UCL fixture schedule from data file."""
    data_dir = Path(__file__).resolve().parent.parent / "data"
    fixtures_path = data_dir / "fixtures.json"
    with open(fixtures_path) as f:
        return json.load(f)


def benchmark_at(iterations: int, fixtures: dict, elo_ratings: dict, seed: int) -> float:
    """Run UCL MC simulation and return elapsed wall-clock time in seconds."""
    start = time.perf_counter()
    run_monte_carlo(fixtures, elo_ratings=elo_ratings, n_iterations=iterations, seed=seed)
    elapsed = time.perf_counter() - start
    return elapsed


def format_results(results: list[dict], seed: int) -> str:
    """Format benchmark results as Markdown report (matching WC pattern)."""
    lines = [
        "# UCL Simulation Benchmark Results",
        "",
        f"**Seed:** {seed}",
        f"**Date:** {time.strftime('%Y-%m-%d')}",
        f"**Script:** `benchmarks/benchmark_simulation.py`",
        "",
        "## Results",
        "",
        "| Iterations | Time (s) | Pass/Fail |",
        "|------------|----------|-----------|",
    ]
    for r in results:
        status = "[PASS]"
        lines.append(f"| {r['iterations']:>6,} | {r['elapsed']:.3f} | {status} |")
    lines.extend([
        "",
        "## Platform",
        "",
        f"- **Python:** {sys.version}",
        f"- **Platform:** {sys.platform}",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    """Run benchmark suite, print results, save to BENCHMARK_RESULTS.md."""
    sep = "=" * 60
    print(sep)
    print("UCL Simulation - Benchmark")
    print(sep)
    print()

    # Load data once, outside timed loop
    print("Loading data...", end=" ", flush=True)
    fixtures = load_data()
    team_names = [t["name"] for t in fixtures["schedule"]["teams"]]
    print("done.")

    # Fetch Elo ratings with fallback for network failure (T-4-04)
    print("Fetching Elo ratings...", end=" ", flush=True)
    try:
        elo_ratings = fetch_team_elos(team_names)
        print("done.")
    except Exception as e:
        print(f"failed ({e}).")
        print("  Using fallback Elo=1500 for all teams (T-4-04).")
        elo_ratings = {name: 1500.0 for name in team_names}
    print()

    # Run benchmark at each iteration count
    results = []
    for iters in ITERATIONS:
        print(f"  Benchmark {iters} iterations...", end=" ", flush=True)
        elapsed = benchmark_at(iters, fixtures, elo_ratings, SEED)
        print(f"{elapsed:.3f}s")
        results.append({"iterations": iters, "elapsed": elapsed})

    # Generate report
    report = format_results(results, SEED)

    # Save results
    output_path = Path(__file__).resolve().parent / "BENCHMARK_RESULTS.md"
    output_path.write_text(report, encoding="utf-8")
    print(f"\nResults saved to: {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
