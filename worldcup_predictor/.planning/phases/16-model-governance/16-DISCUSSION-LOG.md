# Phase 16: Model Governance — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-17
**Phase:** 16-Model-Governance
**Areas discussed:** Versioning Scheme, Backtesting Framework, Drift Detection, Governance Output

---

## Versioning Scheme

| Option | Description | Selected |
|--------|-------------|----------|
| Single incrementing version | One version counter for everything | |
| Separate data/model/run versions | Three independent version coordinates, plus per-entry tracking | ✓ |

**User's choice:** 3-version approach: `data_version`, `model_version`, `run_version`. Each answers a different question: "Which data? Which model? Which run?" All three stored per prediction entry + `versions.json` summary.

**Notes:**
- `data_version` increments only on material dataset change (new match completed OR existing entry gains a new signal). Not on merge execution, cache refresh, governance runs, or simulation runs.
- Run snapshot = lean governance payload only (not full state backup).

---

## Backtesting Framework

| Option | Description | Selected |
|--------|-------------|----------|
| Live API-based | Dynamic data from BSD sports API | |
| Static file-based | Store historical tournament data locally | ✓ |

**User's choice:** Static files at `data/historical/` — deterministic, repeatable, offline. No external API dependency.

**Notes:**
- 2018 + 2022 World Cups initially.
- Per-tournament + aggregate reports per the backtesting spec referenced in ROADMAP.
- Include winner prediction accuracy section.
- Per-match granularity rejected for Phase 16 — belongs in Phase 18.

---

## Drift Detection

| Option | Description | Selected |
|--------|-------------|----------|
| σ of window Brier distribution | σ = per-signal std of per-match Brier in last 50 matches. 2σ above reference baseline = drift alert | ✓ |
| Pooled σ across all signals | σ computed across all signals' 50-match windows | |
| Fixed Brier threshold | e.g., +0.05 from reference baseline | |

| Option | Description | Selected |
|--------|-------------|----------|
| Alert + auto-recalibrate | Drift triggers automatic Platt re-fit | |
| Alert only | Console warning + flag in run snapshot | ✓ |

**User's choice:** Per-signal σ (rejects pooled), 2σ threshold (rejects fixed threshold). Alert-only action for Phase 16 (rejects auto-recalibrate — recalibration already happens via calibrate_and_blend).

**Notes:**
- Reference baseline = fixed after 30-match cold start. Never changes.
- Rolling mean/σ = last 50 matches. Continuous.
- "Pooled σ hides signal-specific degradation" — user explicitly rejected.
- "A universal +0.05 threshold is arbitrary" — user explicitly rejected.

---

## Governance Output

| Option | Description | Selected |
|--------|-------------|----------|
| After probability table | Dashlet in every output cycle | |
| On startup + hourly + drift | Conditional display frequency | ✓ |
| Top of every cycle | Always visible | |

| Option | Description | Selected |
|--------|-------------|----------|
| Full metrics with placeholders | Show Brier = --, ECE = -- during cold start | |
| Hidden until threshold | First appearance shows full data | |
| Partial display — versions + count | Show structure with growing match count, no fake metrics | ✓ |

| Option | Description | Selected |
|--------|-------------|----------|
| Collapsible drift detail | Toggles between compact/expanded | |
| Always-visible expanded drift section | Could clutter output | |

**User's choice:** Frequency = startup + hourly + drift only. Cold start = visible with version info + match count + explicit cold-start status (NO fake metric placeholders). Active = compact table by default, expanded drift section only when drift detected. No collapsible UI.

---

## Deferred Ideas

- **Per-match backtest history** — too granular for Phase 16. Deferred to Phase 18.
- **BSD API as backtest data source** — violates offline/deterministic constraint.
- **Auto-recalibrate on drift** — alert-only in Phase 16. Recalibration handled by existing `calibrate_and_blend()`.
- **Full state dump per run** — archive bloat. Lean snapshots only.
