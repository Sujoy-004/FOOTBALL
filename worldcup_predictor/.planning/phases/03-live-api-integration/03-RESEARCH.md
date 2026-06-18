# Phase 3: Live API Integration — Research

**Researched:** 2026-06-13
**Domain:** Football-Data.org v4 API integration, HTTP retry logic, team name normalization, monkeypatch-based testing
**Confidence:** HIGH

## Summary

Phase 3 adds live match fetching from Football-Data.org v4 API to the World Cup predictor. The fetcher module (`src/fetcher.py`) has two public functions: `fetch_raw_matches()` handling HTTP with manual retry logic, and `process_matches()` handling alias-based team name resolution and bracket matching. Testing uses pytest's `monkeypatch` fixture to mock `requests.get`, following the project's zero-additional-dependency pattern.

The API returns finished World Cup matches at `GET https://api.football-data.org/v4/matches?competition=WC&status=FINISHED`. Team names come from `homeTeam.name` / `awayTeam.name`. The API uses names like "United States", "IR Iran", "Korea Republic" — our `team_aliases.json` maps these to the canonical names used in the bracket ("USA", "Iran", "South Korea"). The `score.winner` field uses `"HOME_TEAM"` / `"AWAY_TEAM"` / `"DRAW"` — we map this to the winning team's canonical name.

**Primary recommendation:** Manual retry loop around `requests.get()` (not urllib3's `Retry` adapter on a Session, because monkeypatching `requests.get` is the agreed testing strategy per D-07). Three retries with 1s/2s/4s backoff, 429 respects `Retry-After` header or 60s default.

**Key risk:** Score field key naming varies between API versions. v4 uses lowercase `fullTime.home` / `fullTime.away`. The overtime doc page shows obsolete `homeTeam/awayTeam` keys. **Always access via dict keys verified against actual v4 responses, not documentation examples.**

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Team-name matching only — no api_id_mapping.json for MVP
- **D-02:** Match by both team names (deterministic per unique knockout match pairings)
- **D-03:** Unmatchable matches → log warning with raw data + skip
- **D-04:** Single `src/fetcher.py` for HTTP + processing
- **D-05:** Two functions: `fetch_raw_matches()` + `process_matches()`
- **D-06:** Full match record returned by process_matches()
- **D-07:** Monkeypatch requests.get for testing — no extra test deps
- **D-08:** Single `test_fetcher.py` following existing patterns
- **D-09:** Minimal JSON fixtures matching only consumed fields
- **D-10:** Case-insensitive alias lookup via team_aliases.json — no fuzzy matching
- **D-11:** Normalization logic inside fetcher.py (private function)
- **D-12:** Aliases loaded by main.py, passed as explicit parameter
- **D-13:** Retry 3x with exponential backoff (1s, 2s, 4s) → cached fallback → continue
- **D-14:** HTTP 429 respects Retry-After header or 60s wait
- **D-15:** Data errors → log + skip that match, continue processing others
- **D-16:** API key validated on startup — fail fast on missing/403
- **D-17:** API_TIMEOUT in constants.py (10s)

### Agent's Discretion
- Retry backoff implementation details (sleep between retries, error classification)
- Exact console log format for match detection, retry attempts, and warnings
- Internal function naming within fetcher.py
- JSON key mapping from API response shape to internal field names

### Deferred Ideas (OUT OF SCOPE)
None.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DATA-01 | System fetches live match results from Football-Data.org API every configured interval | API endpoint confirmed: `GET /v4/matches?competition=WC&status=FINISHED` with `X-Auth-Token` header. Response wraps matches in `{"matches": [...]}`. Free tier covers World Cup with competition code "WC" (ID 2000). Rate limit: 10 req/min free tier, polling at 1 req/60s is well within limits. |
| DATA-03 | Retry logic (3 retries, exponential backoff) + cached data fallback | Manual retry pattern with `requests.get()` confirmed as correct approach per D-07 (monkeypatch constraint). `urllib3.util.Retry` requires `requests.Session` which breaks the monkeypatch pattern. Backoff: 1s/2s/4s. 429 handled separately with `Retry-After` header. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| HTTP fetching | Fetcher (src/fetcher.py) | — | Pure HTTP — network call to Football-Data.org, no state involvement |
| Team name normalization | Fetcher (src/fetcher.py) | — | Private function inside fetcher.py per D-11 |
| Bracket matching | Fetcher (src/fetcher.py) | — | `process_matches()` consumes bracket + aliases to match API teams to bracket slots |
| Alias storage | Data file (team_aliases.json) | State (load_aliases) | Aliases loaded by main.py via state.py, passed to fetcher as parameter per D-12 |
| API key management | Environment (FOOTBALL_API_KEY) | main.py | Key read from env var, validated on startup per D-16 |
| Played match filtering | Fetcher (src/fetcher.py) | — | `played_ids` set passed to `process_matches()` to skip already-processed matches |
| Match persistence | State (state.py) | — | `save_played()` persists new match records from fetcher output |
| Constants config | Constants (constants.py) | — | `API_URL`, `API_TIMEOUT` added alongside existing `K_FACTOR`, `DATA_DIR` |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `requests` | 2.31+ | HTTP GET to Football-Data.org API | Already the project's HTTP library; no alternative considered [CITED: worldcup_predictor/src codebase] |
| `pytest` | 7+ | Test framework | Existing project pattern [CITED: worldcup_predictor/tests/] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `time` | stdlib | `time.sleep()` between retries | In retry loop for manual backoff |
| `logging` | stdlib | Log warnings for retries, skips | Throughout fetcher.py for operational visibility |
| `json` | stdlib | Parse API responses | In fetch_raw_matches for response parsing |
| `os` | stdlib | Read `FOOTBALL_API_KEY` env var | In main.py / startup validation |

### No Extra Dependencies
The team decided against using extra testing/mocking libraries:
- `responses` library — avoided per D-07 (monkeypatch only) [VERIFIED: pytest docs — monkeypatch is stdlib fixture]
- `urllib3.util.Retry` — cannot be used directly because it requires a `requests.Session`, and we're patching `requests.get` not `session.get` [VERIFIED: webscraping.ai guide]

## Package Legitimacy Audit

No new packages are installed in this phase. All code uses Python stdlib (`time`, `logging`, `json`) and the already-installed `requests` library. No audit required.

## Architecture Patterns

### API Data Flow (Phase 3 Context)
```
Football-Data.org API
       │ GET /v4/matches?competition=WC&status=FINISHED
       │ Headers: X-Auth-Token
       ▼
fetch_raw_matches(api_key)
   │ Retry loop: 3 attempts, 1s/2s/4s backoff
   │ 429 → Retry-After
   │ Timeout: API_TIMEOUT (10s)
   ▼
list[dict] — raw API match objects
       │
       ▼
process_matches(raw_matches, teams, bracket, aliases, played_ids)
   │ 1. Normalize team names via alias dict
   │ 2. Match API teams to bracket slots (both-team matching)
   │ 3. Filter out already-played matches
   │ 4. Map API field names → internal record schema
   ▼
list[dict] — processed match records
       │
       ▼
state.save_played() → data/played.json
team_ratings = elo.update_ratings(...)
state.save_teams() → data/teams.json
```

### Alias Resolution Flow
```
team_aliases.json                 main.py
   {                                  │
     "United States": ["USA", ...],   │ load_aliases()
     "Iran": ["IR Iran", ...],        │ invert → lookup dict
     ...                              │   {"usa": "USA", ...}
   }                                  │
       └──────────────────────►  passed to process_matches()
                                        │
                              _normalize_team(api_name, alias_lookup)
                                        │
                                        ▼
                              Normalized canonical team name
                              OR None (unmatchable → log + skip)
```

### Recommended Project Structure (Changes Only)
```
src/
├── __init__.py
├── constants.py     # + API_URL, API_TIMEOUT
├── state.py         # + load_aliases()
├── fetcher.py       # NEW — HTTP + processing
├── elo.py           # unchanged
└── simulation.py    # unchanged
data/
├── teams.json       # unchanged
├── bracket.json     # unchanged
├── team_aliases.json # unchanged
├── played.json      # written to by fetcher (via state.py)
└── (no api_id_mapping.json — per D-01)
tests/
├── conftest.py       # (minor additions possible)
├── test_fetcher.py   # NEW — 6+ test cases
├── test_state.py     # unchanged
├── test_elo.py       # unchanged
└── ...
main.py               # + API key validation, alias loading, fetcher hook
```

### Pattern 1: Manual Retry with requests.get()
**What:** A manual retry loop around `requests.get()` with exponential backoff. This is chosen instead of `urllib3.util.Retry` on a `requests.Session` because D-07 requires monkeypatching `requests.get` in tests. A Session would internally call `session.get()`, not `requests.get()`, making monkeypatch not intercept the calls.

**Source:** [ASSUMED — synthesized from project constraints (D-07 + D-13)]

```python
import time
import requests

def fetch_raw_matches(
    api_key: str,
    api_url: str = API_URL,
    timeout: int = API_TIMEOUT,
) -> list[dict]:
    """Fetch finished matches from Football-Data.org API with retry.

    Returns raw match dicts from API response, or [] on failure.
    """
    headers = {"X-Auth-Token": api_key}
    backoff = [1, 2, 4]  # seconds between retries

    for attempt in range(3):  # D-13: 3 retries total
        try:
            resp = requests.get(api_url, headers=headers, timeout=timeout)

            if resp.status_code == 429:  # D-14: rate limited
                retry_after = resp.headers.get("Retry-After", "60")
                wait = int(retry_after) if retry_after.isdigit() else 60
                if attempt < 2:
                    time.sleep(wait)
                    continue
                return []  # All retries exhausted

            resp.raise_for_status()
            data = resp.json()
            return data.get("matches", [])

        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as e:
            if attempt < 2:
                time.sleep(backoff[attempt])
                continue
            # D-13: all retries failed → return empty list
            return []
        except requests.exceptions.JSONDecodeError:
            # D-15: malformed JSON → skip this response entirely
            return []
    return []
```

### Pattern 2: MockResponse for Monkeypatch Tests
**What:** A minimal `MockResponse` class that mimics only the attributes consumed by the code under test.

**Source:** [VERIFIED: docs.pytest.org/en/stable/how-to/monkeypatch.html]

```python
class MockResponse:
    """Mock requests.Response with only fields used by fetcher."""

    def __init__(self, status_code=200, json_data=None, headers=None):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.headers = headers or {}
        self.ok = 200 <= status_code < 400

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if not self.ok:
            raise requests.exceptions.HTTPError(
                f"HTTP {self.status_code}", response=self
            )


def mock_get(*args, **kwargs):
    """Replacement for requests.get — returns MockResponse."""
    return MockResponse(status_code=200, json_data={
        "matches": [
            {"id": 1, "status": "FINISHED",
             "homeTeam": {"name": "Argentina"},
             "awayTeam": {"name": "Nigeria"},
             "score": {"winner": "HOME_TEAM",
                       "fullTime": {"home": 2, "away": 1}},
             "utcDate": "2026-06-15T22:00:00Z"},
        ]
    })


def test_fetch_success(monkeypatch):
    monkeypatch.setattr(requests, "get", mock_get)
    result = fetch_raw_matches("fake_key")
    assert len(result) == 1
    assert result[0]["homeTeam"]["name"] == "Argentina"
```

### Pattern 3: Multi-call Mock for Retry Testing
**What:** A closure-based mock that returns different responses on successive calls, enabling testing of retry behavior.

**Source:** [ASSUMED — common monkeypatch testing pattern]

```python
def make_retry_mock():
    """Returns a mock_get that returns 429, then 429, then success."""
    responses = [
        MockResponse(status_code=429,
                     json_data={},
                     headers={"Retry-After": "2"}),
        MockResponse(status_code=429,
                     json_data={},
                     headers={"Retry-After": "2"}),
        MockResponse(status_code=200, json_data={
            "matches": [
                {"id": 1, "status": "FINISHED",
                 "homeTeam": {"name": "Argentina"},
                 "awayTeam": {"name": "Nigeria"},
                 "score": {"winner": "HOME_TEAM",
                           "fullTime": {"home": 2, "away": 1}},
                 "utcDate": "2026-06-15T22:00:00Z"},
            ]
        }),
    ]
    call_count = 0

    def mock_get(*args, **kwargs):
        nonlocal call_count
        r = responses[call_count]
        call_count += 1
        return r

    return mock_get, call_count_reference  # use closure variable
```

### Pattern 4: Case-Insensitive Alias Lookup with Bracket Self-Aliases
**What:** Build an inverted alias dict at load time (inverted_dict). First, auto-populate all bracket team names as self-aliases so teams like "Argentina" resolve to themselves. Then overlay team_aliases.json entries for actual name-mapping (e.g., "United States" → "USA", "IR Iran" → "Iran"). Lowercase both API name and lookup keys. Strip whitespace. No fuzzy matching.

**Source:** [ASSUMED — derived from D-10 specification + checker fix for normalization gap]

```python
def _build_alias_lookup(
    aliases: dict[str, list[str]],
    bracket: list[dict],
) -> dict[str, str]:
    """Build alias lookup with bracket team self-aliases.

    Phase 1: Auto-populate all bracket team names as self-aliases so that
    "argentina" → "Argentina", "france" → "France", etc. resolve correctly
    even without explicit alias entries.
    Phase 2: Overlay team_aliases.json entries for API-to-bracket mapping.

    Input aliases: {"United States": ["USA"]}
    Input bracket: [{"team_a": "Argentina", "team_b": "Iran", ...}]
    Output: {"argentina": "Argentina", "iran": "Iran",
             "united states": "United States", "usa": "United States"}
    """
    lookup = {}

    # Phase 1: Auto-populate bracket team names as self-aliases
    for match in bracket:
        if match.get("team_a"):
            lookup[match["team_a"].strip().lower()] = match["team_a"]
        if match.get("team_b"):
            lookup[match["team_b"].strip().lower()] = match["team_b"]

    # Phase 2: Overlay team_aliases.json entries
    for canonical, variants in aliases.items():
        lookup[canonical.strip().lower()] = canonical
        for variant in variants:
            lookup[variant.strip().lower()] = canonical
    return lookup


def _normalize_team(
    api_name: str,
    alias_lookup: dict[str, str],
) -> str | None:
    """Resolve an API team name to canonical bracket name.

    Returns None if unmatchable.
    """
    key = api_name.strip().lower()
    return alias_lookup.get(key)  # None if not found
```

### Pattern 5: Bracket Matching by Both Team Names
**What:** For each API match, normalize both team names and search the bracket for a match where both names match.

**Source:** [ASSUMED — derived from D-02 specification]

```python
def _find_bracket_match(
    api_home: str,
    api_away: str,
    bracket: list[dict],
    alias_lookup: dict[str, str],
) -> str | None:
    """Find bracket match_id where both normalized team names match.

    Checks both orderings (home/away vs team_a/team_b may not align).
    Returns None if no match found.
    """
    home_norm = _normalize_team(api_home, alias_lookup)
    away_norm = _normalize_team(api_away, alias_lookup)

    if home_norm is None or away_norm is None:
        return None

    for match in bracket:
        if match["team_a"] is None or match["team_b"] is None:
            continue  # skip unresolved later-round slots
        ta, tb = match["team_a"], match["team_b"]
        if {ta, tb} == {home_norm, away_norm}:
            return match["match_id"]
    return None
```

### Anti-Patterns to Avoid
- **Session-based retry with monkeypatch:** Using `requests.Session()` + `urllib3.util.Retry` breaks monkeypatch testing because the code calls `session.get()` not `requests.get()`. The D-07 constraint means retry must be manual.
- **`response.raise_for_status()` before checking 429 status:** If you call `raise_for_status()` on a 429 response, it raises `HTTPError` before you can inspect `Retry-After`. Check `status_code == 429` before `raise_for_status()`.
- **Assuming `score.fullTime` keys are `homeTeam/awayTeam`:** The v4 API uses lowercase `home/away` for the score node, but the overtime doc page shows `homeTeam/awayTeam`. Always use the v4 match resource as authoritative.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Mock HTTP responses | Custom mock class with edge cases | `MockResponse` + `monkeypatch.setattr(requests, "get", mock_get)` | pytest docs pattern; D-07 mandates zero extra deps |
| Team name resolution | Fuzzy matching / Levenshtein | Case-insensitive dict lookup via aliases | D-10: fuzzy matching creates false positives worse than no match |
| API ID mapping | Manual mapping file | Team-name matching via aliases | D-01: avoids maintenance burden |
| Retry logic | Custom retry decorator/library | Manual `for attempt in range(3)` loop | Cannot use urllib3 Retry per D-07 constraint |

**Key insight:** This phase is deliberately constrained by the monkeypatch testing decision (D-07). The manual retry loop is slightly more verbose than using urllib3's `Retry` class, but it makes testing dead simple — just provide a `MockResponse` matching the call signature.

## Common Pitfalls

### Pitfall 1: score.winner ≠ team winner name
**What goes wrong:** Code directly returns `score.winner` ("HOME_TEAM") as the match winner instead of resolving it to the actual team name.
**Why it happens:** The API uses enum values "HOME_TEAM", "AWAY_TEAM", "DRAW" for `score.winner`, not team names.
**How to avoid:** Map `score.winner == "HOME_TEAM"` → resolved `homeTeam.name`, `"AWAY_TEAM"` → resolved `awayTeam.name`. Store the canonical team name, not the enum string.
**Warning signs:** The `played.json` winner field contains strings like "HOME_TEAM" instead of team names.

### Pitfall 2: Retry-After header not parsed for 429
**What goes wrong:** Code calls `raise_for_status()` before checking status code, which raises `HTTPError` on 429 before `Retry-After` can be inspected.
**Why it happens:** `raise_for_status()` covers all 4xx/5xx codes. 429 needs special handling.
**How to avoid:** Always check `resp.status_code == 429` first (before `raise_for_status()`), extract `Retry-After`, sleep, and `continue`.
**Warning signs:** 429 errors bubble up as unhandled HTTPExceptions instead of triggering retry.

### Pitfall 3: Bracket match ordering confusion (home/away vs team_a/team_b)
**What goes wrong:** Code matches API `homeTeam` → bracket `team_a` and API `awayTeam` → bracket `team_b` without considering the ordering might be swapped.
**Why it happens:** The bracket.json defines `team_a`/`team_b` but doesn't specify home/away. The API always assigns home/away. A match could have teams in different order.
**How to avoid:** Use set comparison `{team_a, team_b} == {home_norm, away_norm}` instead of positional matching.
**Warning signs:** A valid API match never matches any bracket slot even though team names exist in the bracket.

### Pitfall 4: Score key naming inconsistency in documentation
**What goes wrong:** Code accesses `fullTime["homeTeam"]` (v2 key) but v4 uses `fullTime["home"]`.
**Why it happens:** The football-data.org documentation for overtime/match pages shows different key names in examples.
**How to avoid:** The v4 authoritative match documentation consistently uses lowercase `home`/`away`. Verify against an actual API response during testing.
**Warning signs:** `KeyError` when accessing `fullTime` fields.

### Pitfall 5: `utcDate` format mismatch
**What goes wrong:** Code assumes a specific date format for `completed_at` but API returns ISO 8601 with timezone suffix.
**Why it happens:** The API returns dates like `"2026-06-15T22:00:00Z"` (ISO 8601 with Z suffix).
**How to avoid:** Pass through the UTC string directly as `completed_at`. The existing `test_integration.py` shows the expected format: `"2026-06-15T22:05:01Z"`.
**Warning signs:** Date parsing errors or mismatched format strings.

## Code Examples

### Example 1: Complete fetch_raw_matches with retry
**Source:** [ASSUMED — synthesized from D-07, D-13, D-14, D-17 constraints]

```python
def fetch_raw_matches(
    api_key: str,
    api_url: str = "",
    timeout: int = 10,
) -> list[dict]:
    """Fetch finished World Cup matches with retry logic.

    Args:
        api_key: Football-Data.org API key (X-Auth-Token header).
        api_url: Full API URL with query params.
        timeout: Request timeout in seconds.

    Returns:
        List of raw match dicts from API response.
        Empty list on failure (all retries exhausted).
    """
    headers = {"X-Auth-Token": api_key}
    backoff_seconds = [1, 2, 4]

    for attempt in range(3):
        try:
            resp = requests.get(api_url, headers=headers, timeout=timeout)

            # D-14: Handle 429 before raise_for_status
            if resp.status_code == 429:
                raw = resp.headers.get("Retry-After", "60")
                wait = int(raw) if raw.isdigit() else 60
                if attempt < 2:
                    time.sleep(wait)
                    continue
                return []  # All retries exhausted on 429

            resp.raise_for_status()
            data = resp.json()
            return data.get("matches", [])

        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError):
            if attempt < 2:
                time.sleep(backoff_seconds[attempt])
                continue
            return []  # D-13: all retries → fall back to cached

        except (json.JSONDecodeError,
                requests.exceptions.JSONDecodeError):
            return []  # D-15: malformed JSON → skip
    return []
```

### Example 2: Complete process_matches with alias resolution
**Source:** [ASSUMED — derived from D-02, D-03, D-06, D-10, D-11, D-12, D-15]

```python
def process_matches(
    raw_matches: list[dict],
    teams: dict[str, dict],
    bracket: list[dict],
    aliases: dict[str, list[str]],
    played_ids: set[str],
) -> list[dict]:
    """Process API matches into internal match records.

    Steps:
    1. Build alias lookup from team_aliases.json
    2. For each API match with status FINISHED:
       - Normalize team names via aliases
       - Match to bracket slot by both team names
       - Skip if already played or unmatchable
       - Map API fields to record schema

    Returns:
        List of match records ready for elo.update_ratings()
        and state.save_played().
    """
    alias_lookup = _build_alias_lookup(aliases, bracket)
    results: list[dict] = []

    for match in raw_matches:
        if match.get("status") != "FINISHED":
            continue

        api_id = match.get("id")
        if api_id in played_ids:
            continue

        home_name = match.get("homeTeam", {}).get("name", "")
        away_name = match.get("awayTeam", {}).get("name", "")

        home_norm = _normalize_team(home_name, alias_lookup)
        away_norm = _normalize_team(away_name, alias_lookup)

        if home_norm is None or away_norm is None:
            # D-03: log warning with raw data
            continue

        bracket_id = _find_bracket_match(
            home_norm, away_norm, bracket, alias_lookup
        )
        if bracket_id is None:
            # D-03: log warning — likely group stage match
            continue

        score = match.get("score", {})
        winner_enum = score.get("winner")
        full_time = score.get("fullTime", {})

        # D-06: map to internal record
        if winner_enum == "HOME_TEAM":
            winner = home_norm
        elif winner_enum == "AWAY_TEAM":
            winner = away_norm
        else:
            # DRAW — shouldn't happen in knockout, skip
            continue

        record = {
            "match_id": bracket_id,
            "team_a": home_norm,
            "team_b": away_norm,
            "winner": winner,
            "home_score": full_time.get("home", 0),
            "away_score": full_time.get("away", 0),
            "completed_at": match.get("utcDate", ""),
        }
        results.append(record)

    return results
```

### Example 3: API key validation on startup
**Source:** [ASSUMED — derived from D-16]

```python
import os
import sys

def validate_api_key() -> str:
    """Validate FOOTBALL_API_KEY on startup.

    Returns the API key if valid.
    Exits with code 1 if missing or invalid.
    """
    api_key = os.environ.get("FOOTBALL_API_KEY")
    if not api_key:
        print("Error: FOOTBALL_API_KEY not set.", file=sys.stderr)
        print("Get a free API key at https://www.football-data.org/", file=sys.stderr)
        sys.exit(1)

    # Quick validation call
    test_url = "https://api.football-data.org/v4/competitions/WC"
    resp = requests.get(test_url, headers={"X-Auth-Token": api_key}, timeout=10)
    if resp.status_code == 403:
        print("Error: Invalid FOOTBALL_API_KEY (HTTP 403).", file=sys.stderr)
        sys.exit(1)
    if resp.status_code != 200:
        print(f"Warning: API check returned {resp.status_code}, continuing...", file=sys.stderr)

    return api_key
```

### Example 4: Monkeypatch test for retry exhaustion
**Source:** [ASSUMED — synthesized from D-07 + D-13]

```python
def test_fetch_all_retries_exhausted(monkeypatch):
    """When all 3 retries fail, fetch_raw_matches returns []."""
    responses = [
        MockResponse(status_code=500, json_data={}),
        MockResponse(status_code=500, json_data={}),
        MockResponse(status_code=500, json_data={}),
    ]
    call_log = []

    def mock_get(*args, **kwargs):
        call_log.append(kwargs)
        return responses[len(call_log) - 1]

    monkeypatch.setattr(requests, "get", mock_get)
    result = fetch_raw_matches("fake_key")

    assert result == []
    assert len(call_log) == 3  # 3 retries attempted
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| TRD specified TR-06 `api_id_mapping.json` | Team-name matching via aliases | D-01 discussion | No manual mapping file; aliases handle name differences |
| TRD specified `fetch_new_results(last_known_match_ids)` | Two functions: `fetch_raw_matches()` + `process_matches()` | D-05 | Separates HTTP from data processing; each independently testable |
| TRD specified `MatchResult` class | `dict`-based records | D-06 | Consistent with existing dict-based architecture (no classes) |

**Deprecated/outdated:**
- Football-Data.org v1/v2 docs showing `score.fullTime.homeTeam` / `score.fullTime.awayTeam` — v4 uses lowercase `home` / `away`
- v2 `homeTeamName` / `awayTeamName` — v4 nests under `homeTeam.name` / `awayTeam.name`

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Football-Data.org v4 uses `score.fullTime.home` / `score.fullTime.away` (lowercase) for full-time scores | Technical Context | Minor — would cause KeyError at runtime; fixable by checking both key patterns |
| A2 | `score.winner` values are `"HOME_TEAM"` / `"AWAY_TEAM"` for finished matches | Implementation Patterns | Verified in v4 match page; overtime doc page confirms HOME_TEAM. LOW risk. |
| A3 | Free tier covers WC competition with code "WC" (ID 2000) | Technical Context | CITED in lookup tables; if the 2026 WC has a different competition ID/code, the endpoint filter might not work during the tournament |
| A4 | API returns `utcDate` as ISO 8601 string | Code Examples | Docs show `"2022-02-27T16:05:00Z"` format. LOW risk. |
| A5 | Bracket R16 matches have non-null `team_a`/`team_b` values | Implementation Patterns | VERIFIED: bracket.json shows all R16 entries with concrete team names |
| A6 | `requests.exceptions.JSONDecodeError` exists in installed requests version | Code Examples | Added in requests 2.27+. If older version, falls back to `json.JSONDecodeError`. |
| A7 | Manual retry loop with `requests.get()` is the correct approach given D-07 | Standard Stack | If there's a way to monkeypatch session.get instead, the retry could use `urllib3.Retry`. But D-07 explicitly says `requests.get`. |

## Open Questions (RESOLVED)

1. **(RESOLVED) What competition code/ID does Football-Data.org use for the 2026 World Cup?**
   - What we know: The 2022 WC uses code "WC" and ID 2000. The lookup tables show WC as competition code 2000.
   - Resolution: Use the established `competition=WC` filter. If it doesn't work, the competition may be listed under a different code. The API key validation endpoint `GET /v4/competitions/WC` will fail with 404 if the code is wrong, giving early feedback. Implemented per D-16 in validate_api_key().

2. **(RESOLVED) Will the score.fullTime keys be `home`/`away` (lowercase) or `homeTeam`/`awayTeam` in the actual 2026 World Cup response?**
   - What we know: The v4 match documentation shows lowercase. The overtime page shows the v2 format.
   - Resolution: Access via `full_time.get("home", full_time.get("homeTeam", 0))` for safety. Implemented per D-06 in process_matches().

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 7+ |
| Config file | not found — uses pytest defaults |
| Quick run command | `pytest -x tests/test_fetcher.py -v` |
| Full suite command | `pytest -x -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DATA-01 | Successful fetch returns match list | unit | `pytest tests/test_fetcher.py::test_fetch_success -x -v` | ❌ Wave 0 |
| DATA-01 | Empty API response returns [] | unit | `pytest tests/test_fetcher.py::test_fetch_empty_response -x -v` | ❌ Wave 0 |
| DATA-03 | Transient error retries 3 times then returns [] | unit | `pytest tests/test_fetcher.py::test_fetch_all_retries_exhausted -x -v` | ❌ Wave 0 |
| DATA-03 | HTTP 429 retries with Retry-After | unit | `pytest tests/test_fetcher.py::test_fetch_429_retry_after -x -v` | ❌ Wave 0 |
| DATA-01 | API timeout triggers retry | unit | `pytest tests/test_fetcher.py::test_fetch_timeout_retry -x -v` | ❌ Wave 0 |
| DATA-03 | Malformed JSON returns [] | unit | `pytest tests/test_fetcher.py::test_fetch_malformed_json -x -v` | ❌ Wave 0 |
| DATA-01 | process_matches normalizes team names | unit | `pytest tests/test_fetcher.py::test_process_matches_normalizes -x -v` | ❌ Wave 0 |
| DATA-01 | Unmatchable team names logged and skipped | unit | `pytest tests/test_fetcher.py::test_process_matches_unmatchable -x -v` | ❌ Wave 0 |
| DATA-01 | Already-played matches are filtered out | unit | `pytest tests/test_fetcher.py::test_process_matches_filters_played -x -v` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest -x tests/test_fetcher.py -v`
- **Per wave merge:** `pytest -x -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_fetcher.py` — all test cases (9 total)
- [ ] `tests/conftest.py` — optional: shared MockResponse fixture if reused

*(Framework config: pytest defaults are sufficient — no pytest.ini needed)*

## Security Domain

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | API key read from env var `FOOTBALL_API_KEY`; never in code or JSON |
| V6 Cryptography | no | API uses HTTPS (TLS); no application-level crypto needed |
| V8 Data Protection | partial | API key validated on startup but passed in-memory throughout runtime |

### Known Threat Patterns for requests/HTTP
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Exposed API key in logs/errors | Information Disclosure | Log only `[REDACTED]` for API key; validate key never printed |
| Man-in-the-middle (HTTP) | Tampering | API URL uses `https://` enforced by requests library |
| HTTP 403 key brute-force | Denial of Service | Not applicable — validated once on startup per D-16 |

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.10+ | All code | ✓ | TBD | — |
| `requests` | fetcher.py | ✓ | TBD | — |
| `pytest` | Tests | ✓ | TBD | — |
| Football-Data.org API | fetch_raw_matches | External | v4 | Cached data (played.json) |
| `FOOTBALL_API_KEY` env var | api validation | User-set | — | Startup error + exit 1 |

**Missing dependencies with no fallback:**
- Football-Data.org API key — user must obtain from https://www.football-data.org/. System exits with clear instructions on missing/403.

**Missing dependencies with fallback:**
- API outage → cached `played.json` data, system continues without fetching (D-13).

## Sources

### Primary (HIGH confidence)
- [Football-Data.org v4 Match Documentation](https://docs.football-data.org/general/v4/match.html) — Full response structure, status enums, score.winner values
- [Football-Data.org Lookup Tables](https://docs.football-data.org/general/v4/lookup_tables.html) — Competition codes (WC = 2000), score.duration enums
- [Football-Data.org Overtime/Penalties Documentation](https://docs.football-data.org/general/v4/overtime.html) — score.winner = "HOME_TEAM" confirmed
- [pytest monkeypatch documentation](https://docs.pytest.org/en/stable/how-to/monkeypatch.html) — Official MockResponse pattern
- Project codebase (`worldcup_predictor/`) — Existing patterns for state, constants, tests, bracket, teams, aliases

### Secondary (MEDIUM confidence)
- [Python Requests Retry Guide (SpyderProxy 2026)](https://spyderproxy.com/blog/python-requests-retry) — Retry strategy parameters confirmed
- [urllib3 Retry source](https://github.com/urllib3/urllib3/blob/main/src/urllib3/util/retry.py) — Backoff factor formula `factor * (2 ** (attempt - 1))`

### Tertiary (LOW confidence)
- None — all key claims verified against official documentation or existing codebase

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified in existing codebase
- Architecture: HIGH — derived from explicit phase decisions (D-01 through D-17)
- Pitfalls: MEDIUM — API key naming is assumed based on v4 docs; actual 2026 World Cup key naming might differ slightly

**Research date:** 2026-06-13
**Valid until:** 2026-07-15 (or when 2026 World Cup starts — API competition data may change)
