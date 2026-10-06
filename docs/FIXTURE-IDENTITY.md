# Fixture identity

## Purpose

Each competition derives fixture ids with its own contract, so one match keeps
a single stable identity across every ingest path and no competition's ids
collide with another's.

## Status: deliberately NOT unified

There are three `derive_fixture_id` functions in this repository and they are
**not** going to be merged.

The reason is not that unification is impossible. It is that fixture ids are the
primary keys of persisted stores — `competitions/*/data/seasons/*/{fixtures,results}.json`.
Changing a derivation does not raise an error; it orphans every record already on
disk while the pipeline keeps reporting success. A unification is therefore a data
migration wearing the costume of a refactor — the kind of edit that lands at 02:00
with no migration budgeted for it.

Unification is explicitly deferred per `REQUIREMENTS.md` ("Out of Scope"), and
decision D-28 records why: Phase 5's retirement granularity depends on fixture
identity being **per competition**, so the World Cup can retire per match while
UCL and LaLiga ship whole-snapshot retirement. Coarse, but never mis-retiring.

If you are reading this while thinking "these are obviously the same function three
times", you have found the one change this contract exists to stop.

## The three signatures

| Module | Signature | Output | Hash basis |
|---|---|---|---|
| `football_core/seasons.py:44` | `(namespace, home, away)` | 16 lowercase hex chars, no prefix | `sha256(f"{namespace}\n{home}\n{away}")[:16]` |
| `competitions/ucl/src/seasons.py:289` | `(home_team, away_team, event_date)` | `"gen-"` + 16 hex chars | `sha256("ucl-season-fixture\n{home}\n{away}")[:16]` — namespace **hardcoded**, `event_date` **ignored** |
| `competitions/laliga/src/seasons.py:22` | `(home, away)` | 16 hex chars, no prefix (delegates) | the kernel, called with LaLiga's `SEASON_NAMESPACE` |
| `competitions/worldcup/src` | **none** | n/a | a fixed tournament bracket, not a repeated home/away season |

Two details in that table are easy to miss. UCL does **not** call the kernel — it
has its own implementation that hardcodes the string `"ucl-season-fixture"`, which
is not a named constant anywhere and so needs pinning like any other value. LaLiga
**does** delegate: its wrapper is the kernel plus a namespace, so its id shape is
the kernel's and it will change if the kernel's does.

The World Cup's absence is a decision, not an oversight. A bracket fixture's
identity is its stage plus its slot, not a team pairing, so there is no
`(home, away)` relationship to hash. Its successor is Phase 5, which reconciles
World Cup matches per match through the shared fixture vocabulary in
`football_core.domain` — not a fourth `derive_fixture_id`.

## Why the date is excluded

This is the load-bearing rationale. A postponed match keeps the same `(home, away)`
relationship. The relationship is the fixture; the date is a scheduling attribute
about it, and scheduling attributes change. If the date were in the hash, one
postponement would give the match a new identity, orphaning the record it had
already been ingested as.

UCL depends on this. `competitions/ucl/src/season_draw.py:161` writes the
provisional drawn fixture as `derive_fixture_id(home, away, None)`, and
`competitions/ucl/src/ingest.py:1158` later receives the official dated fixture
list for the same matchups. Because the two produce **the same id**, the official
events *update* the drawn rows in place — id, provenance and metadata preserved —
instead of being appended as duplicates of matches already on file.

The draw proposes who plays whom; the fixture confirms it. They are one identity,
not two. A "the date should be part of the id" change looks like a correctness
improvement and silently breaks both halves of that.

## Why `home` and `away` are ordered

They are positions in a fixture, not an unordered pair. "Manchester City v Real
Madrid" and "Real Madrid v Manchester City" are two different matches sharing two
teams, and only the first is at a neutral venue. A "normalisation" that sorted the
two would merge every fixture with its reverse fixture — in a double round-robin,
exactly the two fixtures of a pair, half the season.

## Stability rules

- Do **not** change the hash input format, the digest length, the `"gen-"`
  prefix, or any namespace value.
- Do **not** add a date component.
- Do **not** sort or normalise the team names or their positions.
- Any genuine format change needs a **store migration**, not an edit to these
  functions. UCL's league phase and LaLiga's season are persisted under these
  ids; a silent re-derivation does not migrate them, it orphans them.

A namespace change is the same class of edit as a hash change, and the two are
easy to confuse: `"laliga-season-fixture"` looks like an implementation detail of
LaLiga rather than part of every id LaLiga has ever written.

## Worked examples

The worked vector this contract is pinned on. These are asserted as literals by
the tests, not re-derived from the implementation:

```
("ucl-season-fixture", "Manchester City", "Real Madrid")  ->  88e56f07916e27e1
UCL wrapper, same teams, any date or None                ->  gen-88e56f07916e27e1
UCL wrapper, reversed teams                              ->  gen-e4e36ce7b6753960
```

Rows 1 and 2 share their 16 hex chars: the UCL wrapper is the kernel with a
constant namespace plus a prefix. Row 3 is a different match, not a different
encoding of row 1.

## Where it lives

| Competition | Implementation |
|---|---|
| Generic kernel | `football_core/seasons.py` |
| UCL | `competitions/ucl/src/seasons.py` (private implementation; call sites in `src/season_draw.py` and `src/ingest.py`) |
| LaLiga | `competitions/laliga/src/seasons.py` (delegating wrapper; namespace in `src/constants.py`) |
| World Cup | none, by decision |
| Executable form | `tests/test_fixture_identity.py` — seven cases: the three signatures, the namespace partition, the ordered positions, the draw/fixture date collision, and the World Cup's absence. If this document and that file ever disagree, the file is the one that fails the build. Line numbers above are as of the commit that introduced this document; the module paths and symbol names are the durable reference. |