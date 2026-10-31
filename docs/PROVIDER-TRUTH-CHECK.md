# Provider Truth Check

How to decide whether a competition's on-disk season store holds **real data** or
**falsified data** — and how to restore it without guessing.

Written after the 2026-10-05 LaLiga incident, where 69 verified results were
destroyed by a provider refresh. Applies to LaLiga, UCL and World Cup.

---

## The failure signature

A store is **falsified** when it looks complete but is actually a fragment.
Red flags, any one of which is disqualifying:

| Signal | Healthy | Falsified |
|--------|---------|-----------|
| `availability.n_played` vs. real-world matchday progress | matches the completed matchday | `0` while the season is weeks underway |
| `availability.n_fixtures` vs. season size | full season (e.g. 380) | one matchday only (e.g. 7) |
| `availability.fully_received` | `true` **and** counts are complete | `true` on a fragment — the worst case |
| `results.json` matches array | one entry per finished match | `[]` while matches have been played |
| `provider` field | stable | flipped mid-season with no code change |
| Fixture `event_date` | real kickoff times | many `...T00:00:00Z` placeholders |

`fully_received: true` on an incomplete payload is the dangerous case: it
disables every downstream staleness check, so the falsified store is trusted
indefinitely.

## Root cause, in this repo

`web/common.py` → `get_data_provider()` resolves providers in this order:

1. `DATA_PROVIDER=football-data` + FDO key → `FootballDataOrgProvider`
2. `DATA_PROVIDER` unset → `FootballDataOrgProvider` when key present
3. no usable key → `None`

Football-Data.org is the sole match data provider. Its `fetch_matches` returns
full season schedules, avoiding rolling-window partial replacement traps.

**`DATA_PROVIDER` is load-bearing, not a preference.** It is pinned in `.env`
to `football-data` with a comment explaining why. Do not remove it.

---

## Cross-check procedure

Run this whenever a season store looks wrong, before touching code. Never
restore from memory or guess which version was right — make the providers
adjudicate.

### 1. Read the store

```powershell
$c = Get-Content "competitions/laliga/data/seasons/2026_27/fixtures.json" -Raw | ConvertFrom-Json
$c.provider; $c.availability | ConvertTo-Json -Compress; $c.fixtures.Count
```

### 2. Ask football-data.org what is true

Use the repo's own provider class so the request format is always correct —
never hand-write the URL.

```python
import json
from pathlib import Path
from football_core.data_providers.football_data_org_provider import FootballDataOrgProvider

env = {}
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); env[k.strip()] = v.strip()

d = FootballDataOrgProvider(env["FOOTBALL_DATA_ORG_KEY"])._request(
    "https://api.football-data.org/v4/competitions/PD/matches?season=2026"
)
ms = d.get("matches", [])
finished = [m for m in ms if m.get("status") == "FINISHED"]
print("total:", len(ms), "finished:", len(finished),
      "matchdays:", sorted({m["matchday"] for m in finished}))
```

Note the season parameter is the **starting year** (`2026`, not `2026_27`) and
the header is `X-Auth-Token`. Getting either wrong returns a structured
400/404 that looks like a network failure but is not.

### 3. Confirm the team-games identity

The single most reliable arithmetic check, needing no schedule knowledge:

```
n_played (matches)  ==  sum over teams of (games played) / 2
```

LaLiga on 2026-10-06: 18 teams × 7 games + 2 teams × 6 games = 138 team-games
÷ 2 = **69 matches**. Two teams on 6 instead of 7 means two postponed
fixtures — a normal, real condition, not a data error.

### 4. Confirm against two independent human sources

The provider is one source. Cross-check with sources that do not share its
failure modes:

- `worldfootball.net/competition/<code>/season/<season>/` — results **and**
  table per matchday
- `laliga.com/en-GB/laliga-easports/standing` — official table, and each match
  page carries per-team played/won/drawn/lost
- `uefa.com` for UCL; `fifa.com` for World Cup

Agreement across provider + aggregator + official source is what makes a
number trustworthy here. Two agreeing sources are a coincidence.

### 5. Adjudicate

- Store matches all sources → store is fine, investigate elsewhere.
- `HEAD` matches all sources, working tree does not → **working tree is
  falsified**. Restore it.
- Neither matches → the provider's live data has moved on; re-ingest and treat
  the re-ingested store as truth.

---

## Restore procedure

Never hand-edit a season store. Restore, then re-ingest through the real
pipeline path.

```powershell
git checkout -- "competitions/laliga/data/seasons/2026_27/fixtures.json" `
                "competitions/laliga/data/seasons/2026_27/results.json"
```

Then re-ingest with an **explicitly constructed** provider, so the result does
not depend on `DATA_PROVIDER` being set correctly:

```python
from football_core.data_providers.football_data_org_provider import FootballDataOrgProvider
from competitions.laliga.src.pipeline import fetch_live_data, DATA_DIR

out = fetch_live_data(data_dir=DATA_DIR,
                      provider=FootballDataOrgProvider(env["FOOTBALL_DATA_ORG_KEY"]),
                      football_data_org_key=env["FOOTBALL_DATA_ORG_KEY"])
print(out["n_raw"], out["n_updated"], out["per_season"])
```

### Verify the ingest changed only what it should

A live re-ingest will legitimately differ from the committed snapshot — the
provider learns real kickoff times for later matchdays after a placeholder
snapshot was taken. Prove the diff is benign:

```python
import json, subprocess
from collections import Counter

old = json.loads(subprocess.run(
    ["git", "show", "HEAD:competitions/laliga/data/seasons/2026_27/fixtures.json"],
    capture_output=True, text=True, encoding="utf-8").stdout)
new = json.loads(open("competitions/laliga/data/seasons/2026_27/fixtures.json",
                      encoding="utf-8").read())

# must hold: no fixture gained or lost
assert Counter(f["match_id"] for f in old["fixtures"]) == \
       Counter(f["match_id"] for f in new["fixtures"])

# must hold: no already-played result changed
ob = {f["match_id"]: f for f in old["fixtures"]}
nb = {f["match_id"]: f for f in new["fixtures"]}
changed = [(m, ob[m]["status"], nb[m]["status"]) for m in ob
           if (ob[m]["status"] == "finished") != (nb[m]["status"] == "finished")]
assert not changed, changed
```

Three assertions give a green light: identical `match_id` sets, zero
played-status changes, zero team-name mismatches. Then check the improvement —
midnight placeholders should *decrease*, and `n_played` must not move.

Commit the result with the cross-check evidence in the message. A data restore
whose provenance is only "it looked wrong" is indistinguishable from a
fabrication later.

---

## Known-good reference values

Use these as tripwires. If a live probe disagrees, the probe is wrong or the
world changed — either way, stop and reconcile rather than overwrite.

**LaLiga 2026/27, verified 2026-10-06** against football-data.org v4,
worldfootball.net and laliga.com:

```
380 fixtures | 69 finished | 270 scheduled | 41 timed
matchdays 1-7 complete; matchday 8 upcoming (9-12 Oct)
18 teams on 7 games, 2 on 6 games  ->  69 matches
season span 2026-08-15 .. 2027-05-30
```

Barcelona 7 played / 21 pts, Atlético 16, Betis 16, Real Madrid 15.

---

## Standing rules

1. A partial provider response must never be written as a complete season.
   `fully_received` is an assertion about the whole season, not about the
   response.
2. `DATA_PROVIDER` stays configured to football-data for complete full season schedules.
3. Restore from `git`, then re-ingest. Never hand-edit a store.
4. Two independent human sources, minimum, before declaring real data falsified.
5. Any provider window smaller than the full season is suspect on sight — a
   league season is hundreds of fixtures, not seven.
6. When in doubt, report it. A falsified store found late is an incident; one
   reported immediately is a footnote.
