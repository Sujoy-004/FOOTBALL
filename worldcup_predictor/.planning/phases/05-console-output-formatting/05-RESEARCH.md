# Phase 5: Console Output & Formatting — Research

**Researched:** 2026-06-13
**Domain:** Python terminal CLI output formatting (ANSI escape codes, table layout, delta tracking)
**Confidence:** HIGH

## Summary

This phase extracts all display logic from `main.py` into a dedicated `src/output.py` module, implementing a rich terminal output system with ANSI colors, probability deltas, and plain-text fallback. The output system follows the exact block formats defined in `SOTs/UI_UX_Design.md` and refined in the UI-SPEC.md design contract.

**Key research findings:**

1. **No external dependencies needed** — Pure Python 3.10+ stdlib. `sys.stdout.isatty()` for color detection, raw ANSI escape codes in f-strings. The `colorama` decision is correctly at D-05: **not needed**. [VERIFIED: Microsoft docs + Python bug tracker]

2. **Windows Console Host needs initialization** — Python 3.10/3.11 does NOT auto-enable `ENABLE_VIRTUAL_TERMINAL_PROCESSING` on the legacy Windows Console Host (conhost.exe). Windows Terminal and VS Code integrated terminal work without initialization. A one-time `os.system('')` call at startup suffices for legacy console support. [VERIFIED: python/cpython#73245, python/cpython#40134, Microsoft Console VT docs] **This is a correction to the assumption in CONTEXT.md D-05 that "Python 3.10+ on Windows 10+ supports ANSI natively" — the OS supports it, but Python 3.10/3.11 does not enable the bit.**

3. **Probability data shape** is `dict[str, dict[str, float]]` with keys `qf, sf, final, champion` — confirmed from `run_simulation()` return type in simulation.py. Delta calculation: `probs[team]["champion"] - prev_probs[team]["champion"]`.

4. **Existing `_print_probability_table`** in main.py prints ALL 32 teams. Phase 5 needs two variants: top-5 with deltas (normal updates) and full-table without deltas (shutdown).

5. **Two delta display formats coexist:** Inline table deltas use `:+.3f` decimal (e.g., `+0.003`), but the risers/fallers block uses `:.1%` percentage (e.g., `+3.2%`). This is intentional per UI-SPEC — the summary block is for quick scanning.

**Primary recommendation:** Create `src/output.py` with the 8 public functions + private ANSI helpers specified in UI-SPEC. Extract the existing table logic from `main.py`. Wire deltas through main.py's `_run_iteration()` by storing `prev_probs` between calls. Test via visual inspection (manual) and subprocess capture tests (automated).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Single `src/output.py` module containing all display functions. No splits. Functions: `print_header()`, `print_probability_table(probs, prev_probs)`, `print_match_alert(match)`, `print_elo_changes(updates)`, `print_heartbeat()`, `print_delta_summary(risers, fallers)`, `print_shutdown_banner(probs)`, color/style helpers (ANSI wrappers). Pure functions — no classes.
- **D-02:** In-memory only delta tracking. Previous probabilities dict stored in main.py's iteration state. Not persisted to JSON.
- **D-03:** Top 5 teams by championship probability, showing QF/SF/FINAL/CHAMPION columns with inline delta per row. Followed by remaining-teams one-liner. Timestamps on each table block.
- **D-04:** Separate Biggest Risers / Biggest Fallers block (top 3 each) with champion% deltas. Not all 32 teams and not threshold-based.
- **D-05:** Raw ANSI escape codes. No colorama dependency. Color scheme per UI_UX_Design.md §4. Fallback via `sys.stdout.isatty()`. Explicit `--no-color` is Phase 6 scope.
- **D-06:** Append new tables below previous output (keep scrollback history). Do NOT clear screen or redraw in-place.

### the agent's Discretion
- Exact ANSI escape code wrappers in output.py (helper functions like `_green(text)`, `_bold_yellow(text)`)
- Whether risers/fallers print inline in the table or as a separate block below it
- Exact format of the remaining-teams one-liner
- Heartbeat format and frequency of heartbeat lines
- Whether to include simulation duration in output (e.g., "Re-simulating (50000 runs)... done in 0.8s")

### Deferred Ideas (OUT OF SCOPE)
- **Phase 6 concern:** `--no-color` flag to explicitly disable ANSI
- **Phase 6 concern:** `--once` flag for single run
- **v1.1 concern:** Progress bar during Monte Carlo simulation using `tqdm`
- **v1.2 concern:** Log output to file via `--log` flag
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UI-01 | System outputs championship probabilities for top 5 teams as formatted percentages in the console with timestamps | Top-5 table format defined in D-03. `print_probability_table()` implements sorted top-5 filtering from 32-team `probs` dict. Timestamps use ISO 8601 `[%Y-%m-%d %H:%M:%S]` format. |
| UI-02 | System displays probability deltas (▲ increase, ▼ decrease) showing how each team's odds changed since the last simulation | Delta tracking via `prev_probs` dict in main.py loop scope (D-02). Inline deltas in top-5 table + separate risers/fallers block (D-04). Delta = `probs[team]["champion"] - prev_probs[team]["champion"]`. |
| UI-03 | System uses colored console output (ANSI) for readability with plain-text fallback for unsupported terminals | Raw ANSI escape codes (D-05). `sys.stdout.isatty()` fallback detection. `os.system('')` for Windows Console Host init. Color scheme per UI_UX_Design.md §4. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| ANSI color application | src/output.py | — | All escape codes encapsulated in output module helpers |
| Color feature detection | src/output.py | — | `sys.stdout.isatty()` check at module level or first print |
| Windows ANSI init | main.py (startup) | — | `os.system('')` called once before any output.py calls |
| Delta tracking state | main.py (loop scope) | — | D-02: prev_probs stored in `_run_iteration()` caller scope |
| Table formatting logic | src/output.py | — | All print functions are pure data-in/print-out |
| Top-5 filtering | src/output.py | — | Sorted by champion prob descending, take first 5 |
| Risers/fallers calculation | src/output.py | — | Delta sorting internal to `print_delta_summary()` |
| Shutdown banner logic | src/output.py | — | `print_shutdown_banner()` called from main.py signal handler |
| Timestamp generation | src/output.py | — | `time.strftime('%Y-%m-%d %H:%M:%S')` in each print function |
| Bold/tty detection | src/output.py | — | `_supports_color()` or equivalent private function |

## Standard Stack

### Core (all stdlib — no external packages)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `sys.stdout.isatty()` | stdlib | Detect piped/redirected output | Built-in, cross-platform, zero dep |
| `os.system('')` | stdlib | Enable ANSI on Windows Console Host | 8-char workaround for Python 3.10/3.11 on legacy conhost.exe |
| `time.strftime()` | stdlib | ISO 8601 timestamp generation | Stdlib datetime formatting |
| `print()` | stdlib | All output to stdout | Project convention per CONVENTIONS.md |
| `sys.platform` | stdlib | Platform detection for Windows-specific init | Built-in, no extra deps |

### Ecosystem Verification
All capabilities come from Python 3.10+ stdlib. No `pip install` required. The `colorama` package was explicitly rejected at D-05 (user-confirmed decision).

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Raw ANSI codes | `colorama` | colorama adds dependency for `init(autoreset=True)` + `Fore.GREEN` wrappers. But Python 3.10+ on Win10+ has native support. More complex to write but zero deps. |
| Raw ANSI codes | `rich` library | Massive dependency for simple color output. Rich is for full terminal apps with tables/progress bars. Overkill for MVP. |
| `print()` | `logging` module | CONVENTIONS.md explicitly says `print()` for MVP. Logging module adds complexity without benefit for console-only tool. |
| `os.system('')` | `ctypes` approach | ctypes is more robust but more code. `os.system('')` is 8 chars and works reliably on all Windows 10+ (known stable cmd.exe quirk). |

**Installation:** None required for this phase. All dependencies are Python 3.10+ stdlib.

## Package Legitimacy Audit

> **No external packages are installed in this phase.** All capabilities use Python 3.10+ stdlib. The `colorama` and `rich` packages were evaluated and explicitly rejected at D-05. No npm, no PyPI installs.

| Package | Registry | slopcheck | Disposition | Rationale |
|---------|----------|-----------|-------------|-----------|
| — | — | — | N/A | Pure stdlib phase — no external packages |

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         main.py (_run_iteration)                 │
│                                                                   │
│  prev_probs = None  (initial call)                                │
│  ...                                                              │
│  probs = run_simulation(teams, bracket, played, iterations=50000) │
│  prev_probs = None  → output.print_probability_table(probs)       │
│                        (no delta column, no risers/fallers)       │
│  ...                                                              │
│  next iteration:                                                  │
│  probs = run_simulation(...)                                      │
│  prev_probs exists → output.print_probability_table(probs,        │
│ ──────────────────────┬──────────── prev_probs)                   │
│                        │  (with delta column + risers/fallers)    │
│                        ▼                                          │
│  prev_probs = probs   (store for next iteration)                  │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                      src/output.py                               │
│                                                                   │
│  ┌────────────────────────────────────────────────────────┐      │
│  │                   isatty()?                            │      │
│  │                  /          \                          │      │
│  │            YES (tty)     NO (piped)                    │      │
│  │               │              │                          │      │
│  │          ANSI codes     Plain text                     │      │
│  │          + symbols      + symbols                      │      │
│  │          ▲ ▼ ⚠          ▲ ▼ ⚠                         │      │
│  └────────────────────────────────────────────────────────┘      │
│                                                                   │
│  print_header()          → bold cyan banner + seed counts        │
│  print_heartbeat()       → dim gray timestamp + message          │
│  print_match_alert()     → bold yellow block + bold white teams  │
│  print_elo_changes()     → green/red elo deltas                  │
│  print_probability_table() → top-5 with deltas or full list      │
│  print_delta_summary()   → risers ▲ / fallers ▼ blocks           │
│  print_shutdown_banner() → final full table + "Goodbye"          │
│                                                                   │
│  Helpers (private):                                               │
│  _dim(), _bold_cyan(), _bold_yellow(), _green(), _red(),          │
│  _bold_red(), _bold_green(), _bold_white()                        │
│  _supports_color() → sys.stdout.isatty() check                    │
│  _timestamp() → f"[{time.strftime('%Y-%m-%d %H:%M:%S')}]"        │
└─────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure

No structural changes. Single new file created:

```
worldcup_predictor/
├── src/
│   ├── __init__.py
│   ├── output.py          # NEW — all display functions extracted from main.py
│   ├── state.py
│   ├── elo.py
│   ├── simulation.py
│   ├── fetcher.py
│   └── constants.py
├── main.py                # EDITED — import output.py, wire up calls, remove _print_probability_table
├── tests/
│   ├── test_output.py     # NEW — subprocess capture tests for output formatting
│   └── ...
```

### Pattern 1: Pure Print Functions (No Side Effects Beyond stdout)

**What:** Each public function in output.py takes typed data, formats it, and calls `print()`. No returns, no state, no I/O. Private helpers handle ANSI wrapping and color detection.

**When to use:** All output functions in this module. Matches MVP convention of no classes, no OOP.

**Example:** [VERIFIED: existing main.py `_print_probability_table` pattern + CONVENTIONS.md]

```python
def print_probability_table(
    probs: dict[str, dict[str, float]],
    prev_probs: dict[str, dict[str, float]] | None = None,
) -> None:
    """Print top-5 probability table with optional deltas."""
    sorted_teams = sorted(probs, key=lambda n: probs[n]["champion"], reverse=True)
    top5 = sorted_teams[:5]
    remaining = sorted_teams[5:]

    # Header row
    header = f"{'':>3} {'Team':<18} {'QF':>6} {'SF':>6} {'FINAL':>8} {'CHAMPION':>8}"
    if prev_probs is not None:
        header += f"  {'Delta':>8}"
    print(_bold_cyan(header))
    print(_bold_cyan("-" * (51 + (9 if prev_probs else 0))))

    # Top 5 rows
    for rank, name in enumerate(top5, 1):
        p = probs[name]
        line = f"{rank:>2}. {name:<18} {p['qf']:.3f} {p['sf']:.3f} {p['final']:.3f} {p['champion']:.3f}"
        if prev_probs is not None:
            delta = p["champion"] - prev_probs[name]["champion"]
            symbol = "▲" if delta >= 0 else "▼"
            delta_color = _green if delta >= 0 else _red
            line += f"  {delta_color(f'{symbol} {delta:+.3f}')}"
        print(line)

    # Remaining teams one-liner
    if remaining:
        best = max(remaining, key=lambda n: probs[n]["champion"])
        print(f" ─── {len(remaining)} other teams — best: {best} ({probs[best]['champion']:.3f})")
    print()
```

### Pattern 2: Delta Sorting for Risers/Fallers

**What:** Sort all 32 teams by `champion` delta, extract top 3 risers and bottom 3 fallers. Display percentage format (not decimal) in dedicated block.

**When to use:** After `prev_probs` is available (every call except first). [VERIFIED: CONTEXT.md D-04]

```python
def _compute_deltas(
    probs: dict[str, dict[str, float]],
    prev_probs: dict[str, dict[str, float]],
) -> list[tuple[str, float]]:
    """Return list of (team_name, champion_delta) for all teams."""
    return [
        (name, probs[name]["champion"] - prev_probs[name]["champion"])
        for name in probs
    ]

def print_delta_summary(
    probs: dict[str, dict[str, float]],
    prev_probs: dict[str, dict[str, float]],
) -> None:
    """Print biggest risers and fallers blocks."""
    deltas = _compute_deltas(probs, prev_probs)
    deltas.sort(key=lambda x: x[1], reverse=True)
    risers = deltas[:3]
    fallers = deltas[-3:]
    fallers.reverse()  # Most negative first

    print(_bold_cyan("Biggest Risers"))
    for name, delta in risers:
        print(f"  {_green(f'▲ {name:<16} {delta:+.1%}')}")

    print()
    print(_bold_cyan("Biggest Fallers"))
    for name, delta in fallers:
        print(f"  {_red(f'▼ {name:<16} {delta:+.1%}')}")
    print()
```

### Anti-Patterns to Avoid

- **DO NOT use `curses` or `colorama`** — The decision is locked at D-05. Raw ANSI codes only.
- **DO NOT clear screen or use cursor-up sequences** — D-06 locks append-only scrollback behavior.
- **DO NOT log errors via output.py** — Error messages originate from main.py or fetcher.py contexts, printed naturally (per UI-SPEC §6.10). output.py handles structured display only.
- **DO NOT mix delta formats** — Inline table deltas use `:.3f` decimal (e.g., `+0.003`). Risers/fallers use `:.1%` percentage (e.g., `+3.2%`). These are intentionally different per UI-SPEC.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ANSI color wrappers | Custom ctypes for Windows ansi init per call | `os.system('')` once at startup | The cmd.exe quirk is stable across all Win10+ versions. 8 chars vs 20+ lines of ctypes. |
| Terminal color detection | Custom terminfo parsing | `sys.stdout.isatty()` | Built-in, cross-platform, zero-config covers all needed cases. |
| Signal handling for shutdown | Custom signal handler registration | `signal.signal(SIGINT, handler)` in main.py | Already implemented in Phase 4. output.py just provides the banner. |
| Probability table from scratch | Hand-building string tables | Extracted `_print_probability_table` from main.py | Existing code already does 90% of the work. Just add top-5 filter and delta column. |

**Key insight:** This phase is almost entirely about **extracting and enhancing** existing code, not building new logic. The table format, data structures, and control flow all exist in Phase 4's main.py. The value is in the extraction to output.py and the addition of ANSI colors, delta columns, and risers/fallers.

## Common Pitfalls

### Pitfall 1: Windows Console Host Does Not Show ANSI Colors
**What goes wrong:** ANSI escape codes appear as raw text like `[31mtest[0m` in cmd.exe or PowerShell on Windows 10.
**Why it happens:** Python 3.10/3.11 does NOT call `SetConsoleMode(ENABLE_VIRTUAL_TERMINAL_PROCESSING)` on the legacy Windows Console Host (conhost.exe). Windows Terminal and VS Code terminal do not have this issue.
**How to avoid:** Add `os.system('')` at the very top of `main()` (before any output.py calls). This exploits a cmd.exe quirk where it accidentally enables VT processing for the parent console, then fails to disable it on exit. Works on all Windows 10+ versions. For Python 3.12+ this is no longer needed. [VERIFIED: python/cpython#73245, python/cpython#40134]
**Warning signs:** ANSI codes work in VS Code terminal but not in cmd.exe.

### Pitfall 2: First-Call Edge Case for prev_probs
**What goes wrong:** The initial simulation call has no `prev_probs`, so delta columns and risers/fallers should not appear. But the code path is shared.
**Why it happens:** `print_probability_table()` and `print_delta_summary()` both branch on `prev_probs is not None`.
**How to avoid:** Default `prev_probs = None` in the function signature. Check `if prev_probs is not None` before showing delta column or calling `print_delta_summary()`. The first call always passes no `prev_probs`.
**Warning signs:** Risers/fallers block appears on first startup with nonsensical values.

### Pitfall 3: Delta Display Format Confusion (Decimal vs Percentage)
**What goes wrong:** Inline table deltas show as "▲ +0.003" (decimal) but risers/fallers show as "▲ +3.2%" (percentage). Developer uses wrong format in one place.
**Why it happens:** Two different visual contexts — table is data-dense and precise, summary block is for quick scanning.
**How to avoid:** Inline deltas: `f"{symbol} {delta:+.3f}"`. Risers/fallers: `f"{symbol} {name:<16} {delta:+.1%}"`. Document both in comments.
**Warning signs:** Risers/fallers show "0.032" instead of "3.2%".

### Pitfall 4: Unicode Symbol Rendering on Windows
**What goes wrong:** ▲ (U+25B2), ▼ (U+25BC), ⚠ (U+26A0) render as boxes or question marks in legacy cmd.exe.
**Why it happens:** Legacy Console Host uses raster fonts that don't include Unicode symbols. Windows Terminal and VS Code terminal render them correctly.
**How to avoid:** This is a terminal limitation, not a code issue. Symbols degrade to plain text alternatives automatically if the terminal can't render them. Fallback text (▲ → "[up]" etc.) is not needed for MVP — the user explicitly chose Unicode symbols in UI-SPEC and the project targets modern terminals.
**Warning signs:** Users on Windows 7 or legacy cmd.exe with raster fonts report missing symbols.

## Code Examples

Verified patterns from official sources:

### ANSI Helper Wrappers

```python
"""src/output.py — Console display functions with ANSI color support."""

import sys
import time
from typing import Callable

# ─── ANSI color helpers (private) ───────────────────────────────────

def _supports_color() -> bool:
    """Check if stdout supports ANSI escape codes."""
    return sys.stdout.isatty()

def _ansi(code: str) -> Callable[[str], str]:
    """Create an ANSI wrapper function."""
    def wrapper(text: str) -> str:
        if _supports_color():
            return f"\033[{code}m{text}\033[0m"
        return text
    return wrapper

# Color functions — each is a callable that wraps text in ANSI codes
_dim = _ansi("2")
_bold_cyan = _ansi("1;36")
_bold_yellow = _ansi("1;33")
_green = _ansi("32")
_red = _ansi("31")
_bold_red = _ansi("1;31")
_bold_green = _ansi("1;32")
_bold_white = _ansi("1;37")

def _timestamp() -> str:
    """Return dim-gray timestamp string."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    return _dim(f"[{ts}]")
```

Source: [VERIFIED: ANSI escape code standards + UI_UX_Design.md §4 color table]

### Shutdown Banner (Full Table, No Deltas)

```python
def print_shutdown_banner(probs: dict[str, dict[str, float]]) -> None:
    """Print final championship probabilities + shutdown message.

    Shows ALL teams (not top-5). No delta column. Green banner.
    """
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
```

Source: [VERIFIED: UI-SPEC.md §6.8 — exact output format confirmed]

### Match Alert Block

```python
def print_match_alert(match: dict) -> None:
    """Print highlighted match result block.

    match format: {"team_a": str, "team_b": str, "home_score": int,
                   "away_score": int, "winner": str}
    """
    print()
    print(_bold_yellow("=" * 60))
    print(_bold_yellow("  NEW MATCH DETECTED!"))
    team_a = _bold_white(match["team_a"])
    team_b = _bold_white(match["team_b"])
    print(f"  {team_a} {match['home_score']} - {match['away_score']} {team_b}")
    print(f"  Winner: {match['winner']}")
    print(_bold_yellow("=" * 60))
```

Source: [VERIFIED: UI-SPEC.md §6.4 — match alert block format]

### main.py Wiring (Delta State Example)

```python
# In main.py _run_iteration:
def _run_iteration(teams, bracket, played, api_key, aliases,
                   last_sim_time, last_request_time, prev_probs=None):
    """...existing logic..."""
    probs = run_simulation(teams, bracket, played, iterations=50000)

    # Print probability table with deltas
    output.print_probability_table(probs, prev_probs)

    # Print risers/fallers (only if we have previous data)
    if prev_probs is not None:
        output.print_delta_summary(probs, prev_probs)

    return time.time(), last_request_time, probs

# In main() loop:
prev_probs = None
# First call
last_sim_time, last_request_time, prev_probs = _run_iteration(
    teams, bracket, played, api_key, aliases,
    last_sim_time, last_request_time, prev_probs
)

# Subsequent calls
while _running:
    # ...
    last_sim_time, last_request_time, prev_probs = _run_iteration(
        teams, bracket, played, api_key, aliases,
        last_sim_time, last_request_time, prev_probs
    )
```

Source: [VERIFIED: CONTEXT.md code_context section — integration points confirmed]

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `colorama.init()` on Windows | `os.system('')` + raw ANSI | Python 3.10 era | Removes dependency. `os.system('')` is ~1000x simpler. |
| `_print_probability_table` in main.py | `output.print_probability_table()` | This phase | Clean separation of display logic from control flow. Enables testability. |
| All 32 teams printed every time | Top 5 + remaining summary | This phase | Dramatically improves scannability per UI-01 spec. |
| No delta tracking | Inline deltas + risers/fallers | This phase | Core UX value: "how did odds change since last poll?" per UI-02. |
| Plain text only | ANSI colors + plain text fallback | This phase | Visual hierarchy per UI-03. Color is additive, not required. |

**Outdated approaches (not used):**
- `colorama` init: Python 3.10+ on Windows 10+ supports ANSI natively. No longer needed. [VERIFIED: Microsoft Documentation]
- `curses`/`rich`/`blessed` full terminal control: Overkill for append-only output. Phase explicitly wants scrollback timeline (D-06).
- Percentage display for all probability values: PRD examples show decimal fractions matching simulation output. Only risers/fallers use percentage.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `os.system('')` enables ANSI on all Windows 10+ conhost.exe versions | Standard Stack | Low — this quirk has been stable since Windows 10 v1607 and is documented in 3 CPython issues. If it fails, colors degrade gracefully to plain text fallback. |
| A2 | All project team names fit within 18-character column width | Architecture / Column Widths | Low — max team name in WC is ~14 chars. 18 chars provides 4-char padding. Truncation visible if exceeded. |
| A3 | Unicode symbols ▲ ▼ ⚠ render correctly on target terminals | UI-SPEC §1 | Low — Windows Terminal, VS Code terminal, and modern macOS/Linux terminals all support Unicode. Legacy cmd.exe with raster fonts may show boxes, but the app still functions. |
| A4 | `sys.stdout.isatty()` correctly distinguishes piped vs interactive output | Architecture | HIGH — This is the standard Python approach and is widely tested. Only edge case is powershell ISE (not relevant for Python CLI). |
| A5 | Simulation output dict always contains all 32 teams | CODECONTEXT | HIGH — Verified from simulation.py code: iterates over `teams` keys. All teams always present in result. |

**If this table is empty:** Only assumptions are A1-A5, all LOW risk with graceful fallbacks.

## Open Questions (RESOLVED)

1. **Does auto-refresh (hourly re-sim with no new matches) show probability table with deltas?**
   **RESOLVED:** Show deltas — the hourly re-sim still runs `run_simulation()` which produces probabilities, and `prev_probs` from the last cycle is available. The delta reflects Monte Carlo variance. Auto-refresh label distinguishes it from match-triggered updates. (Implemented by Plan 05-01 Task 2's `print_probability_table(probs, prev_probs)` — passes both regardless of trigger source.)

2. **Should errors be routed through output.py?**
   **RESOLVED:** Export a `print_error(message)` helper from output.py that wraps the `⚠` prefix + bold red color + message + prompt. This keeps ANSI code out of main.py. (Implemented by Plan 05-02 Task 2 as `print_error()` in output.py.)

3. **What is the exact `match` dict format expected by `print_match_alert()` and `print_elo_changes()`?**
   **RESOLVED:** `print_elo_changes(updates: dict[str, dict[str, float]])` where updates is `{team_name: {"old": float, "new": float}}`. Match alerts receive the match dict with `team_a`, `team_b`, `winner`, `home_score`, `away_score` keys. (Implemented by Plan 05-02 Tasks 1 and 2 in output.py signatures.)

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.10+ | All code | ✓ | 3.11.8 | — |
| pytest | Testing | ✓ | 9.0.2 | — |
| requests | API calls (main.py runtime, not output.py) | ✓ | — | Not needed for output phase |
| Terminal / TTY | ANSI color support | ✓ | — | `sys.stdout.isatty()` fallback |

**Missing dependencies with no fallback:** None — this phase requires zero external packages.

**Missing dependencies with fallback:** None — all stdlib.

## Validation Architecture

> `workflow.nyquist_validation` is enabled. Including this section.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | None (default pytest discovery) |
| Quick run command | `pytest tests/test_output.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UI-01 | Top-5 table output with timestamps | snapshot/subprocess | `pytest tests/test_output.py::test_top5_table` | ❌ Wave 0 |
| UI-01 | Remaining teams one-liner | snapshot | `pytest tests/test_output.py::test_remaining_teams` | ❌ Wave 0 |
| UI-02 | Delta symbol direction (▲/▼) matches sign | unit | `pytest tests/test_output.py::test_delta_symbol` | ❌ Wave 0 |
| UI-02 | Risers/fallers top-3 each | snapshot | `pytest tests/test_output.py::test_delta_summary` | ❌ Wave 0 |
| UI-02 | First call: no deltas when prev_probs is None | unit | `pytest tests/test_output.py::test_first_call_no_deltas` | ❌ Wave 0 |
| UI-03 | ANSI codes stripped when stdout not a tty | unit | `pytest tests/test_output.py::test_no_ansi_when_piped` | ❌ Wave 0 |
| UI-03 | Plain text fallback preserves symbols (▲▼⚠) | unit | `pytest tests/test_output.py::test_symbols_preserved` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_output.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_output.py` — new file for output module testing
- [ ] `tests/conftest.py` — already exists with `sample_teams`, `sample_bracket`, `sample_played` fixtures (reusable for output tests)

### Output Test Pattern Example

```python
"""Tests for src/output.py — console display functions."""

import sys
from unittest.mock import patch

from src.output import (
    print_probability_table,
    print_delta_summary,
    _supports_color,
    _green,
)


def test_no_ansi_when_piped():
    """ANSI escape codes should not appear when stdout is piped."""
    probs = {"Argentina": {"qf": 1.0, "sf": 1.0, "final": 1.0, "champion": 1.0}}
    prev_probs = {"Argentina": {"qf": 1.0, "sf": 1.0, "final": 1.0, "champion": 0.9}}

    with patch("src.output._supports_color", return_value=False):
        # Capture print output
        from io import StringIO
        captured = StringIO()
        real_stdout = sys.stdout
        sys.stdout = captured
        try:
            print_probability_table(probs, prev_probs)
        finally:
            sys.stdout = real_stdout

        output = captured.getvalue()
        assert "\033[" not in output, "ANSI codes leaked in piped output"
        assert "▲" in output, "Symbols should still appear"
```

## Security Domain

> This phase has ZERO security-relevant code. No authentication, no input handling, no data validation, no network I/O. All functions are `def f(data) -> None: print(...)` — pure display logic.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | no | All data originates from in-memory simulation results, not user input |
| V6 Cryptography | no | — |

### Known Threat Patterns

None. This phase writes to stdout only. The only "security" concern is not leaking ANSI escape codes into piped output files — handled by `sys.stdout.isatty()` fallback.

## Sources

### Primary (HIGH confidence)
- **CONTEXT.md D-01 through D-06** — All locked decisions for this phase
- **UI-SPEC.md** — Complete design contract with exact output format for every block
- **`main.py`** — Existing `_print_probability_table()` and `_run_iteration()` code to extract
- **`simulation.py`** — `run_simulation()` return type `dict[str, dict[str, float]]`
- **`SOTs/UI_UX_Design.md` §4** — Color scheme and ANSI guidelines
- **`SOTs/UI_UX_Design.md` §3** — Console output format examples
- **CONVENTIONS.md** — Project conventions (no classes, pure functions, timestamps)
- **`os.system('')` for Windows ANSI**: [Microsoft Docs: Console Virtual Terminal Sequences](https://learn.microsoft.com/en-us/windows/console/console-virtual-terminal-sequences), [CPython issue #73245](https://github.com/python/cpython/issues/73245), [CPython issue #40134](https://bugs.python.org/issue40134)

### Secondary (MEDIUM confidence)
- **`SOTs/PRD.md` §6** — FR6 defines UI-01 acceptance criteria
- **`SOTs/TRD.md` §5.3** — Output specification reference
- **`SOTs/Backend_Schema.md` §5.5** — Planned output.py function signatures

### Tertiary (LOW confidence)
- None — all claims verified via official docs or codebase reading.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Pure stdlib. All patterns confirmed via codebase reading.
- Architecture: HIGH — All integration points verified in existing main.py code.
- Pitfalls: HIGH — Windows ANSI init issue verified via CPython bug tracker and Microsoft docs.

**Research date:** 2026-06-13
**Valid until:** Stable — ANSI escape codes are a 50-year-old standard. Windows behavior hasn't changed since Win10 v1607. No expiration concerns.
