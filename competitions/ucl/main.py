"""Minimal CLI entry point for UCL live data pipeline.

Usage:
    python -m competitions.ucl.main --mode live --once -n 100 --seed 42
    python -m competitions.ucl.main --help
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="competitions.ucl.main",
        description="UCL live data pipeline CLI",
    )
    p.add_argument(
        "--mode", choices=["live"], default="live",
        help="Pipeline mode (default: live)",
    )
    p.add_argument(
        "--once", action="store_true",
        help="Run a single fetch+compute cycle and exit",
    )
    p.add_argument(
        "-n", "--n-iterations", type=int, default=10000,
        help="Monte Carlo iterations (default: 10000)",
    )
    p.add_argument(
        "--seed", type=int, default=42,
        help="RNG seed (default: 42)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv)

    # ── Resolve paths ────────────────────────────────────────────────────
    data_dir = Path(__file__).resolve().parent / "data"
    if not data_dir.is_dir():
        print(f"[error] data directory not found: {data_dir}", file=sys.stderr)
        return 1

    # ── Resolve credentials ──────────────────────────────────────────────
    bsd_key = os.environ.get("BSD_API_KEY", "")
    fdo_key = os.environ.get("FOOTBALL_DATA_ORG_KEY", "")

    # ── Select provider ──────────────────────────────────────────────────
    from web.common import get_data_provider

    provider = get_data_provider(bsd_key, fdo_key, bsd_league_id=7)
    provider_name = type(provider).__name__ if provider else "none"

    if provider is None:
        print("[error] No data provider available — set BSD_API_KEY or "
              "FOOTBALL_DATA_ORG_KEY", file=sys.stderr)
        return 1

    # ── Step 1: Ingestion ────────────────────────────────────────────────
    from competitions.ucl.src.pipeline import fetch_live_data

    print(f"[info] Provider : {provider_name}")
    print(f"[info] Data dir : {data_dir}")

    # Safety: if data_dir is the real repo data and there's no FOOTBALL_LIVE
    # env var set, warn the user about live writes to production stores.
    _repo_data = Path(__file__).resolve().parent / "data"
    if data_dir == _repo_data and not os.environ.get("FOOTBALL_LIVE"):
        print("[warn] Writing to production data directory. "
              "Set FOOTBALL_LIVE=1 to confirm intentional live ingestion.")
        return 1
    print()

    ingest = fetch_live_data(
        str(data_dir),
        bsd_api_key=bsd_key,
        football_data_org_key=fdo_key,
        ucl_league_id=7,
        provider=provider,
    )

    status = ingest.get("status", "unknown")
    n_raw = ingest.get("n_raw", 0)
    n_updated = ingest.get("n_updated", 0)
    report = ingest.get("report", {})
    per_season = ingest.get("per_season", {})

    # Determine provider season from ingest result.
    provider_season = None
    for sk, sv in per_season.items():
        if isinstance(sv, dict) and not sv.get("legacy"):
            provider_season = sk
            break

    if status != "ok":
        err = report.get("error", "unknown error")
        print(f"[error] Ingestion {status}: {err}", file=sys.stderr)
        fin = report.get("finished", {})
        print(f"  received={fin.get('received', 0)}  "
              f"skipped_unmatchable={fin.get('skipped_unmatchable', 0)}  "
              f"skipped_no_target={fin.get('skipped_no_target', 0)}")
        return 1

    # ── Step 2: Compute ──────────────────────────────────────────────────
    from competitions.ucl.src.orchestrator import run_compute_all

    compute = run_compute_all(
        str(data_dir),
        bsd_api_key=bsd_key,
        seed=args.seed,
        n_iterations=args.n_iterations,
        provider_season=provider_season,
    )

    if compute.get("error"):
        print(f"[error] Compute failed: {compute['error']}", file=sys.stderr)
        for step in compute.get("boot", []):
            if step.get("status") == "error":
                print(f"  {step['step']}: {step['output']}")
        return 1

    # ── Step 3: Summary ──────────────────────────────────────────────────
    mode = compute.get("mode", "?")
    champion = compute.get("champion", {})
    teams = compute.get("all_teams") or compute.get("teams", [])
    n_teams = compute.get("n_teams", len(teams))
    phase = compute.get("phase", {})
    lifecycle = compute.get("lifecycle", {})

    print()
    print("=" * 56)
    print("  UCL Pipeline Summary")
    print("=" * 56)
    print(f"  Provider        : {provider_name}")
    print(f"  Ingest status   : {status}")
    print(f"  Raw matches     : {n_raw}")
    print(f"  Updated matches : {n_updated}")
    print(f"  Compute mode    : {mode}")
    if provider_season:
        print(f"  Active season   : {provider_season}")
    if lifecycle:
        lc_label = lifecycle.get("label", "")
        lc_stage = lifecycle.get("stage", "")
        if lc_label or lc_stage:
            print(f"  Lifecycle       : {lc_label or lc_stage}")
    if phase:
        ph = phase.get("phase", "")
        ph_label = phase.get("label", "")
        if ph:
            print(f"  Phase           : {ph_label or ph}")
    print(f"  Teams           : {n_teams}")
    if champion and isinstance(champion, dict):
        ch_name = champion.get("team", champion.get("name", ""))
        ch_prob = champion.get("champion_prob", "")
        if ch_name:
            prob_str = f" ({ch_prob:.1%})" if isinstance(ch_prob, (int, float)) else ""
            print(f"  Champion        : {ch_name}{prob_str}")
    print("=" * 56)
    print()

    # ── Per-season breakdown ─────────────────────────────────────────────
    if per_season:
        print("  Per-season ingest:")
        for sk, sv in per_season.items():
            if not isinstance(sv, dict):
                continue
            legacy_tag = " (legacy)" if sv.get("legacy") else ""
            fx = sv.get("fixtures_total", sv.get("fixtures_count", "?"))
            res_a = sv.get("results_added", sv.get("results_count", "?"))
            res_u = sv.get("results_updated", "")
            res_str = f"results +{res_a}"
            if res_u:
                res_str += f" / ~{res_u}"
            print(f"    {sk}{legacy_tag}: fixtures={fx}, {res_str}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
