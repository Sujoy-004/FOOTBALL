# Phase 3: UCL Simulation Orchestration + Display — Context

**Gathered:** 2026-06-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver the `ucl-predict` CLI entry point and formatted display for UCL simulation results — league table with qualification zone highlighting, playoff tie results, knockout bracket matchups, and champion/qualification odds. The display layer depends on an abstract result contract rather than directly on the simulation engine, so Phase 4 (BSD validation) can inject enriched data without changing presentation code.

This phase extends Phase 2's frozen interfaces: `run_monte_carlo()`, `aggregate_mc_results()`, and the knockout pipeline are consumed through a `SimulationResult` schema, not called directly by display code.

</domain>

<decisions>
## Implementation Decisions

### CLI Design
- **D-01:** Single-run tool (not polling loop). `ucl-predict` runs the simulation once with given parameters and exits. No live match data to react to — unlike wc-predict's live polling loop.
- **D-02:** Flags use hyphens: `--iterations`, `--seed`, `--output`. Short forms: `-n`, `-s`, `-o`.
- **D-03:** `--iterations` / `-n` — number of MC iterations (default 10000)
- **D-04:** `--seed` / `-s` — random seed for reproducibility
- **D-05:** `--output` / `-o` — optional JSON output file path. When provided, formatted text still goes to stdout; JSON is written to file in addition.

### Output Structure
- **D-06:** Display order follows tournament chronology:
  1. Simulation Summary (iterations, seed, snapshot date)
  2. League Table (36 rows, positions 1-36)
  3. Playoff Results (8 ties, aggregate scores, advancing winners)
  4. Knockout Bracket (R16 → QF → SF → Final, round-by-round match list)
  5. Champion / Qualification Odds (all 36 teams)
- **D-07:** League table default columns: Position, Team, Pts, GD, GS, Zone (color-coded). The full tiebreaker information remains available internally and may be exposed by a future diagnostic mode.
- **D-08:** Knockout bracket displayed as round-by-round match list (not ASCII tree). Playoff ties shown individually with aggregate scores; ET/Pens displayed only when they occur. ASCII tree considered a future enhancement.
- **D-09:** Odds display shows all 36 teams sorted by champion probability descending. Columns: Rank, Team, Champion %, Final %, SF %, QF %. Full 7-stage probabilities (eliminated → champion) available in JSON export only.

### Display Formatting
- **D-10:** ANSI color only — green for top-8 zone, yellow for playoff zone, red for eliminated zone. Bold for headings. No Unicode box-drawing borders.
- **D-11:** Auto-detect terminal color capability using the existing project pattern. Fall back to plain text automatically. No `--color` flag unless future requirement demands it.
- **D-12:** Section headers with separator lines (`==== League Table ====`), blank lines between sections.

### Data Export
- **D-13:** JSON format for `--output`. Not CSV. CSV can be generated from JSON without changing the simulation.
- **D-14:** With `--output`, both stdout (formatted text) and file (JSON) are produced simultaneously. Stdout is never suppressed by output flags — users redirect with `> /dev/null` if they want silence.

### Architecture — Display Layer Abstraction
- **D-15:** Display layer depends on an abstract `SimulationResult` contract (dataclass/protocol), not on `run_monte_carlo()` directly. Phase 3 creates it from simulation output. Phase 4 normalizes BSD-enriched data into the same schema. Display code is unchanged between phases.
- **D-16:** The `SimulationResult` schema is owned by the orchestration (Phase 3) layer — neither by the simulation engine nor by BSD. BSD data normalizes into this contract before reaching the display.
- **D-17:** The display layer consumes only the `SimulationResult` contract. It must not import or depend directly on simulation internals or BSD-specific structures.

### agent's Discretion
- File/function naming for CLI entry point (`main.py` vs `cli.py` etc.)
- `SimulationResult` dataclass field names and types (must capture all output fields display needs)
- Column widths, ANSI color codes, separator line format
- Whether to use `argparse.FileType` for `--output`
- Table printing implementation (string-format based, no external libs)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/REQUIREMENTS.md` — UCLO-01 through UCLO-04 (orchestration + display requirements)
- `.planning/ROADMAP.md` — Phase 3 section with success criteria

### Phase 2 (frozen interfaces — consumed by Phase 3)
- `competitions/ucl/src/simulation.py` — `run_monte_carlo()` return dict schema, `STAGE_ORDER`, `STAGE_TO_VALUE`
- `competitions/ucl/src/knockout.py` — `simulate_playoff_round()`, `build_r16_bracket()`, `simulate_knockout_tree()`, `track_knockout_stages()`
- `.planning/phases/02-ucl-knockout-phase/02-CONTEXT.md` — D-01 through D-13 (frozen decisions guiding what data is available)
- `.planning/phases/02-ucl-knockout-phase/02-AUDIT.md` — Public interface freeze; note Final match schema difference (no `leg`/`aggregate` keys)

### Existing CLI Patterns (reference only — UCL is simpler)
- `competitions/worldcup/main.py` — WC argparse CLI (1567 lines, polling loop, reference for ARGPARSE PATTERNS only)
- `competitions/worldcup/src/output.py` — WC display (952 lines, ANSI color, auto-detect, reference for COLOR SUPPORT only)
- `competitions/euro/main.py` — Euro argparse CLI (261 lines, single-run, closer pattern to follow)
- `competitions/euro/display.py` — Euro display (44 lines, plain text, minimal pattern)

### Data
- `competitions/ucl/data/playoff_pairings.json` — Playoff tie data (display may reference tie numbers)
- `competitions/ucl/data/bracket_rules.json` — Bracket structure (display may reference match IDs)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `run_monte_carlo()` — returns dict with `teams: {team_name: {top_8_prob, champion_prob, stage_*_prob, ...}}`, `snapshot_date`, `n_iterations`, `seed`, `stage_order`. This is the data source for Phase 3.
- `aggregate_mc_results()` — isolated aggregation function that populates per-team probability fields. Can be reused if Phase 3 creates its own `SimulationResult`.
- `competitions/euro/display.py` — 44-line minimal display module. Pattern for UCL's simpler display layer.
- `competitions/worldcup/src/output.py` `_supports_color()` — ANSI detection function, reusable pattern.
- `competitions/worldcup/src/output.py` `_ansi()` — ANSI factory pattern, reusable.

### Established Patterns
- **argparse** with flat flags (no subcommands) — both WC and Euro set precedent.
- **Hand-rolled string formatting** — no tabulate/rich/PrettyTable. stdlib-only display.
- **Post-aggregation MC** — probabilities already aggregated by `run_monte_carlo()`.
- **Competition under `competitions/ucl/`** — all UCL logic stays in this directory.

### Integration Points
- `competitions/ucl/src/__init__.py` — Export new CLI and display functions.
- `competitions/ucl/src/simulation.py` — `run_monte_carlo()` output feeds the display.
- `competitions/ucl/src/knockout.py` — Knockout result dicts used by bracket display.
- `competitions/ucl/data/` — Data files remain unchanged; display reads `run_monte_carlo()` output, not data files directly.

</code_context>

<specifics>
## Specific Ideas

- `SimulationResult` schema should mirror what `run_monte_carlo()` returns plus knockout detail. Planned in PLAN.md, not designed here.
- Playoff display format: `9th Team A  3-2 agg  24th Team B  → Team A advances`. ET/Pens shown only when triggered: `2-2 agg (4-3 pens)`.
- ASCII tree bracket display is deferred to v2 (UCLD-02 path visualization).
- JSON schema for `--output` should be stable — Phase 4 consumers will depend on it.

</specifics>

<deferred>
## Deferred Ideas

- ASCII tree bracket visualization — future display enhancement, not architectural requirement.
- CSV export — can be generated from JSON without changing the simulation.
- `--quiet` flag — not needed; stdout can be redirected.
- `--verbose` flag for full tiebreaker chain — may add later, no demonstrated need yet.

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 3-UCL Simulation Orchestration + Display*
*Context gathered: 2026-06-28*
