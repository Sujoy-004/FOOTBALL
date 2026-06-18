# Phase 15: Context Signals — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-17
**Phase:** 15-context-signals
**Areas discussed:** Form computation design, Form integration mechanism, Lineup strength data source, Lineup strength formulation

---

## Form Computation Design

| Option | Description | Selected |
|--------|-------------|----------|
| Points-based rolling avg | W=3/D=1/L=0 averaged over last N matches | |
| Elo-based form residual | actual - expected, sum over window. Captures over/under-performance | ✓ |
| Scoreline-margin based | Goal difference per match, averaged | |

**User's choice:** Elo-based form residual
**Notes:** Window configurable default 5, minimum 1, 0 matches → available=false. Includes ALL match data (not WC-only).

---

## Form → Probability Conversion

| Option | Description | Selected |
|--------|-------------|----------|
| Log-odds adjustment | sigmoid(logit(p_elo) + residual) | |
| Exponential moving average | Weight recent more heavily, EMA → probability | |
| Direct rolling win-rate | Simple wins/(wins+losses), then Platt calibrated | |

**User's choice:** Match-level formulation with sigmoid
**Notes:** form_delta = home_residual - away_residual. p_form = sigmoid(k * form_delta). The user explicitly rejected single-team probability approaches: "Form is a team state metric, not a match prediction model." k is not locked — planner must determine from observed data.

---

## Form Integration Mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Modifier to Elo | Form factor adjusts expected_score before simulation | |
| Independent 4th signal | Form gets its own key in signals dict, goes through blender | ✓ |
| Both | Modifier + tracked signal for analysis | |

**User's choice:** Independent 4th signal (key: "form")

---

## Lineup Strength Data Source

| Option | Description | Selected |
|--------|-------------|----------|
| Research BSD API first | Check if BSD has squad/player endpoints | ✓ |
| Manual data file | data/team_values.json from Transfermarkt | |
| FIFA rank proxy | Use existing FIFA ranking | |

**User's choice:** Research BSD API first (deferred to gsd-phase-researcher)
**Notes:** Data source determines implementation path.

---

## Lineup Strength Formulation

| Option | Description | Selected |
|--------|-------------|----------|
| Log-ratio | delta = ln(home/away), sigmoid(k * delta) | ✓ |
| Z-score | Standardize across population first | Rejected |
| Other | User's own transformation | |

**User's choice:** Log-ratio, locked. Z-score rejected (shifts when teams are added/removed).
**Notes:** strength_delta = ln(home_value / away_value). p_strength = sigmoid(k * strength_delta). k not locked — same as form.

---

## the agent's Discretion

- Default k value for both signals (planner determines from observed data ranges)
- Lineup strength data source (after BSD research)
- Form window implementation detail (list/deque/rolling sum)
- Whether lineup.py is a standalone module or inline

## Deferred Ideas

None — discussion stayed within phase scope.
