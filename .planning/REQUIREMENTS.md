# Requirements: Football Prediction Engine

**Defined:** 2026-06-27
**Core Value:** Adding a new competition requires only a new competition module — not changes to `football_core`

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### UCL League Table Engine

- [x] **UCLT-00**: Validate fixture schedule against official UCL format — verify each team has exactly 8 opponents, correct pot distribution (2 per pot), no duplicate matchups
- [x] **UCLT-01**: Simulate 36-team league phase with 8 matches per team, pot-constrained opponents (2 from each of 4 pots)
- [x] **UCLT-02**: UCL-specific tiebreaker chain — GD → GS → away GS → wins → away wins → opponent points → opponent GD → opponent GS → disciplinary → UEFA coefficient
- [x] **UCLT-03**: Rank qualification zones (top 8 direct, 9–24 playoff, 25–36 eliminated)
- [x] **UCLT-04**: Load fixture schedule from UCL data files (pre-determined draw, not dynamic pairing)
- [x] **UCLT-05**: Produce per-team advancement probabilities from Monte Carlo simulation
- [x] **UCLT-06**: Reuse `football_core` Poisson match simulation for individual UCL matches (no core modifications)

### UCL Knockout Phase

- [ ] **UCLK-01**: Simulate two-legged knockout ties with aggregate scoring (no away goals rule; extra time + penalties)
- [ ] **UCLK-02**: Build seeded knockout bracket — top 8 vs playoff winners with position-based pairings (1/2 vs 15/18, 3/4 vs 13/20, etc.)
- [ ] **UCLK-03**: Top-4 seeding protection — seeds 1–4 cannot meet each other until semifinals
- [ ] **UCLK-04**: Simulate playoff round (teams 9–24) to determine final 8 R16 entrants
- [ ] **UCLK-05**: Full knockout tree from R16 → QF → SF → Final with per-team stage probabilities

### UCL Orchestration + Display

- [ ] **UCLO-01**: CLI entry point (`ucl-predict`) with configurable iterations and seed
- [ ] **UCLO-02**: Display league table with qualification zones after simulation
- [ ] **UCLO-03**: Display knockout bracket with matchups and per-team stage probabilities
- [ ] **UCLO-04**: Display champion probabilities, final odds, and top-4 qualification odds

### UCL Validation & Production Readiness

- [ ] **UCLV-01**: Live BSD API integration — fetch real UCL match results and validate against fixture schedule
- [ ] **UCLV-02**: Cross-check predictions against real completed UCL matches
- [ ] **UCLV-03**: Accuracy metrics — Brier score, Log Loss, calibration curve for UCL predictions
- [ ] **UCLV-04**: Performance benchmarking — simulation time vs iteration count, identify bottlenecks
- [ ] **UCLV-05**: Regression verification — WC test suite green (613 passed, 1 skipped), Euro sim unchanged
- [ ] **UCLV-06**: Documentation and release readiness — README, ARCHITECTURE.md update, known limitations

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### UCL Differentiators (post-validation polish)

- **UCLD-01**: What-if scenario analysis (e.g., "what if Team X wins their remaining matches")
- **UCLD-02**: Path visualization (most-likely elimination path for a given team)
- **UCLD-03**: Strength-of-schedule impact reporting

### League Competitions (La Liga / Premier League)

- **LEAG-01**: Double round-robin fixture generation (circle method, ~40 lines)
- **LEAG-02**: League standings with configurable tiebreakers (H2H for La Liga, GD for PL)
- **LEAG-03**: Promotion/relegation logic (3 up, 3 down, with play-off variants)
- **LEAG-04**: European qualification placement
- **LEAG-05**: Season-long Monte Carlo simulation (38 matchdays × 20 teams = 380 matches)
- **LEAG-06**: Performance optimization for 50K+ iteration league simulation

### Euro Refactoring

- **EURO-01**: Refactor shared group/advancement logic into `football_core`
- **EURO-02**: Remove `sys.path` mutation from `competitions/euro/__init__.py`

### Packaging

- **PKG-01**: pip-installable `football-core` package with `pyproject.toml`
- **PKG-02**: Published public API with documented interface for competition modules

## Out of Scope

| Feature | Reason |
|---------|--------|
| Web UI / dashboard | Engine-only; web layer is separate project |
| Mobile app | Not relevant to engine architecture |
| Real-time live betting | Predictions are tournament-forecast, not in-play |
| ML model training pipeline | CatBoost models are consumed, not trained |
| Injury/suspension modeling | Too dynamic for Monte Carlo forecasting; relies on unavailable data |
| Transfer window modeling | Club-level only; unpredictable by nature |
| pyproject.toml / pip package | Deferred until 3 competitions are proven stable |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| UCLT-00 | Phase 1 | Completed (Plan 01) |
| UCLT-01 | Phase 1 | Completed (Plan 02) |
| UCLT-02 | Phase 1 | Completed (Plan 02) |
| UCLT-03 | Phase 1 | Completed (Plan 02) |
| UCLT-04 | Phase 1 | Completed (Plan 01) |
| UCLT-05 | Phase 1 | Completed (Plan 03) |
| UCLT-06 | Phase 1 | Completed (Plan 02) |
| UCLK-01 | Phase 2 | Pending (deferred Phase 1 limitation) |
| UCLK-02 | Phase 2 | Pending |
| UCLK-03 | Phase 2 | Pending |
| UCLK-04 | Phase 2 | Pending |
| UCLK-05 | Phase 2 | Pending |
| UCLO-01 | Phase 3 | Pending |
| UCLO-02 | Phase 3 | Pending |
| UCLO-03 | Phase 3 | Pending |
| UCLO-04 | Phase 3 | Pending |
| UCLV-01 | Phase 4 | Pending |
| UCLV-02 | Phase 4 | Pending |
| UCLV-03 | Phase 4 | Pending |
| UCLV-04 | Phase 4 | Pending |
| UCLV-05 | Phase 4 | Pending |
| UCLV-06 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 22 total
- Completed: 7
- Pending: 16
- Mapped to phases: 22
- Unmapped: 0 ✓

---

*Requirements defined: 2026-06-27*
*Last updated: 2026-06-27 after initial definition*
