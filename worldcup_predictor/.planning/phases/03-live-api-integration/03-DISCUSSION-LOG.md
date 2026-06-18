# Phase 3: Live API Integration — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-13
**Phase:** 3-Live API Integration
**Areas discussed:** API-to-bracket matching, Module responsibility split, Testing approach, Team name normalization, Failure handling and API outages

---

## API-to-Bracket Matching

| Option | Description | Selected |
|--------|-------------|----------|
| Team-name matching only | Match by comparing API team names to bracket team names using team_aliases.json. No api_id_mapping.json | ✓ |
| Pre-filled static mapping | Create static api_id_mapping.json mapping API numeric IDs to bracket IDs | |
| Hybrid | Primary: team-name + aliases. If ambiguous, consult api_id_mapping.json | |

**User's choice:** Team-name matching only
**Notes:** Matches Phase 1 D-08 decision. No manual mapping file, no maintenance burden.

**Follow-up 1:** How to determine which bracket match an API result corresponds to?
| Option | Selected |
|--------|----------|
| Match both teams — find bracket match where both team names match via aliases | ✓ |
| Match by match_id in URL (via mapping) | |

**Follow-up 2:** What happens when a match can't be matched to any bracket slot?
| Option | Selected |
|--------|----------|
| Silently skip | |
| Log warning + continue with raw data for inspection | ✓ |

**User's rationale:** Visible failure, no crash, easy debugging, system continues running.

---

## Module Responsibility Split

| Option | Description | Selected |
|--------|-------------|----------|
| Single fetcher.py | One module for HTTP + parse + alias lookup + bracket matching | ✓ |
| Separate modules | fetcher.py for HTTP only, separate matcher.py for processing | |

**User's choice:** Single fetcher.py

**Follow-up 1:** Public API shape?
| Option | Selected |
|--------|----------|
| Single fetch_new_results() | |
| Two functions: fetch_raw_matches() + process_matches() | ✓ |

**User's rationale:** More testable, cleaner separation, low complexity cost.

**Follow-up 2:** Return format for process_matches()?
| Option | Selected |
|--------|----------|
| Full match record (match_id, team_a, team_b, winner, scores, completed_at) | ✓ |
| Match ID + winner only | |

---

## Testing Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Monkeypatch requests.get | pytest monkeypatch fixture, zero additional dependencies | ✓ |
| Add responses library | Third-party HTTP mock library | |
| Add requests-mock library | Another HTTP mock library | |

**User's choice:** Monkeypatch requests.get

**Follow-up 1:** Test file structure?
| Option | Selected |
|--------|----------|
| Single test_fetcher.py | ✓ |
| Separate test dir with multiple files | |

**Follow-up 2:** Mock response realism?
| Option | Selected |
|--------|----------|
| Minimal JSON dicts matching only consumed fields | ✓ |
| Full realistic responses with all API fields | |

**User's rationale:** Test only what you consume. Smaller fixtures, easier maintenance.

---

## Team Name Normalization

| Option | Description | Selected |
|--------|-------------|----------|
| Case-insensitive alias lookup | Lowercase + strip + alias dict. No fuzzy matching | ✓ |
| Exact match only | Team name must match exactly | |
| Alias + fuzzy fallback | Alias primary, substring/partial fallback | |

**User's choice:** Case-insensitive alias lookup

**Follow-up 1:** Where does normalization logic live?
| Option | Selected |
|--------|----------|
| In fetcher.py as private function | ✓ |
| In separate normalize.py | |
| In state.py | |

**User's rationale:** Only used by API processing. Avoids extra file. Extract later if needed.

**Follow-up 2:** How does fetcher.py get aliases?
| Option | Selected |
|--------|----------|
| main.py loads via state.py, passes as parameter | ✓ |
| fetcher.py loads directly | |

**User's rationale:** Explicit dependency, more testable, no hidden I/O, consistent with architecture.

---

## Failure Handling and API Outages

| Option | Description | Selected |
|--------|-------------|----------|
| Retry 3x + fallback | Exponential backoff (1s, 2s, 4s), then cached data, continue loop | ✓ |
| Retry indefinitely | Keep retrying forever, never fall back | |
| Fail fast | On first failure, exit | |

**User's choice:** Retry 3x + fallback
**User's rationale:** Resilient, matches TRD, no crash during temporary outages, no infinite hangs.

**Follow-up 1:** HTTP 429 handling?
| Option | Selected |
|--------|----------|
| Respect Retry-After header, extended backoff | ✓ |
| Same as other errors (1s, 2s, 4s) | |

**User's rationale:** 429 is different from a network error. Respect Retry-After. Avoid repeated violations.

**Follow-up 2:** Data-level failures (malformed JSON, unmatchable names/matches)?
| Option | Selected |
|--------|----------|
| Log + skip — one bad match doesn't discard others | ✓ |
| Log + fall back to last cached data entirely | |

**User's rationale:** One bad match should not discard good matches. Log it, skip it, continue.

**Follow-up 3:** Partial tournament data (non-bracket matches)?
| Option | Selected |
|--------|----------|
| Filter to bracket only | |
| Existing matching logic already enforces this — no extra filter needed | ✓ |

**Follow-up 4:** API key validation timing?
| Option | Selected |
|--------|----------|
| Validate on startup — test call, fail fast | ✓ |
| Lazy check on first poll | |

**Follow-up 5:** HTTP timeout configuration?
| Option | Selected |
|--------|----------|
| In constants.py (API_TIMEOUT) | ✓ |
| Hardcoded in fetcher.py | |

---

## Agent's Discretion

- Retry backoff implementation details (sleep between retries, error classification)
- Exact console log format for match detection, retry attempts, and warnings
- Internal function naming within fetcher.py
- JSON key mapping from API response shape to internal field names

## Deferred Ideas

None — discussion stayed within phase scope.
