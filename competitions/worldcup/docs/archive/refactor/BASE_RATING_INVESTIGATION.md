# BASE_RATING Investigation

## Finding

**`BASE_RATING` does not exist in the codebase.** Not in `src/`, not in `tests/`, not in any plan or roadmap document. The name is absent from the repository entirely.

## What Actually Exists

Only **two** module-level constants are truly duplicated (same name, same value, independently defined in two places):

| Constant | File | Line | Value | Also in |
|----------|------|------|-------|---------|
| `COLD_START_THRESHOLD` | `src/blender.py` | 20 | `30` | `src/constants.py` line 199 |
| `BRIER_WINDOW_SIZE` | `src/blender.py` | 21 | `50` | `src/constants.py` line 203 |

Both are defined in `blender.py` **before** `constants.py` gained its own versions (WP-1). `blender.py` never imports them from `constants.py` — it keeps its own independent copies.

## Why the Two Duplicates Exist

`blender.py` was created before the constants were centralized in WP-1. These two constants were originally defined only in `blender.py`. When `constants.py` was populated, the same values were added there, but the originals in `blender.py` were never removed. The `blender.py` versions are now dead code — the module also imports and uses the `constants.py` versions via `from src import constants`.

Note: `groups.py`'s `MAX_EXPECTED_GOALS = constants.MAX_EXPECTED_GOALS` is a re-export alias, not a duplicate.

## Conclusion

The roadmap's hypothetical `BASE_RATING` never existed. The actual out-of-date references are:

| Reference | Reality |
|-----------|---------|
| Roadmap line 65: `groups.py:14` → `MAX_EXPECTED_GOALS` | Already centralized (imports from `constants.py`) |
| Roadmap's missing: `blender.py:20-21` → `COLD_START_THRESHOLD`, `BRIER_WINDOW_SIZE` | **Not** in roadmap — oversight |
| Plan's `BASE_RATING` | Name not found — likely refers to no actual constant |

**Recommended action:** Remove the `blender.py` duplicates of `COLD_START_THRESHOLD` and `BRIER_WINDOW_SIZE`, and have `blender.py` import them from `constants.py` instead. This aligns with WP-1's intent and is the mechanical cleanup that was missed.
