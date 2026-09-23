"""LaLiga leak-free historical evaluation core.

The leak-free context-construction primitives (prior-only ``build_context_for_match``,
strictly-before ``ReplayResultProvider``, ``order_matches``, ``frequency_baseline``,
``split_chronological``, ``gate_verdict``) are audited, competition-agnostic logic
that already ships with UCL at ``competitions/ucl/src/historical.py``. We reuse
that module READ-ONLY (never modified) so that every LaLiga historical prediction
has exactly the same leakage guarantees, verified once in the UCL backfill and
independently re-audited for LaLiga by the Phase 11 leakage audit.

This module is the LaLiga-facing entry point: import the primitives from here so
evaluation code never couples directly to the UCL package layout.
"""

from __future__ import annotations

from competitions.ucl.src.historical import (
    ReplayResultProvider,
    available_signals,
    build_context_for_match,
    chronological_key,
    distinct_keys,
    frequency_baseline,
    gate_verdict,
    is_completed,
    load_replay_matches,
    order_matches,
    outcome_index,
    prior_matches,
    result_row,
    split_chronological,
)

__all__ = [
    "ReplayResultProvider",
    "available_signals",
    "build_context_for_match",
    "chronological_key",
    "distinct_keys",
    "frequency_baseline",
    "gate_verdict",
    "is_completed",
    "load_replay_matches",
    "order_matches",
    "outcome_index",
    "prior_matches",
    "result_row",
    "split_chronological",
]