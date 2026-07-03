"""Simulation mode orchestrator for UCL.

Routes between simulate, replay, and live modes per D-05.
Each mode resolves played_matches from its source, then delegates
to the simulation engine which is mode-agnostic.

Extended in Phase 10 (Plan 02) to support Glicko-1 rating system
uncertainty propagation via the *rating_system* parameter.

Usage:
    from competitions.ucl.src.orchestrator import run_simulation
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict

from football_core.provider import FixtureSchedule

logger = logging.getLogger(__name__)


def resolve_played_matches(
    args: argparse.Namespace,
    data_dir: str,
    fixtures_schedule: FixtureSchedule,
) -> dict[tuple[str, str], tuple[int, int]] | None:
    """Resolve played_matches based on CLI mode (D-05 orchestration).

    Returns None for simulate mode (full synthetic).
    Loads from JSON file for replay mode (ReplayMatchResultProvider).
    Fetches from BSD API for live mode (BSDMatchResultProvider).

    All mode logic lives here — NOT in main.py or the engine.
    """
    if args.mode == "replay":
        if not args.replay_data:
            print("Error: --replay-data PATH required for replay mode",
                  file=sys.stderr)
            sys.exit(1)
        from competitions.ucl.src.result_provider import ReplayMatchResultProvider
        provider = ReplayMatchResultProvider(args.replay_data)
        return provider.load()

    elif args.mode == "live":
        api_key = args.api_key or os.environ.get("BSD_API_KEY")
        if not api_key:
            print("Error: BSD_API_KEY required for live mode",
                  file=sys.stderr)
            sys.exit(1)
        from competitions.ucl.src.result_provider import BSDMatchResultProvider
        team_aliases_path = os.path.join(data_dir, "team_aliases.json")
        with open(team_aliases_path) as f:
            team_aliases = json.load(f)
        provider = BSDMatchResultProvider(
            api_key, team_aliases, asdict(fixtures_schedule),
        )
        return provider.load()

    return None


def run_simulation(
    fixtures_schedule: FixtureSchedule,
    elo_ratings: dict[str, float],
    seed: int,
    n_iterations: int,
    args: argparse.Namespace,
    data_dir: str,
    rating_system: object | None = None,
    compute_ci: bool = False,
) -> object:
    """Orchestrate the full simulation: resolve mode, run MC, return result.

    This is the main entry point called by main.py after CLI parsing.

    Parameters
    ----------
    rating_system:
        Optional :class:`~football_core.glicko.RatingSystem` for Glicko-1
        uncertainty propagation.  When provided, the MC loop samples
        team strengths from N(μ, σ²) per iteration.  ``None`` uses the
        existing point-estimate path.
    compute_ci:
        If True, compute bootstrap CIs on champion probabilities
        (default False).  Passed through to the MC loop.
    """
    played_matches = resolve_played_matches(args, data_dir, fixtures_schedule)

    from competitions.ucl.main import build_simulation_result
    return build_simulation_result(
        fixtures_schedule, elo_ratings, seed, n_iterations,
        played_matches=played_matches,
        rating_system=rating_system,
        compute_ci=compute_ci,
    )
