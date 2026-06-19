# Plan 17-01: Enrichment Core Module — Summary

**Status:** ✅ Complete

## What was built

Created `src/enrichment.py` with:

- `_STATS_FIELD_MAP` — 8 entries mapping internal names (e.g. `yellow_cards_home`) to BSD leaf field names (e.g. `yellow_cards`), following the fallback-chain tuple pattern from catboost.py (D-11)
- `_CONTEXT_SOURCE_MAP` — 2 entries mapping `venue`/`referee` to `(source_key, sub_key)` tuples for top-level extraction
- `_resolve_field()` — helper that tries fallback chains with type coercion (int/str)
- `extract_stats(raw_event)` — navigates `live_stats.home`/`live_stats.away`, returns dict with up to 8 stat fields, None when `live_stats` absent (D-06 optional keys, D-07 sparse fields)
- `extract_context(raw_event)` — extracts venue name and referee name from top-level dicts, returns partial dict when only one resolves, None when both absent

## Key decisions

- Stat field names stored as leaf names only; parent path navigation happens in `extract_stats()` — avoids duplicating `live_stats.home/away` path for every field
- Context fields extracted from top-level `venue`/`referee` dicts (not under `live_stats`) via `_CONTEXT_SOURCE_MAP` tuples
- Coach data deferred to P1/stretch despite being always available — kept P0 scope tight

## Acceptances met

- [x] Module importable without errors
- [x] `extract_stats()` returns all 8 stat fields from finished BSD event
- [x] `extract_stats()` returns None when live_stats=None
- [x] `extract_stats()` returns partial dict for sparse data (only possession fields)
- [x] `extract_context()` returns both venue and referee
- [x] `extract_context()` returns None when both source dicts None
- [x] `extract_context()` returns partial dict when only venue or only referee present
- [x] Possession values stored as int, not float/str
- [x] All output values Python native types — no BSD dict objects leak
