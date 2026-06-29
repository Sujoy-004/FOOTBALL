"""SimulationResult dataclass — abstract result contract for UCL display layer.

This is the architectural spine of Phase 3 (D-15, D-16, D-17):
- Phase 3 CLI creates this from run_monte_carlo() output + one extra bracket iteration.
- Phase 4 creates this from BSD-enriched data.
- Display functions never import simulation.py or knockout.py — only result.py.

Owned by orchestration (Phase 3), not by simulation engine or BSD (D-16).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SimulationResult:
    """Abstract result contract consumed by all display functions.

    Carries both aggregated probabilities (from Monte Carlo) and one
    representative bracket snapshot (from a single extra iteration).

    Fields use JSON-native types throughout so dataclasses.asdict()
    produces JSON directly with no custom serializers needed (D-20).
    """

    # ── Summary metadata ──
    snapshot_date: str
    n_iterations: int
    seed: int

    # ── League table (36 rows, position-ordered) ──
    standings: list[dict]  # [{team, position, pts, gd, gs, zone, ...}]

    # ── Per-team probabilities (from MC aggregation) ──
    teams: dict[str, dict]  # {team_name: {top_8_prob, champion_prob, stage_*_prob, ...}}

    # ── Playoff ties (from one representative iteration) ──
    playoff_ties: dict[int, dict]  # {tie_number: simulate_two_legged_tie() result}
    playoff_winners: dict[int, str]  # {tie_number: team_name}

    # ── Knockout bracket (from one representative iteration) ──
    bracket_rounds: dict[str, list[dict]]  # {round_name: [{match_id, team_a, team_b, winner, result}]}
    bracket_champion: str | None  # team name or None

    # ── Stage tracking (all 36 teams) ──
    stages: dict[str, str]  # {team_name: stage_string}

    # ── Stage order for interpretation ──
    stage_order: list[str] = field(
        default_factory=lambda: [
            "eliminated",
            "playoff",
            "r16",
            "qf",
            "sf",
            "final",
            "champion",
        ]
    )

    # ── Validation results (Phase 4 — backward-compatible, D-09) ──
    validation: dict | None = field(default=None)
