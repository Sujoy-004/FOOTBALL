"""UCL display functions — formatted output for simulation results.

D-17: This module imports ONLY from competitions.ucl.result and stdlib.
No imports from competitions.ucl.src.

Exports:
    - print_summary(result: SimulationResult) -> None
    - print_league_table(result: SimulationResult) -> None
    - _supports_color() -> bool
    - _ansi(code: str) -> callable
"""

from __future__ import annotations

import sys

from competitions.ucl.result import SimulationResult

# ── Module-level constants ──────────────────────────────────────────────

NO_COLOR: bool = False  # Set by main.py when stdout is not a TTY
_SECTION_SEP: str = "=" * 60

# ANSI color codes (D-10: green=top_8, yellow=playoff, red=eliminated)
_GREEN: str = "32"
_YELLOW: str = "33"
_RED: str = "31"
_BOLD: str = "1"


# ── ANSI helpers ────────────────────────────────────────────────────────


def _supports_color() -> bool:
    """Return True if stdout is a TTY and NO_COLOR is not set (D-11)."""
    return sys.stdout.isatty() and not NO_COLOR


def _ansi(code: str):
    """Return a wrapper function that adds ANSI escape codes around text.

    If color is not supported, returns text unchanged.
    """
    def wrapper(text: str) -> str:
        if _supports_color():
            return f"\033[{code}m{text}\033[0m"
        return text
    return wrapper


_green = _ansi(_GREEN)      # top-8 zone
_yellow = _ansi(_YELLOW)    # playoff zone
_red = _ansi(_RED)          # eliminated zone
_bold = _ansi(_BOLD)        # section headings and column headers


def _zone_color(zone: str):
    """Return the ANSI color wrapper for a given qualification zone.

    Args:
        zone: One of "top_8", "playoff", "eliminated".

    Returns:
        A callable that wraps text in the zone's ANSI color,
        or the identity function for unknown zones.
    """
    if zone == "top_8":
        return _green
    elif zone == "playoff":
        return _yellow
    elif zone == "eliminated":
        return _red
    return lambda x: x  # identity for unknown zones


# ── Display functions (D-06: summary first, league table second) ────────


def print_summary(result: SimulationResult) -> None:
    """Print simulation summary metadata (D-06 position 1).

    Includes iteration count, random seed, and snapshot date.
    """
    print()
    print(f"==== Simulation Summary ====")
    print()
    print(f"  Iterations: {result.n_iterations}")
    print(f"  Seed: {result.seed}")
    print(f"  Snapshot: {result.snapshot_date}")
    print()


def print_league_table(result: SimulationResult) -> None:
    """Print formatted 36-row league table with ANSI zone coloring (D-06 position 2).

    Columns: Pos, Team, Pts, GD, GS, Zone (D-07).
    Zone color: green for top_8, yellow for playoff, red for eliminated (D-10).
    Auto-detects terminal color support (D-11).
    """
    print()
    print(f"==== League Table ====")
    print()

    # ── Header row (bold) ──
    print(
        f"  {_bold('Pos')}  "
        f"{_bold('Team'):<28} "
        f"{_bold('Pts')} "
        f"{_bold('GD')} "
        f"{_bold('GS')} "
        f"{_bold('Zone')}"
    )

    # ── Separator ──
    print("-" * 48)

    # ── Data rows (sorted by position ascending) ──
    for entry in result.standings:
        zone_label = entry["zone"].upper()
        color_fn = _zone_color(entry["zone"])

        pos_str = f"{entry['position']:>2}."
        team_str = f"{entry['team']:<24}"
        pts_str = f"{entry['pts']:>3}"
        gd_str = f"{entry['gd']:>+4}"
        gs_str = f"{entry['gs']:>3}"
        zone_str = color_fn(f"{zone_label:<10}")

        print(f"{pos_str}  {team_str} {pts_str} {gd_str} {gs_str} {zone_str}")

    print()
