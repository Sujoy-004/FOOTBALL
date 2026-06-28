# Phase 3: UCL Simulation Orchestration + Display — Research

**Researched:** 2026-06-28
**Domain:** CLI orchestration, dataclass contract design, ANSI terminal display, argparse testing
**Confidence:** HIGH

## Summary

Phase 3 delivers the `ucl-predict` CLI entry point and formatted display of UCL simulation results. The architecture follows a three-layer pattern: CLI orchestration → `SimulationResult` contract → display functions. The CLI (`main.py`) calls `run_monte_carlo()` to get aggregated probabilities, runs one additional iteration for a representative bracket snapshot, assembles a `SimulationResult` dataclass, then delegates to pure display functions. The display layer (D-17) imports zero simulation internals — it reads only the `SimulationResult` contract. This decoupling is the critical architectural investment: Phase 4's BSD data normalizes into the same contract, and display code is unchanged.

Two reference implementations exist in the codebase: Euro's clean 261-line `main.py` (closer pattern) and World Cup's 1567-line `main.py` (over-engineered for UCL's needs). The Euro pattern should be followed: simple `_parse_args()`, `main()`, single `_run_simulation()` call flow. No polling loop, no signal handlers, no config files.

**Primary recommendation:** Use `@dataclass SimulationResult` as the contract between orchestration and display. CLI imports from `simulation.py` and `knockout.py` but display imports only the result contract and formatting functions. The `SimulationResult` carries both aggregated probabilities (from `run_monte_carlo()`) and one representative bracket snapshot (from a single post-MC iteration).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Single-run tool (not polling loop). `ucl-predict` runs the simulation once with given parameters and exits.
- **D-02:** Flags use hyphens: `--iterations`, `--seed`, `--output`. Short forms: `-n`, `-s`, `-o`.
- **D-03:** `--iterations` / `-n` — number of MC iterations (default 10000)
- **D-04:** `--seed` / `-s` — random seed for reproducibility
- **D-05:** `--output` / `-o` — optional JSON output file path. When provided, formatted text still goes to stdout; JSON is written to file in addition.
- **D-06:** Display order follows tournament chronology: Simulation Summary → League Table → Playoff Results → Knockout Bracket → Champion / Qualification Odds
- **D-07:** League table default columns: Position, Team, Pts, GD, GS, Zone (color-coded)
- **D-08:** Knockout bracket displayed as round-by-round match list (not ASCII tree). Playoff ties shown individually with aggregate scores; ET/Pens displayed only when they occur.
- **D-09:** Odds display shows all 36 teams sorted by champion probability descending. Columns: Rank, Team, Champion %, Final %, SF %, QF %.
- **D-10:** ANSI color only — green for top-8 zone, yellow for playoff zone, red for eliminated zone. Bold for headings. No Unicode box-drawing borders.
- **D-11:** Auto-detect terminal color capability. Fall back to plain text automatically. No `--color` flag.
- **D-12:** Section headers with separator lines (`==== League Table ====`), blank lines between sections.
- **D-13:** JSON format for `--output`. Not CSV.
- **D-14:** With `--output`, both stdout (formatted text) and file (JSON) are produced simultaneously.
- **D-15:** Display layer depends on an abstract `SimulationResult` contract (dataclass/protocol), not on `run_monte_carlo()` directly. Phase 4 normalizes BSD data into the same schema.
- **D-16:** The `SimulationResult` schema is owned by the orchestration (Phase 3) layer — neither by simulation engine nor by BSD.
- **D-17:** The display layer consumes only the `SimulationResult` contract. It must not import or depend directly on simulation internals or BSD-specific structures.

### the agent's Discretion
- File/function naming for CLI entry point (`main.py` vs `cli.py` etc.)
- `SimulationResult` dataclass field names and types
- Column widths, ANSI color codes, separator line format
- Whether to use `argparse.FileType` for `--output`
- Table printing implementation (string-format based, no external libs)

### Deferred Ideas (OUT OF SCOPE)
- ASCII tree bracket visualization — future display enhancement, not architectural requirement.
- CSV export — can be generated from JSON without changing the simulation.
- `--quiet` flag — not needed; stdout can be redirected.
- `--verbose` flag for full tiebreaker chain — may add later.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UCLO-01 | CLI entry point (`ucl-predict`) with configurable iterations and seed | Euro `main.py` pattern — 261 lines, flat argparse flags (`-n`, `-s`, `-o`), single-run flow. See CLI Architecture section. |
| UCLO-02 | Display league table with qualification zones after simulation | 6-column table (Pos/Team/Pts/GD/GS/Zone) with ANSI zone coloring. D-10 forbids box-drawing. See League Table Display section. |
| UCLO-03 | Display knockout bracket with matchups and per-team stage probabilities | Round-by-round match list (D-08). Playoff ties with aggregate scores. Bracket from one representative iteration. See Bracket Display section. |
| UCLO-04 | Display champion probabilities, final odds, and top-4 qualification odds | All 36 teams sorted by champion prob descending. 4 columns: Champion %, Final %, SF %, QF %. See Odds Display section. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| CLI argument parsing | Orchestration (CLI) | — | argparse in main.py, validates args before simulation |
| MC simulation invocation | Orchestration (CLI) | — | Calls `run_monte_carlo()` from simulation.py, owns the call boundary |
| Representative bracket sample | Orchestration (CLI) | — | Runs one post-MC iteration to get a single bracket for display |
| SimulationResult assembly | Orchestration (CLI) | — | Assembles the contract from MC output + bracket snapshot |
| Display — League Table | Display (display.py) | — | Pure formatting, consumes SimulationResult only |
| Display — Bracket | Display (display.py) | — | Pure formatting, consumes SimulationResult only |
| Display — Odds | Display (display.py) | — | Pure formatting, consumes SimulationResult only |
| JSON export | Orchestration (CLI) | — | Dumps SimulationResult to JSON when --output given |
| ANSI color detection | Display (display.py) | — | `_supports_color()` pattern from WC output.py |
| Data contract ownership | Orchestration (CLI) | — | SimulationResult is owned here, not in simulation engine (D-16) |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.11+ | Runtime | Existing project standard |
| argparse | stdlib | CLI argument parsing | Established precedent (WC + Euro) |
| json | stdlib | JSON export for `--output` | D-13: JSON format, stdlib |
| dataclasses | stdlib | SimulationResult contract | Zero-dependency, frozen by convention |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| io.StringIO | stdlib | Stdout capture for testing | All display tests — established WC pattern |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| argparse | click / typer | argparse is project standard (WC + Euro), no new dep |
| dataclass | TypedDict / Protocol | dataclass is more natural for instantiation; Protocol adds complexity with no benefit for single-consumer contract |
| hand-rolled table | tabulate / rich | D-10 forbids external libs; hand-rolled gives full control over ANSI formatting |

**Installation:**
```bash
# No new dependencies — stdlib only
```

**Version verification:** All libraries are stdlib — no npm/pip verification needed. Python 3.11+ confirmed via environment.

## Package Legitimacy Audit

> **Not applicable** — Phase 3 installs no external packages. Display and CLI use only Python stdlib (`argparse`, `json`, `dataclasses`, `io`, `sys`). No npm/PyPI verification needed.

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  CLI Entry (ucl-predict)  │
│  competitions/ucl/main.py                                          │
│                                                                     │
│  1. _parse_args(argv) → argparse.Namespace                         │
│  2. Call run_monte_carlo() → MC aggregated results {teams, ...}    │
│  3. Run 1 additional iteration → representative bracket snapshot   │
│  4. Assemble SimulationResult from (2) + (3)                       │
│  5. Feed SimulationResult to display functions                     │
│  6. If --output: json.dump(result) to file                         │
└───────────────────────┬─────────────────────────────────────────────┘
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ Simulation      │ │ Knockout        │ │ Display (D-17)  │
│ (Phase 1 & 2)   │ │ (Phase 2)       │ │ display.py      │
│                 │ │                 │ │                 │
│ run_monte_carlo │ │ playoff ties    │ │ print_summary() │
│ → teams probs   │ │ bracket rounds  │ │ print_table()   │
│ aggregate_mc    │ │ tree results    │ │ print_playoffs()│
│                 │ │                 │ │ print_bracket() │
│                 │ │                 │ │ print_odds()    │
└─────────────────┘ └─────────────────┘ └─────────────────┘
                        ▲                    ▲
                        │    Only reads      │
                        │  SimulationResult  │
                        └─────────┬──────────┘
                                  │
                        ┌─────────────────┐
                        │ SimulationResult │ (dataclass)
                        │                 │
                        │ - snapshot_date │
                        │ - n_iterations  │
                        │ - seed          │
                        │ - teams         │
                        │ - standings     │
                        │ - playoff_ties  │
                        │ - bracket       │
                        │ - stages        │
                        └─────────────────┘
```

### Recommended Project Structure
```
competitions/ucl/
├── main.py              # ucl-predict CLI entry point
├── display.py           # ALL display functions (D-17: no sim imports)
├── result.py            # SimulationResult dataclass
├── src/
│   ├── __init__.py      # Existing — add result + display exports
│   ├── simulation.py    # Existing — frozen
│   ├── knockout.py      # Existing — frozen
│   ├── groups.py        # Existing — frozen
│   └── elo_fetcher.py   # Existing — frozen
├── data/
│   ├── fixtures.json    # Existing
│   ├── playoff_pairings.json  # Existing
│   └── bracket_rules.json     # Existing
├── tests/
│   ├── conftest.py      # Existing — add sample result fixtures
│   ├── test_cli.py      # NEW — argparse tests
│   ├── test_display.py  # NEW — stdout capture tests
│   └── ...
```

### Pattern 1: SimulationResult Contract (D-15, D-16, D-17)
**What:** A `@dataclass` (or `@dataclass(frozen=True)`) that carries ALL data the display layer needs. The display layer imports and consumes ONLY this type — never simulation internals.

**When to use:** Every path from data source to display. Phase 4 creates `SimulationResult` from BSD data. Display code is unchanged between phases.

**Example — Recommended schema:**
```python
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class SimulationResult:
    """Abstract result contract consumed by all display functions.
    
    Phase 3 creates this from run_monte_carlo() output + one extra
    bracket iteration. Phase 4 creates this from BSD-enriched data.
    Display functions never import simulation.py or knockout.py.
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
    stage_order: list[str] = field(default_factory=lambda: [
        "eliminated", "playoff", "r16", "qf", "sf", "final", "champion",
    ])
```
*Source: Derived from `run_monte_carlo()` return signature [VERIFIED: competitions/ucl/src/simulation.py:312-321], `simulate_playoff_round()` return [VERIFIED: competitions/ucl/src/knockout.py:365-369], `simulate_knockout_tree()` return [VERIFIED: competitions/ucl/src/knockout.py:716-721], and D-15/D-16/D-17 architectural constraints [VERIFIED: CONTEXT.md lines 45-48].*

### Pattern 2: Display Function Signature (D-17)
**What:** Each display function takes a `SimulationResult` and optional flags, prints to stdout. Never imports from `simulation.py`, `knockout.py`, or `groups.py`.

**When to use:** Every formatting function. Verifiable at import time — no simulation module imports allowed.

**Example:**
```python
# display.py — ONLY imports from result.py and stdlib
import sys
from competitions.ucl.result import SimulationResult

def print_league_table(result: SimulationResult) -> None:
    """Print 36-row league table with ANSI zone coloring."""
    for entry in result.standings:
        zone_color = _zone_ansi(entry["zone"])  # green/yellow/red
        print(f"{entry['position']:>2}. {entry['team']:<22} "
              f"{entry['pts']:>3} {entry['gd']:>+4} {entry['gs']:>3} "
              f"{zone_color(entry['zone'].upper())}")
```

### Pattern 3: CLI Flow (single-run, no polling)
**What:** `main.py` with flat `_parse_args()`, one-shot execute-and-exit flow. No polling loop, no signal handlers, no config files.

**When to use:** D-01: single-run tool. This is the defining simplicity of Phase 3 vs the complex WC/Euro predictors.

**Example — Recommended flow:**
```python
# competitions/ucl/main.py
def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ucl-predict")
    parser.add_argument("-n", "--iterations", type=int, default=10000)
    parser.add_argument("-s", "--seed", type=int, default=None)
    parser.add_argument("-o", "--output", type=str, default=None)
    return parser.parse_args(argv)

def main() -> None:
    args = _parse_args()
    # 1. Load fixture data
    fixtures = json.load(open(...))
    # 2. Run MC simulation
    mc_result = run_monte_carlo(fixtures, n_iterations=args.iterations, seed=args.seed)
    # 3. Run one extra iteration for bracket snapshot
    #    (same seed -> deterministic first iteration)
    standings = simulate_league_phase(fixtures, elo_ratings, rng, ...)
    playoff = simulate_playoff_round(standings, elo_ratings, rng, ...)
    bracket = build_r16_bracket(standings, playoff, ...)
    tree = simulate_knockout_tree(bracket, elo_ratings, rng)
    stages = track_knockout_stages(standings, tree)
    # 4. Assemble SimulationResult
    result = SimulationResult(
        snapshot_date=mc_result["snapshot_date"],
        n_iterations=mc_result["n_iterations"],
        seed=mc_result["seed"],
        standings=standings,
        teams=mc_result["teams"],
        playoff_ties=playoff["ties"],
        playoff_winners=playoff["winners"],
        bracket_rounds=tree["rounds"],
        bracket_champion=tree["champion"],
        stages=stages,
    )
    # 5. Display all sections in order (D-06)
    print_summary(result)
    print_league_table(result)
    print_playoff_rounds(result)
    print_knockout_bracket(result)
    print_odds(result)
    # 6. JSON export if --output given
    if args.output:
        with open(args.output, "w") as f:
            json.dump(asdict(result), f, indent=2)
```

### Anti-Patterns to Avoid
- **Importing simulation internals in display.py:** Violates D-17. Verifiable: `grep -n "from competitions.ucl.src" display.py` should return zero matches except for `result.py`.
- **Inlining data loading in display functions:** Display functions should receive the `SimulationResult`, not load fixtures/elo from disk.
- **Complex main() flow:** UCL is single-run with 3 flat flags. Don't follow WC's 1567-line pattern with historical catch-up, governance dashlets, blending, etc.
- **Mixing JSON export into display functions:** Keep export in `main.py` as a separate step after display. Don't let `print_*` functions write JSON.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CLI argument validation | Manual sys.argv parsing | argparse [stdlib] | Established project standard, type coercion, help generation, error messages |
| JSON serialization | Manual dict-building | `dataclasses.asdict()` [stdlib] | One-liner conversion of dataclass to JSON-compatible dict |
| Stdout capture for tests | Writing output to temp files | `io.StringIO` [stdlib] | WC test pattern (`_capture()` in test_output.py) is proven clean |

**Key insight:** The entire Phase 3 is purposefully constrained to stdlib. The risk is not in choosing wrong libraries but in violating D-17 (display imports simulation internals). Every import in `display.py` must be reviewed against the rule: "does this touch simulation.py, knockout.py, or groups.py?"

## Common Pitfalls

### Pitfall 1: Display Imports Simulation Internals (D-17 Violation)
**What goes wrong:** A `print_league_table` function imports `compute_swiss_standings` "just to check something." Phase 4 cannot reuse the display without changing it.
**Why it happens:** Convenience — the team data needed for a display column is available in the simulation module.
**How to avoid:** The `SimulationResult` contract must include every field the display needs. If a display function needs to import from `src/`, the contract is incomplete — add the field to `SimulationResult`.
**Warning signs:** Any `from competitions.ucl.src` import in `display.py` except `.result`.

### Pitfall 2: Bracket Display After MC Aggregation (Data Not Available)
**What goes wrong:** The CLI runs Monte Carlo, then tries to display bracket results — but `run_monte_carlo()` returns only aggregated probabilities, not per-iteration bracket states. The bracket data doesn't exist in the return dict.
**Why it happens:** `run_monte_carlo()` was designed for probability aggregation, not display. Its return dict has `teams: {probabilities}` but no `playoff_ties` or `bracket_rounds`.
**How to avoid:** The CLI must run one additional iteration (or capture the last iteration's state) explicitly for bracket display. Use the same seed for deterministic first-iteration results.
**Verification:** `run_monte_carlo()` return signature [VERIFIED: simulation.py:312-321] — no playoff/bracket keys in the top-level dict.

### Pitfall 3: ANSI Codes in --output JSON File
**What goes wrong:** JSON export includes ANSI escape codes because the display functions write directly to the JSON encoder.
**Why it happens:** Shared formatting functions that add ANSI codes before data reaches the JSON serializer.
**How to avoid:** Keep display formatting (ANSI wrapping) as a separate step from data preparation. The `SimulationResult` contains raw numeric data. Display functions wrap with ANSI as they print. JSON export uses `dataclasses.asdict()` on the raw result — no ANSI.
**Verification:** Check that `--output` file contains valid JSON with numeric probabilities, not colored text strings.

### Pitfall 4: JSON Schema Instability (Phase 4 Breaks)
**What goes wrong:** Phase 4 expects `--output` JSON in a specific schema. Phase 3 changes field names during implementation, breaking Phase 4 consumers.
**Why it happens:** No formal JSON schema agreement across phases.
**How to avoid:** The JSON schema for `--output` must be documented and stable at the end of Phase 3. Consider writing a `--json-schema` doc in the Phase 3 audit that Phase 4 references.
**Key fields:** `{snapshot_date, n_iterations, seed, teams: {name: {top_8_prob, champion_prob, stage_*_prob}}, standings: [{position, team, pts, gd, gs, zone}], playoff_ties: {...}, bracket: {rounds: {...}, champion}}`

### Pitfall 5: argparse.FileType for --output
**What goes wrong:** Using `argparse.FileType("w")` for `--output` opens the file handle at parse time, before the simulation runs. If the simulation crashes, the file handle is leaked (or truncated).
**How to avoid:** Accept `--output` as string path (`type=str`), open the file only after successful display. This also makes testing easier (pass a path, not an open file).
**WC/Euro precedent:** Neither WC nor Euro uses `FileType`. Both accept string paths. [VERIFIED: competitions/worldcup/main.py:238-250, competitions/euro/main.py:43-44]

## Code Examples

### Example 1: CLI Argument Parsing
```python
# competitions/ucl/main.py — pattern derived from Euro main.py:36-45
import argparse

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ucl-predict",
        description="UEFA Champions League 2025/26 Monte Carlo predictor.",
    )
    parser.add_argument(
        "-n", "--iterations", type=int, default=10000,
        metavar="N", help="Number of Monte Carlo iterations (default: 10000)",
    )
    parser.add_argument(
        "-s", "--seed", type=int, default=None,
        metavar="N", help="Random seed for reproducible simulation",
    )
    parser.add_argument(
        "-o", "--output", type=str, default=None,
        metavar="FILE", help="Write JSON output to FILE (stdout still prints text)",
    )
    return parser.parse_args(argv)
```
*Source: Pattern established by `competitions/euro/main.py:_parse_args()` [VERIFIED] and `competitions/worldcup/main.py:_parse_args()` [VERIFIED]. D-02 through D-05 specify exact flag names. D-14 specifies dual output behavior.*

### Example 2: ANSI Color Detection and Factory
```python
# competitions/ucl/display.py — pattern from WC output.py:27-48
import sys

NO_COLOR = False  # Set by main.py if stdout is not a TTY

def _supports_color() -> bool:
    return sys.stdout.isatty() and not NO_COLOR

def _ansi(code: str):
    def wrapper(text: str) -> str:
        if _supports_color():
            return f"\033[{code}m{text}\033[0m"
        return text
    return wrapper

_green = _ansi("32")       # top-8 zone
_yellow = _ansi("33")      # playoff zone
_red = _ansi("31")         # eliminated zone
_bold = _ansi("1")         # section headings
```
*Source: Direct pattern from `competitions/worldcup/src/output.py:_supports_color()` and `_ansi()` [VERIFIED: worldcup/src/output.py:27-48]. D-10 specifies zone colors. D-11 specifies auto-detect without --color flag.*

### Example 3: Bracket Display — Round-by-Round Match List
```python
# competitions/ucl/display.py — D-08 bracket format
def print_knockout_bracket(result: SimulationResult) -> None:
    """Print round-by-round match list. NOT an ASCII tree (D-08)."""
    print()
    print("==== Knockout Bracket ====")
    print()
    round_order = ["R16", "QF", "SF", "FINAL"]
    for round_name in round_order:
        matches = result.bracket_rounds.get(round_name, [])
        print(f"--- {round_name} ---")
        for m in matches:
            a, b = m["team_a"], m["team_b"]
            w = m["winner"]
            # For two-legged ties, show aggregate scores
            r = m["result"]
            if r.get("is_final"):
                print(f"  {a} {r['score_a']}-{r['score_b']} {b}")
            else:
                agg_a, agg_b = r["aggregate_a"], r["aggregate_b"]
                et = f" ({r['et_a']}-{r['et_b']} ET)" if r.get("et_played") else ""
                pens = f" ({r['penalty_a']}-{r['penalty_b']} pens)" if r.get("penalties_played") else ""
                print(f"  {a} {agg_a}-{agg_b} agg{b}{et}{pens} {b}")
        print()
```
*Source: D-08 specifies round-by-round match list (not ASCII tree). Playoff tie format from CONTEXT.md specifics line 113-115. `simulate_two_legged_tie()` result keys from [VERIFIED: competitions/ucl/src/knockout.py:197-212].*

### Example 4: Display Test Pattern (Stdout Capture)
```python
# competitions/ucl/tests/test_display.py — pattern from WC test_output.py:70-79
import io
import sys
import pytest
from competitions.ucl.result import SimulationResult
from competitions.ucl.display import print_league_table

def _capture(func, *args, **kwargs) -> str:
    buf = io.StringIO()
    real = sys.stdout
    sys.stdout = buf
    try:
        func(*args, **kwargs)
    finally:
        sys.stdout = real
    return buf.getvalue()

def test_league_table_prints_all_36_teams(sample_result: SimulationResult):
    output = _capture(print_league_table, sample_result)
    lines = [l for l in output.split("\n") if l.strip()]
    assert "1." in output  # First position
    assert "36." in output  # Last position
    assert "Man City" in output  # A team name
```
*Source: WC test pattern `competitions/worldcup/tests/test_output.py:_capture()` [VERIFIED: worldcup/tests/test_output.py:70-79].*

### Example 5: CLI Unit Test
```python
# competitions/ucl/tests/test_cli.py — pattern from WC test_cli.py
from competitions.ucl.main import _parse_args

def test_defaults():
    args = _parse_args([])
    assert args.iterations == 10000
    assert args.seed is None
    assert args.output is None

def test_iterations_flag():
    args = _parse_args(["-n", "5000"])
    assert args.iterations == 5000

def test_seed_flag():
    args = _parse_args(["--seed", "42"])
    assert args.seed == 42

def test_output_flag():
    args = _parse_args(["-o", "results.json"])
    assert args.output == "results.json"

def test_all_flags_together():
    args = _parse_args(["-n", "5000", "--seed", "42", "-o", "out.json"])
    assert args.iterations == 5000
    assert args.seed == 42
    assert args.output == "out.json"

def test_seed_rejects_non_int():
    try:
        _parse_args(["--seed", "abc"])
        assert False, "Should have raised SystemExit"
    except SystemExit:
        pass
```
*Source: WC test pattern `competitions/worldcup/tests/test_cli.py` [VERIFIED: worldcup/tests/test_cli.py:1-108].*

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Display format lives in simulation code | Display depends on abstract `SimulationResult` contract | Phase 3 (D-15) | Phase 4 can change data source without touching display. The contract is the innovation. |

**Deprecated/outdated:**
- World Cup's monolithic 952-line `output.py` — over-engineered for UCL's simpler display needs. UCL display should be modular single-purpose functions.
- World Cup's 1567-line `main.py` — the polling loop, governance, signal blending, multi-league logic, historical catch-up are all irrelevant to UCL's single-run design.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The CLI should run one additional simulation iteration for bracket/playoff display because `run_monte_carlo()` doesn't return per-iteration bracket snapshots | CLI Flow (Pattern 3) | LOW — verified by reading `run_monte_carlo()` return. The return dict lacks playoff/bracket fields. `run_monte_carlo()` return verified at simulation.py:312-321 [VERIFIED]. The alternative is modifying `run_monte_carlo()` to return bracket data, but Phase 2 interfaces are frozen. |
| A2 | No additional conftest.py fixtures needed beyond `sample_mc_output` which already provides a pre-formatted MC output dict | Testing | LOW — `sample_mc_output` fixture exists [VERIFIED: conftest.py:568-619] but only covers teams probabilities. A `sample_result: SimulationResult` fixture will be needed for display tests. This is a minor addition, not a risk. |
| A3 | `argparse` is the right choice (no click, no typer) | CLI Architecture | LOW — established by WC and Euro precedent. No external dep requirements. |

## Open Questions

1. **How should championship probabilities be sorted in the odds table?**
   - What we know: D-09 says "sorted by champion probability descending"
   - Recommendation: Stable sort. In case of ties, sort by team name alphabetically for deterministic output across runs.

2. **Should the representative bracket iteration share the MC seed or use a separate seed?**
   - What we know: The MC loop uses `seed` for all iterations. The representative bracket needs one iteration's results.
   - Recommendation: Use the same seed. `random.Random(seed)` produces the same first iteration every time, so the displayed bracket is consistent with the MC output. The bracket is for illustration, not statistical accuracy.

3. **JSON schema for --output — how deep should playoff/bracket detail go?**
   - What we know: Phase 4 consumers will depend on this schema.
   - Recommendation: Include full playoff tie results (all keys from `simulate_two_legged_tie()` result) and full bracket rounds. Phase 4 will want match-level detail for BSD validation. Don't truncate — the JSON file is not for human reading.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3 | Runtime | ✓ | 3.11+ (project-wide) | — |
| argparse | CLI parsing | ✓ (stdlib) | — | — |
| json | JSON export | ✓ (stdlib) | — | — |
| dataclasses | SimulationResult | ✓ (stdlib, Python 3.7+) | — | — |
| pytest | Testing | ✓ | project-standard | — |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | None — project-wide defaults (no pytest.ini found in UCL). Tests run via `python -m pytest competitions/ucl/tests/`. |
| Quick run command | `python -m pytest competitions/ucl/tests/test_cli.py competitions/ucl/tests/test_display.py -x` |
| Full suite command | `python -m pytest competitions/ucl/tests/ -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UCLO-01 | CLI parses -n/--iterations, -s/--seed, -o/--output | unit | `test_cli.py::test_defaults` etc. | ❌ Wave 0 |
| UCLO-02 | League table displays 36 rows with 6 columns, zone coloring | unit | `test_display.py::test_league_table_*` | ❌ Wave 0 |
| UCLO-03 | Bracket displays round-by-round match list | unit | `test_display.py::test_knockout_bracket_*` | ❌ Wave 0 |
| UCLO-04 | Odds table shows all 36 teams, sorted by champion prob descending | unit | `test_display.py::test_odds_*` | ❌ Wave 0 |
| D-10/D-11 | ANSI codes present when stdout is TTY, absent when piped | unit | `test_display.py::test_ansi_*` | ❌ Wave 0 |
| D-13/D-14 | JSON export has correct schema, stdout still prints text | unit | `test_cli.py::test_output_flag` | ❌ Wave 0 |
| D-17 | display.py does not import from simulation.py/knockout.py | static | `grep -c "from competitions.ucl.src" display.py` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest competitions/ucl/tests/test_cli.py competitions/ucl/tests/test_display.py -x`
- **Per wave merge:** `python -m pytest competitions/ucl/tests/ -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_cli.py` — covers UCLO-01 (argparse tests)
- [ ] `tests/test_display.py` — covers UCLO-02, UCLO-03, UCLO-04 (display output tests)
- [ ] `tests/conftest.py` — add `sample_result: SimulationResult` fixture for display tests
- [ ] Display import audit — add a static check that `display.py` has zero imports from `competitions.ucl.src` (except `.result`)

## Security Domain

> Not applicable — Phase 3 uses only stdlib (no networking, no dependencies, no user input beyond CLI args). Input validation is handled by argparse (type coercion for `--seed`, `--iterations`). File output via `--output` writes to user-specified path — no shell injection risk. JSON output contains only simulation data (no code execution vector).

## Sources

### Primary (HIGH confidence)
- `competitions/ucl/src/simulation.py` — `run_monte_carlo()` return signature [VERIFIED: lines 312-321]
- `competitions/ucl/src/knockout.py` — `simulate_two_legged_tie()` result keys [VERIFIED: lines 197-212], `simulate_playoff_round()` return [VERIFIED: lines 365-369], `simulate_knockout_tree()` return [VERIFIED: lines 716-721], `track_knockout_stages()` return [VERIFIED: lines 724-780]
- `competitions/euro/main.py` — CLI pattern (261 lines, single-run) [VERIFIED: lines 1-262]
- `competitions/worldcup/src/output.py` — ANSI color detection pattern [VERIFIED: lines 27-48]
- `competitions/worldcup/tests/test_cli.py` — argparse test pattern [VERIFIED: lines 1-108]
- `competitions/worldcup/tests/test_output.py` — stdout capture test pattern [VERIFIED: lines 70-79]
- `.planning/phases/03-ucl-orchestration-display/03-CONTEXT.md` — All 17 locked decisions [VERIFIED]

### Secondary (MEDIUM confidence)
- `competitions/ucl/tests/conftest.py` — `sample_mc_output` fixture (existing 3-team mock) [VERIFIED: lines 568-619]
- `competitions/ucl/src/__init__.py` — current exports [VERIFIED: lines 1-41]

### Tertiary (LOW confidence)
- None — all claims verified against actual code or official CONTEXT.md.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all stdlib, established by WC/Euro precedent
- Architecture: HIGH — patterns verified against actual source code (simulation.py:312-321, knockout.py:197-780)
- Pitfalls: HIGH — D-17 violation risk confirmed by reading display.py (currently doesn't exist yet; risk is in creation)
- Testing: HIGH — patterns verified against WC test_cli.py and test_output.py

**Research date:** 2026-06-28
**Valid until:** 2026-07-28 (stable — all findings are stdlib and frozen interfaces)
