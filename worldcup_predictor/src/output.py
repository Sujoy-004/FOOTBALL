"""Console output module for the World Cup predictor.

Pure display functions using raw ANSI escape codes. No external dependencies.
"""

import sys
import time
from typing import Callable


def _supports_color() -> bool:
    """Return True if stdout is a TTY (ANSI codes supported)."""
    return sys.stdout.isatty()


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
