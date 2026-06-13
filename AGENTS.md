# GSD Workflow Instructions

This project uses the GSD (Get Shit Done) workflow system managed via Claude/OpenCode.

## Project Context

- **Project:** World Cup Dynamic Prediction
- **Location:** `C:\Users\KIIT0001\Documents\antigravity skills\WC-2026`
- **Core Value:** A live, self-updating tournament predictor in your terminal

## Planning Documents

| Artifact | Location | Description |
|----------|----------|-------------|
| Project | `.planning/PROJECT.md` | Project context, requirements, constraints |
| Config | `.planning/config.json` | Workflow preferences |
| Requirements | `.planning/REQUIREMENTS.md` | 12 v1 requirements with traceability |
| Roadmap | `.planning/ROADMAP.md` | 6 phases with success criteria |
| State | `.planning/STATE.md` | Current phase and project memory |
| Codebase Map | `.planning/codebase/` | Codebase analysis (7 documents) |
| Research | `.planning/research/` | Domain research (5 documents) |
| Source of Truth | `SOTs/` | PRD, TRD, MVP, Appflow, Backend Schema, UI/UX, Implementation Plan |

## Workflow Preferences

- **Mode:** Interactive
- **Granularity:** Standard (5-8 phases, 3-5 plans each)
- **Parallelization:** Enabled
- **Commit docs:** No (.planning/ in .gitignore)
- **Model profile:** Inherit (use session model)
- **Research:** Yes (before each phase)
- **Plan check:** Yes
- **Verifier:** Yes
- **Nyquist validation:** Enabled
- **Project mode:** MVP (vertical slices)

## Available Commands

- `/gsd-plan-phase N` — Plan a specific phase
- `/gsd-execute-phase N` — Execute a planned phase
- `/gsd-progress` — Check project status
- `/gsd-map-codebase` — Refresh codebase understanding
