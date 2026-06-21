# Phase 19: Multi-League Framework — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-19
**Phase:** 19-Multi-League Framework
**Areas discussed:** League catalog source, State directory migration, Config mechanism, Per-league vs shared data

---

## League Catalog Source

| Option | Description | Selected |
|--------|-------------|----------|
| Static dict in constants.py | Hardcode `{1:"EPL", 2:"La Liga", ... 27:"World Cup 2026"}`. Zero API calls, always available. | ✓ |
| Fetched from BSD API | Dynamic, always current, but requires API access + startup latency. | |
| config.json in data/ | Editable without code changes, but adds file management overhead. | |

**User's choice:** Static dict in `constants.py`
**Notes:** Rejected API fetch (runtime dependency, failure mode, latency) and config.json (no architectural benefit). League IDs stable and version-controlled. `--list-leagues` reads from constants.

---

## State Directory Migration

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-migrate on first run | If `data/played.json` exists but `data/27/played.json` doesn't, copy files to `data/27/`. | ✓ |
| Flag-based migration | User runs `--migrate-states` explicitly. | |
| No migration — clean break | Keep existing files as-is, write to `data/27/` going forward. | |

**User's choice:** Auto-migrate on first run
**Notes:** Idempotent (guard by `data/27/played.json` existence), non-destructive (never delete originals), automatic, silent after first success. Rejected flag-based (unnecessary burden) and clean break (orphans continuity).

---

## Config Mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| `--league` + `config.json` | CLI flag for override, config.json for persistent default. Precedence: CLI > config.json > 27. | ✓ |
| `--league` + `LEAGUE_ID` env var | Follows POLL_INTERVAL pattern. | |
| `--league` only | No persistence, defaults to 27. | |

**User's choice:** `--league` + `config.json`
**Notes:** Rejected env var (deployment concern, poor UX for local users) and CLI-only (forces repeated flag usage). Config auto-created if missing, corrupt config falls back to 27 gracefully.

---

## Per-League vs Shared Data

| Option | Description | Selected |
|--------|-------------|----------|
| Modified Option 1 | Per-league: runtime state, caches, calibration, history. Shared: immutable reference data. | ✓ |
| File-per-league naming | `data/27_played.json`. No directory structure. | |
| Everything per-league | Even static assets duplicated. | |

**User's choice:** Modified Option 1 with per-league/Shared split
**Notes:** Challenge resolved: `calibration_params.json` = per-league (league-specific), `team_values.json` = shared (team-inherent reference data), `versions.json` = per-league (data_version/models_version/run_version all track league-scoped state). Rule established: shared = immutable reference data; per-league = anything generated, learned, cached, calibrated, or stateful.

---

## Deferred Ideas

None.
