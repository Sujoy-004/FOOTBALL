# Phase 2: UCL Knockout Phase - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-28
**Phase:** 02-ucl-knockout-phase
**Areas discussed:** Extra time & penalties modeling, Playoff draw constraints, R16 pairing table format, Stage probability tracking, BSD API capabilities for UCL

---

## Extra Time & Penalties Modeling

| Option | Description | Selected |
|--------|-------------|----------|
| Reduced Poisson lambda | Simulate ET using football_core Poisson with reduced base rate | |
| Fixed draw -> penalties | Skip ET simulation, go straight to penalties | |
| Research first | Probe BSD for ET data before finalizing | ✓ |

**User's choice:** Research first. Probe BSD using the API key to determine available ET/penalty data. If BSD cannot support ET behavior, fall back to reduced-Poisson ET model reusing existing football_core primitives. Do not hardcode ET assumptions before checking the API.

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed conversion ~76% | Each shot has fixed ~76% scoring probability | |
| Elo-based conversion | Higher-Elo team gets better conversion rate | |
| Research first | Check BSD for penalty data first | ✓ |

**User's choice:** First determine whether BSD exposes penalty shootout data. If it does, use that evidence. If not, then choose the simplest statistically defensible model. Do not invent Elo-based penalty skill without evidence.

| Option | Description | Selected |
|--------|-------------|----------|
| Second leg home team | ET played at second leg venue, 2nd-leg home team gets home advantage | ✓ |
| No ET home advantage | ET is neutral — same lambdas as normal time | |

**User's choice:** Second leg home team. This is a competition rule, not a tunable model.

---

## Playoff Draw Constraints

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed position-based pairing | 9v24, 10v23, etc. Deterministic | |
| Seeded random draw | Random pair 9-16 vs 17-24 each iteration | |
| Hybrid — random but constrained | Random within bands, skip association clash | |
| Use official draw data | Use UEFA/BSD playoff draw if available, fallback to deterministic | ✓ |

**User's choice:** Use official UEFA/BSD playoff draw if available. Do not randomize or recreate the draw. Only fall back to deterministic position-based pairing if no authoritative draw data is available.

| Option | Description | Selected |
|--------|-------------|----------|
| Single pairing list | JSON array of 8 pairings as dedicated file | ✓ |
| Inherit from fixtures | Extend fixtures.json to include playoff matchups | |

**User's choice:** Single pairing list in dedicated `playoff_draw.json`. The playoff draw is a distinct competition artifact, not part of the league-phase fixture schedule.

---

## R16 Pairing Table Format

| Option | Description | Selected |
|--------|-------------|----------|
| Hardcoded in Python | Constant dict in knockout module | |
| JSON data file | bracket_rules.json alongside other data files | ✓ |

**User's choice:** JSON data file. This is competition configuration, not algorithmic logic. UCL module already uses data files. If UEFA changes format, update JSON rather than code.

---

## Stage Probability Tracking

| Option | Description | Selected |
|--------|-------------|----------|
| Post-aggregation (Phase 1 pattern) | Track per iteration, aggregate at end | ✓ |
| Analytical from matchup odds | Compute from match-up odds without simulating | |

**User's choice:** Post-aggregation (Phase 1 pattern). Established architecture from Phase 1. Knockout paths are path-dependent, making analytical probabilities more complex.

| Option | Description | Selected |
|--------|-------------|----------|
| Extended loop | Single MC loop: league + knockout in one | ✓ |
| Separate simulation | Standalone pass using league results | |

**User's choice:** Extended loop. Knockout depends on league-phase outcome of same MC iteration. Matches post-aggregation architecture.

| Option | Description | Selected |
|--------|-------------|----------|
| All knockout rounds | Full granularity through all stages | |
| Final 4 only | SF, Finalist, Champion only | |

**User's choice:** Full granularity: Eliminated in League Phase (25–36), Reached Playoff (9–24), Reached Round of 16, Quarterfinal, Semifinal, Final, Champion.

---

## BSD API Capabilities for UCL

**Investigation:** Probed live BSD API at `https://sports.bzzoiro.com/api/v2/events/?season_id=268&status=finished`. UCL Champions League uses league_id=7, season_id=268 (UEFA Champions League 25/26).

**Findings:**
- `penalty_shootout`: Exists with `home`/`away` scores (populated for Final: PSG 1-1 Arsenal, pens 4-3) ✅
- `extra_time_score`: Always null ❌
- `round_name`: "Round of 16", "Quarterfinals", "Semifinals", "Final" available ✅
- No official playoff pairings or bracket data exposed ❌
- `home_score`/`away_score` is FT score only, no ET breakdown

**User's choice:** Live BSD API is authoritative for validation, not simulation. ET simulated locally because BSD doesn't expose ET scoring. Penalty data used later for calibration (Phase 4), not runtime input.

---

## Deferred Ideas

- What-if scenario analysis (UCLD-01) — deferred to v2
- Path visualization (UCLD-02) — deferred to v2
- Strength-of-schedule impact reporting (UCLD-03) — deferred to v2
