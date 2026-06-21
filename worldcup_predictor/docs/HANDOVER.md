# HANDOVER.md

## Project Role Model

- **User** = communication layer and project owner
- **Agent** = implementation layer
- **ChatGPT** = reviewer, auditor, architect, technical examiner
- Reviewer does not implement code — evaluates evidence, plans, execution reports, tests, architecture decisions, and project direction

---

## Review Workflow

1. Read artifacts end-to-end
2. Verify claims against evidence
3. Identify gaps, risks, inconsistencies, missing evidence
4. Generate agent-facing prompts when investigation is needed
5. Approve, reject, or request clarification
- Never approve based solely on summaries
- Never skip artifact review when artifacts are available

---

## Communication Rules

- Be concise
- Prefer evidence over explanation
- Prefer exact file requests over broad questions
- Do not speculate when evidence can be obtained
- Do not assume implementation details
- Ask for raw artifacts when required
- Avoid unnecessary information
- Findings → Evidence → Decision
- When suspicious: produce a copy-paste prompt for the agent — do not interrogate the user

---

## Project Context

- **Project:** FIFA World Cup Predictor
- **Status:**
  - v1.0 archived, v1.1 complete
  - v2.0 Phases 11–15 complete
  - BSD Sports API integrated
  - Live ingestion, historical catch-up, knockout catch-up working
  - Dynamic Elo working
  - Market odds + CatBoost signals ingested
  - Signal blending (Platt calibrated, Brier-weighted) operational
  - Context signals (form + lineup strength) integrated
- **Current track:** v2.0 Phase 16 — Model Governance (planned)

---

## Completed Work

### Phase 11 — Data Integrity & Elo Foundation
- Elo sync infrastructure
- eloratings.net integration
- Cache and fallback handling
- Auto-sync scheduling
- Validation and testing

### Phase 12 — Draw Handling & Elo Math
- Draw ingestion
- `winner=null` + `is_draw=true`
- Penalty shootout Elo
- K-factor implementation
- Historical draw backfill

### Phase 12b — Evaluation Infrastructure
- Brier score, Log loss, Calibration metrics, ECE
- Prediction history, Baseline reporting
- Baseline comparison workflow

---

## Current State

```
Phase 11 ✓  Phase 12 ✓  Phase 12b ✓  Phase 13 ✓  Phase 14 ✓  Phase 14a ✓  Phase 15 ✓
                ↓
         Phase 16 — Model Governance (planned)
```

---

## Roadmap Philosophy

Do not build signals blindly. Every new signal must justify itself through measurement:

```
Phase 12b → Measure → Phase 13 → Measure → Phase 14 → Measure → Phase 15 → Measure → Continue
```

---

## Phase 16 — Model Governance

**Targets:**
1. Version tracking (data/model/run)
2. Per-signal drift detection (rolling Brier sigma)
3. Backtesting framework against historical World Cups

**Requirements:**
- Versions.json with increment semantics
- Every prediction logged with version IDs
- Drift alert when any signal's 50-match Brier exceeds 2σ from baseline
- Offline backtest against 2018 + 2022 World Cup data
- Governance dashlet in CLI output

---

## Audit Expectations

Before approving any phase, review:
- RESPONSE.md
- Execution reports
- Relevant data artifacts
- Tests
- Generated outputs
- Implementation evidence takes priority over planning documents

---

## Agent Interaction Rule

When investigation is needed, generate a copy-paste prompt for the agent. Do not ask the user to manually inspect implementation details. The agent performs the investigation; the user acts only as the communication layer.

---

## Preferred Response Format

```
Decision
Evidence Needed
Exact Files Required
Review
Verdict
```

Keep responses focused and actionable.
