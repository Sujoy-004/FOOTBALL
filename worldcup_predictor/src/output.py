"""Console output module for the World Cup predictor.

Pure display functions using raw ANSI escape codes. No external dependencies.
"""

import sys
import time
from typing import Callable

from src.constants import POLL_INTERVAL


# Ensure stdout uses UTF-8 for Unicode symbols (▲, ▼, ⚠, →) on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NO_COLOR = False
"""Module-level flag: set to True to disable ANSI color output. Set from main.py after arg parsing (D-05)."""


def _supports_color() -> bool:
    """Return True if stdout is a TTY and NO_COLOR is not set."""
    return sys.stdout.isatty() and not NO_COLOR


def _ansi(code: str) -> Callable[[str], str]:
    """Factory: return a function that wraps text in ANSI escape code."""
    def wrapper(text: str) -> str:
        if _supports_color():
            return f"\033[{code}m{text}\033[0m"
        return text
    return wrapper


_dim = _ansi("2")
_bold_cyan = _ansi("1;36")
_green = _ansi("32")
_red = _ansi("31")
_bold_green = _ansi("1;32")
_bold_white = _ansi("1;37")
_bold_yellow = _ansi("1;33")
_bold_red = _ansi("1;31")


def _timestamp() -> str:
    """Return dim-gray timestamp string: [YYYY-MM-DD HH:MM:SS]."""
    return _dim(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}]")


def print_probability_table(probs: dict, prev_probs: dict | None = None) -> None:
    """Print the top-5 probability table with optional delta column."""
    sorted_names = sorted(probs, key=lambda n: probs[n]["champion"], reverse=True)
    top5 = sorted_names[:5]
    remaining = sorted_names[5:]

    label = "Initial probabilities:" if prev_probs is None else "UPDATED PROBABILITIES:"
    print(f"{_timestamp()} {_bold_cyan(label)}")

    has_delta = prev_probs is not None

    header = f"{'':>3} {'Team':<18} {'QF':>6} {'SF':>6} {'FINAL':>8} {'CHAMPION':>8}"
    if has_delta:
        header += f"  {'Delta':>8}"
    print(_bold_cyan(header))

    sep_len = 51 + (9 if has_delta else 0)
    print(_bold_cyan("-" * sep_len))

    for rank, name in enumerate(top5, 1):
        p = probs[name]
        row = f"{rank:>2}. {name:<18} {p['qf']:.3f} {p['sf']:.3f} {p['final']:.3f} {p['champion']:.3f}"
        if has_delta and name in prev_probs:
            delta = probs[name]["champion"] - prev_probs[name]["champion"]
            if delta > 0:
                delta_str = _green(f"▲ {delta:+.3f}")
            elif delta < 0:
                delta_str = _red(f"▼ {delta:+.3f}")
            else:
                delta_str = f" {'=':>6} "
            row += f"  {delta_str:>8}"
        elif has_delta:
            row += f"  {'—':>8}"
        print(row)

    if remaining:
        best_name = remaining[0]
        best_val = probs[best_name]["champion"]
        print(f" ─── {len(remaining)} other teams — best: {best_name} ({best_val:.3f})")

    print()


def print_delta_summary(probs: dict, prev_probs: dict | None) -> None:
    """Print Biggest Risers / Biggest Fallers top-3 block."""
    if prev_probs is None:
        return

    deltas = []
    for name in probs:
        if name in prev_probs:
            delta = probs[name]["champion"] - prev_probs[name]["champion"]
            deltas.append((name, delta))

    deltas.sort(key=lambda x: x[1], reverse=True)
    risers = deltas[:3]
    fallers = [d for d in reversed(deltas) if d[1] < 0][:3]

    print(_bold_cyan("Biggest Risers"))
    for name, delta in risers:
        print(f"  {_green(f'▲ {name:<16} {delta:+.1%}')}")

    print()
    print(_bold_cyan("Biggest Fallers"))
    for name, delta in fallers:
        print(f"  {_red(f'▼ {name:<16} {delta:+.1%}')}")

    print()


def print_simulation_duration(elapsed_seconds: float) -> None:
    """Print simulation duration in bold green."""
    print(f"{_timestamp()} {_bold_green(f'Re-simulating (50000 runs)... done in {elapsed_seconds:.1f}s')}")


def print_header(
    teams: dict[str, dict],
    bracket: list[dict],
    played: dict[str, dict],
    aliases: dict[str, list[str]],
) -> None:
    """Print startup banner with team/bracket/played/alias counts."""
    print()
    print(_bold_cyan("=" * 60))
    print(_bold_cyan("  WORLD CUP DYNAMIC PREDICTOR — MVP"))
    print(_bold_cyan(f"  Polling API every {POLL_INTERVAL} seconds. Press Ctrl+C to stop."))
    print(_bold_cyan(
        f"  Loaded {len(teams)} teams, {len(bracket)} bracket matches, "
        f"{len(played)} played matches, {len(aliases)} aliases."
    ))
    print(_bold_cyan("=" * 60))
    print()


def print_match_alert(match: dict) -> None:
    """Print highlighted match result block with bold yellow banner."""
    print()
    print(_bold_yellow("=" * 60))
    print(_bold_yellow("  NEW MATCH DETECTED!"))
    team_a = _bold_white(match["team_a"])
    team_b = _bold_white(match["team_b"])
    print(f"  {team_a} {match['home_score']} - {match['away_score']} {team_b}")
    print(f"  Winner: {match['winner']}")
    print(_bold_yellow("=" * 60))


def print_elo_changes(updates: dict[str, dict[str, float]]) -> None:
    """Print Elo rating changes after a match.

    Args:
        updates: {team_name: {"old": float, "new": float}}
    """
    print(f"{_timestamp()} Updating Elo:")
    for team_name in updates:
        old = updates[team_name]["old"]
        new_rating = updates[team_name]["new"]
        delta = int(round(new_rating - old))
        delta_str = f"({'+' if delta >= 0 else ''}{delta})"
        colored_delta = _green(delta_str) if delta >= 0 else _red(delta_str)
        arrow = "→"
        print(f"   {team_name:<12} {int(old)} {arrow} {int(new_rating)}  {colored_delta}")


def print_heartbeat() -> None:
    """Print single-line heartbeat for poll cycles with no new matches."""
    print(f"{_timestamp()} Polling... no new matches.")


def print_auto_refresh() -> None:
    """Print one-liner for hourly auto-refresh simulation."""
    print(f"{_timestamp()} Auto-refresh simulation (no new matches in 1h)")


def print_shutdown_banner(probs: dict[str, dict[str, float]]) -> None:
    """Print final championship probabilities with ALL teams (full table)."""
    print()
    print(_bold_green("=" * 60))
    print(_bold_green("  FINAL CHAMPIONSHIP PROBABILITIES"))
    print(_bold_green("=" * 60))

    sorted_teams = sorted(probs, key=lambda n: probs[n]["champion"], reverse=True)
    print(f"{'':>3} {'Team':<18} {'QF':>6} {'SF':>6} {'FINAL':>8} {'CHAMPION':>8}")
    print("-" * 51)

    for rank, name in enumerate(sorted_teams, 1):
        p = probs[name]
        print(f"{rank:>2}. {name:<18} {p['qf']:.3f} {p['sf']:.3f} {p['final']:.3f} {p['champion']:.3f}")

    print()
    print(_bold_green("State saved. Goodbye."))


def print_error(message: str) -> None:
    """Print bold red error with warning prefix and timestamp to stderr."""
    print(f"{_timestamp()} {_bold_red(f'⚠ {message}')}", file=sys.stderr)
