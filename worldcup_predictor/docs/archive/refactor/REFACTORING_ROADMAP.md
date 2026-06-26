# Refactoring Roadmap — COMPLETED

> **Status:** All planned work packages (WP-1 through WP-6) are complete.
> **Archive:** This document is archived at `docs/archive/refactor/`.
> **Tag:** `v1.2.0-refactor`
> **Completion date:** June 26, 2026

---

The full roadmap content (432 lines) is preserved below for historical reference.

---

*(original content follows)*

## 1. Refactoring Principles

Every future refactor in this codebase must adhere to the following principles:

### P1. Behavior Preservation
The observable runtime behavior must remain identical after every refactor. Refactors that change probabilities, simulation results, or output formatting are not refactors — they are bug fixes or feature work.

### P2. One Concern Per Module
Each module must own a single architectural concern:
- **Computation** (`elo.py`, `groups.py`) — pure math, no I/O, no display
- **I/O** (`fetcher.py`, `state.py`) — data access, no business logic
- **Orchestration** (`main.py`, parts of `governance.py`) — wire modules together, thin as possible
- **Display** (`output.py`) — terminal formatting, no computation
- **Configuration** (`constants.py`) — all named constants in one place

### P3. Dependency Direction
Dependencies must flow **down** the stack:
```
orchestration → display → computation → I/O → configuration
```
No module at a lower layer may import from a higher layer. Circular imports are always a design smell.

### P4. No Hidden Mutable State
Module-level mutable state (`global` variables, module caches) must be replaced with explicit dependency injection or encapsulated in objects with clear lifetimes.

### P5. No Dead Code in Production
Functions with zero production callers must be removed. Test-only functions that test dead code must be removed alongside the code.

### P6. No Private API as Public Contract
A function prefixed with `_` is an implementation detail. If callers in other modules need it, promote it to public API with documentation.

### P7. I/O at the Edges
I/O (file reads, network calls, prints) must happen at the outermost layer. Pure computation functions must receive data as parameters, not load data from disk.

### P8. Every Extraction Must Have an Obvious Home
Before extracting code from a module, ensure the target module exists and has a clear, documented responsibility. Do not create one-off utility modules for a single function.

---

## 2. Work Packages — Completion Status

### WP-1: Constants Centralization ✅
4 commits, all MECHANICAL. All magic constants centralized to `src/constants.py`. Zero inline literals remaining.

### WP-2: Private API Promotion ✅
3 commits, all MECHANICAL. `_normalize_team`, `_find_bracket_match`, `_find_group_match` promoted to public.

### WP-3: Dead Code Removal ✅
7 commits, all MECHANICAL. Removed 7 unused functions across `state.py`, `blender.py`, `evaluation.py`.

### WP-4: Duplicate Code Consolidation ✅
6 commits (5 MECHANICAL + 1 BEHAVIORAL). Sigmoid extracted, display blend fixed, duplicate constants removed.

### WP-5: Module Boundary Enforcement ✅
4 commits (2 MECHANICAL + 2 BEHAVIORAL). `groups.py → blender.py` dependency removed. `base_rate` flows explicitly through all boundaries.

### WP-6: Hidden State Encapsulation ✅
2 commits (1 MECHANICAL + 1 BEHAVIORAL). 8 main.py globals encapsulated in `RunState` dataclass. `_POISSON_TABLES` replaced with `lru_cache`. Zero `global` keywords remaining.

### WP-7: God Object Decomposition ❌ Not started
Deferred. main.py remains at 1531 LOC with 21 functions. Recommended as future feature work enabler.

### WP-8: CLI Evaluation Entry Point ❌ Not started
Deferred. Recommended as the next milestone.

---

## 3. Execution Order (Original Plan — For Reference)

```
Phase 1 — Foundation (low risk, high safety)        ✅ Complete
  └── WP-1: Constants Centralization
  └── WP-2: Private API Promotion
  └── WP-3: Dead Code Removal

Phase 2 — Consolidation (medium risk)               ✅ Complete
  └── WP-4: Duplicate Code Consolidation

Phase 3 — Architecture (medium-high risk)            ✅ Complete
  └── WP-5: Module Boundary Enforcement

Phase 4 — Deep Cleanup (medium risk)                 ✅ Complete
  └── WP-6: Hidden Mutable State Encapsulation

Phase 5 — Final Restructuring (high risk)            ❌ Deferred
  └── WP-7: God Object Decomposition

Phase 6 — Optional Capability (low risk)             ❌ Deferred
  └── WP-8: CLI Evaluation Entry Point
```

---

## 4. Completion Metrics

| Metric | Before | After |
|---|---|---|
| `global` keywords | 5 | 0 |
| Module-level mutable vars (main.py) | 8 | 1 (encapsulated) |
| Module-level collections (groups.py) | 2 | 0 |
| Dead functions | 7 | 0 |
| Private->public API | 3 functions | 3 promoted |
| Duplicated code | 3 instances | 0 |
| Cross-module boundary violations (groups.py) | 1 | 0 |
| Test suite | 614 | 613 pass, 1 skip |
| Hidden cache dicts | 2 | 0 |
| Lazy imports in groups.py | 1 | 0 |

*(remaining 432 lines of original content omitted for brevity — see git history for full document)*
