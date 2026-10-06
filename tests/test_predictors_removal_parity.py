"""Live before/after parity for the deprecated-predictors deletion (plan 01-06).

Both sides of every comparison are computed inside this one run -- this is
deliberately **not** a frozen golden (the frozen golden bracket has its own
test in ``test_wc_bracket_golden.py``).

"Before" does not mean "the deleted code"; D-16 forbids archiving it. It means
the *observable effect* the deletion removed: the four signal-cache files that
``fetch_live_data`` used to write. The caches are rebuilt here by driving the
kernel signal classes the deleted adapters delegated to (``RestDaysSignal``,
``RollingFormSignal``, ``SquadValueSignal``) plus the kernel odds layer the
fourth adapter was a pure pass-through for. "After" is simply the current code
with no producer at all.

Both data directories are independent copies of the committed fixtures under
``tests/fixtures/wc_bracket/``. ``competitions/worldcup/data/`` is only partly
tracked, is never read here, and no network or API key is touched, so this
suite reproduces identically on a clean clone.

Case 4 is the load-bearing one: if the harness cannot tell the two paths apart
even when the caches exist, then Cases 1-3 are vacuous and this suite is
reporting a tautology rather than parity.
"""

from __future__ import annotations

import importlib
import json
import shutil
from pathlib import Path

import pytest

from football_core.predictors.odds import fetch_and_cache_odds
from football_core.signal import PredictionContext
from football_core.signals.rest_days import RestDaysSignal
from football_core.signals.rolling_form import RollingFormSignal
from football_core.signals.squad_value import SquadValueSignal

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures" / "wc_bracket"
WEIGHTS_FILE = (
    ROOT.parent / "competitions" / "worldcup" / "config" / "signal_weights.json"
)

# The four files the deleted stage wrote, in the order it wrote them.
CACHE_FILES = (
    "odds_cache.json",
    "rolling_form_cache.json",
    "squad_value_cache.json",
    "rest_days_cache.json",
)

# Nothing reads cache freshness (``load_signal_cache`` has no TTL check), but a
# fixed timestamp keeps the produced caches byte-deterministic.
FIXED_TS = "2000-01-01T00:00:00+00:00"

SIGNAL_KEYS = ("elo", "market_odds", "rolling_form", "squad_value", "rest_days")


# --------------------------------------------------------------------------
# fixtures / harness
# --------------------------------------------------------------------------

def _load(data_dir: Path, name: str):
    return json.loads((data_dir / name).read_text(encoding="utf-8"))


def _state(data_dir: Path) -> dict:
    """Load the six committed fixture files from one data directory."""
    groups_raw = _load(data_dir, "groups.json")
    return {
        "groups_raw": groups_raw,
        "groups": groups_raw.get("groups", groups_raw),
        "teams": _load(data_dir, "teams.json"),
        "bracket": _load(data_dir, "bracket.json"),
        "annex_c": _load(data_dir, "annex_c.json"),
        "played": _load(data_dir, "played.json"),
        "played_groups": _load(data_dir, "played_groups.json"),
    }


def _engine_matches(state: dict) -> list[dict]:
    """Group fixtures + every bracket entry, mirroring ``run_simulation_compute``."""
    matches: list[dict] = []
    for group in state["groups"].values():
        matches.extend(group.get("matches", []))
    matches.extend(state["bracket"])
    return matches


def _signal_matches(state: dict) -> list[dict]:
    """Group fixtures + *resolved* bracket entries, as the deleted adapters did."""
    matches: list[dict] = []
    for group in state["groups"].values():
        matches.extend(group.get("matches", []))
    matches.extend(
        m for m in state["bracket"]
        if m.get("team_a") is not None and m.get("team_b") is not None
    )
    return matches


def _outputs(data_dir: Path) -> dict:
    """The three canonical outputs, computed from one data directory.

    Standings and probabilities are separate outputs because only the second
    one reads the caches; the bracket is computed with engine predictions so
    its ``signals`` blocks exercise the same path.
    """
    from competitions.worldcup.src.bracket import compute_full_bracket
    from competitions.worldcup.src.engine import build_engine_from_caches
    from competitions.worldcup.src.overview import compute_real_standings

    state = _state(data_dir)
    standings = compute_real_standings(state["groups"], state["played_groups"])

    engine = build_engine_from_caches(data_dir=data_dir)
    matches = _engine_matches(state)
    context = PredictionContext(
        fixtures=matches,
        elo_ratings={name: data["elo"] for name, data in state["teams"].items()},
        played_results=list(state["played"].values())
        + list(state["played_groups"].values()),
    )
    predictions = [engine.evaluate(m, context) for m in matches]
    probabilities = [
        (p.home_prob, p.draw_prob, p.away_prob) for p in predictions
    ]

    bracket_payload = compute_full_bracket(
        state["groups_raw"],
        state["teams"],
        state["bracket"],
        state["annex_c"],
        state["played"],
        state["played_groups"],
        predictions,
    )
    return {
        "standings": standings,
        "probabilities": probabilities,
        "bracket": bracket_payload,
    }


def _fresh_dir(root: Path, name: str) -> Path:
    target = root / name
    target.mkdir(parents=True)
    for fixture in FIXTURES.glob("*.json"):
        if fixture.name == "golden_bracket.json":
            continue
        shutil.copy(fixture, target / fixture.name)
    return target


def _pair(root: Path, produce_caches: bool) -> dict:
    """Build two independent copies of the fixtures and run the harness on both.

    ``produce_caches`` writes the four caches into the before-directory only --
    that is the entire difference between the two paths.
    """
    before = _fresh_dir(root, "before")
    after = _fresh_dir(root, "after")
    if produce_caches:
        _write_deleted_stage_caches(before)
    return {
        "before": _outputs(before),
        "after": _outputs(after),
        "before_dir": before,
        "after_dir": after,
    }


# --------------------------------------------------------------------------
# the "before" path: caches rebuilt from the kernel signal classes
# --------------------------------------------------------------------------

def _clamp(value: float) -> float:
    return max(1e-15, min(1 - 1e-15, value))


def _wrap(matches: dict) -> dict:
    return {"fetched_at": FIXED_TS, "expires_at": FIXED_TS, "matches": matches}


def _available(probability: float, draw: float) -> dict:
    return {
        "probability": _clamp(probability),
        "draw_probability": draw,
        "timestamp": FIXED_TS,
        "available": True,
    }


def _unavailable(reason: str) -> dict:
    return {
        "probability": None,
        "timestamp": FIXED_TS,
        "available": False,
        "reason": reason,
    }


def _match_date(match: dict) -> str | None:
    return match.get("event_date") or match.get("date") or match.get("completed_at")


class _FixtureResultsProvider:
    """``ResultHistoryProvider`` over the committed played fixtures.

    ``RollingFormSignal`` takes historical results through this protocol
    (``football_core/provider.py``) instead of reading a store itself, so any
    caller must supply an implementation. Rows are indexed by team and ordered
    most-recent-first, which is the order the signal's stable sort relies on
    when a match carries no ``event_date``.
    """

    def __init__(self, played: dict, played_groups: dict) -> None:
        self._by_team: dict[str, list[dict]] = {}
        for match in list(played.values()) + list(played_groups.values()):
            if not isinstance(match, dict):
                continue
            for team in (match.get("team_a"), match.get("team_b")):
                if team:
                    self._by_team.setdefault(team, []).append(
                        {
                            "winner": match.get("winner"),
                            "is_draw": match.get("is_draw", False),
                            "completed_at": match.get("completed_at", ""),
                        }
                    )
        for rows in self._by_team.values():
            rows.sort(key=lambda r: r.get("completed_at", ""), reverse=True)

    def get_team_results(
        self, team: str, before_date: str, limit: int = 10
    ) -> list[dict]:
        rows = [
            r for r in self._by_team.get(team, [])
            if r.get("completed_at", "") < before_date
        ]
        return rows[:limit]


def _rest_days_cache(matches: list[dict], context: PredictionContext) -> dict:
    signal = RestDaysSignal()
    entries: dict[str, dict] = {}
    for match in matches:
        mid = match.get("match_id")
        if not mid:
            continue
        if not _match_date(match):
            entries[mid] = _unavailable("no_date_info")
            continue
        try:
            out = signal.predict(match, context)
            entries[mid] = _available(out.home_prob, out.draw_prob)
        except Exception:
            entries[mid] = _unavailable("error")
    return _wrap(entries)


def _rolling_form_cache(
    matches: list[dict], provider: _FixtureResultsProvider
) -> dict:
    signal = RollingFormSignal(
        result_provider=provider, windows=[5], decay_factor=0.9
    )
    context = PredictionContext(fixtures=list(matches), elo_ratings={})
    entries: dict[str, dict] = {}
    for match in matches:
        mid = match.get("match_id")
        if not mid:
            continue
        try:
            out = signal.predict(match, context)
            entries[mid] = _available(out.home_prob, out.draw_prob)
        except Exception:
            entries[mid] = _unavailable("error")
    return _wrap(entries)


def _squad_value_cache(
    matches: list[dict], team_values: dict
) -> dict:
    signal = SquadValueSignal()
    context = PredictionContext(
        fixtures=list(matches), elo_ratings={}, squad_values=team_values
    )
    entries: dict[str, dict] = {}
    for match in matches:
        mid = match.get("match_id")
        if not mid:
            continue
        team_a = match.get("team_a", "")
        team_b = match.get("team_b", "")
        if team_a not in team_values:
            entries[mid] = _unavailable(f"team_value_not_found: {team_a}")
            continue
        if team_b not in team_values:
            entries[mid] = _unavailable(f"team_value_not_found: {team_b}")
            continue
        try:
            out = signal.predict(match, context)
            entries[mid] = _available(out.home_prob, out.draw_prob)
        except Exception:
            entries[mid] = _unavailable("error")
    return _wrap(entries)


def _odds_cache(state: dict) -> dict:
    """Kernel odds layer the deleted adapter was a pure pass-through for.

    ``fetch_and_cache_odds`` parses events it is handed; it never fetches.
    Handing it the empty event list reproduces the offline / no-BSD condition
    the stage actually ran under, so this makes no network call of any kind.
    """
    return fetch_and_cache_odds(
        "",
        [],
        {},
        state["groups_raw"],
        bracket=state["bracket"],
    )


def _write_deleted_stage_caches(data_dir: Path) -> None:
    """Reproduce the effect the deleted signal-fetch stage had on disk.

    The stage and its ``src.predictors`` adapters are gone (Case 5 proves it);
    what they left behind was four cache files in the competition data
    directory. This writes exactly those four files, from the kernel signal
    classes the adapters delegated to, using only committed fixture data --
    ``team_values.json`` is not a committed fixture, so squad-value entries are
    unavailable here exactly as they are on a clean clone.
    """
    from src.state import save_signal_cache

    state = _state(data_dir)
    matches = _signal_matches(state)
    provider = _FixtureResultsProvider(state["played"], state["played_groups"])
    team_values_path = data_dir / "team_values.json"
    team_values = (
        json.loads(team_values_path.read_text(encoding="utf-8"))
        if team_values_path.exists()
        else {}
    )

    save_signal_cache(_odds_cache(state), "odds_cache.json", data_dir)
    save_signal_cache(
        _rolling_form_cache(matches, provider), "rolling_form_cache.json", data_dir
    )
    save_signal_cache(
        _squad_value_cache(matches, team_values), "squad_value_cache.json", data_dir
    )
    save_signal_cache(
        _rest_days_cache(
            matches, PredictionContext(fixtures=list(matches), elo_ratings={})
        ),
        "rest_days_cache.json",
        data_dir,
    )


# --------------------------------------------------------------------------
# shared state (module-scoped: each pair is built once)
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cache_free_pair(tmp_path_factory) -> dict:
    """Both paths with no cache on disk -- the condition the repo is in now."""
    root = tmp_path_factory.mktemp("parity_nocache")
    return _pair(root, produce_caches=False)


@pytest.fixture(scope="module")
def cached_pair(tmp_path_factory) -> dict:
    """before = caches written by the producers, after = no producer."""
    root = tmp_path_factory.mktemp("parity_cache")
    return _pair(root, produce_caches=True)


# --------------------------------------------------------------------------
# Cases 1-3: parity under the real (cache-free) condition
# --------------------------------------------------------------------------

def test_case_1_standings_identical_with_caches_absent(cache_free_pair):
    """Case 1 -- the canonical standings do not move with the deletion."""
    before, after = cache_free_pair["before"], cache_free_pair["after"]
    assert before["standings"] == after["standings"]
    assert before["standings"], "harness produced no standings at all"


def test_case_2_probabilities_identical_with_caches_absent(cache_free_pair):
    """Case 2 -- every per-match probability vector is unchanged."""
    before, after = cache_free_pair["before"], cache_free_pair["after"]
    assert len(before["probabilities"]) == len(after["probabilities"])
    assert before["probabilities"] == after["probabilities"]
    assert len(before["probabilities"]) > 1, "harness evaluated too few matches"


def test_case_3_bracket_structurally_identical_with_caches_absent(
    cache_free_pair,
):
    """Case 3 -- the bracket payload is compared as structure, not as text."""
    before, after = cache_free_pair["before"], cache_free_pair["after"]
    assert before["bracket"] == after["bracket"]
    assert before["bracket"].get("rounds"), "harness produced an empty bracket"


# --------------------------------------------------------------------------
# Case 4: the sensitivity check that makes Cases 1-3 worth anything
# --------------------------------------------------------------------------

def test_case_4_harness_detects_difference_when_caches_exist(cached_pair):
    """Case 4 -- with the caches present the same harness reports inequality.

    If this fails, Cases 1-3 are vacuous: the harness would be blind to the
    very inputs the deletion removed. The assertion is deliberately on the
    whole output bundle -- standings are cache-independent by construction,
    so asserting on them alone would be meaningless.
    """
    before = cached_pair["before"]
    after = cached_pair["after"]
    assert before != after, (
        "harness is insensitive to the signal caches -- parity tests are vacuous"
    )
    # ...and the sensitivity must come from the probabilities, which are the
    # one output that actually reads the caches.
    assert before["probabilities"] != after["probabilities"]
    # Standings remain equal even with caches present: no cache feeds them.
    assert before["standings"] == after["standings"]
    # The only difference between the two directories is the four files.
    assert all((cached_pair["before_dir"] / f).exists() for f in CACHE_FILES)
    assert not any((cached_pair["after_dir"] / f).exists() for f in CACHE_FILES)


# --------------------------------------------------------------------------
# Cases 5-6: the deletion and the weights file are both real and untouched
# --------------------------------------------------------------------------

def test_case_5_deletion_is_real_no_compatibility_shim():
    """Case 5 -- the package is gone for real, not shadowed by a stub."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("competitions.worldcup.src.predictors.odds")
    assert not (ROOT.parent / "competitions" / "worldcup" / "src" / "predictors").exists()


def test_case_6_signal_weights_untouched_uniform_five():
    """Case 6 -- D-21: five signals at uniform 0.2, rewritten by nobody."""
    payload = json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))
    weights = payload["weights"]
    assert tuple(sorted(weights)) == tuple(sorted(SIGNAL_KEYS))
    assert all(weights[key] == 0.2 for key in SIGNAL_KEYS), weights
