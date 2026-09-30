"""Behaviour locks for the shared historical-backfill kernel.

`football_core/historical_backfill.py` absorbed the logic that UCL and LaLiga
each used to carry in their own `historical_backfill/` packages. The
`competitions/*/historical_backfill/*` modules are now thin wrappers, so these
tests pin the kernel to the *original* construction semantics (rebuilt here
from the pre-refactor implementations) rather than to the refactor's own code.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata

import numpy as np
import pytest

from football_core import historical_backfill as shared
from football_core.evaluation import multi_class_brier

# ── reference implementations copied from the pre-refactor modules ──

_SPECIAL_FOLDS = {
    "ß": "ss", "ø": "o", "æ": "ae", "œ": "oe",
    "ł": "l", "đ": "d", "ı": "i",
}
_TAG_RE = re.compile(r"\s*\([a-z]{3}\)\s*$")
_WS_RE = re.compile(r"\s+")


def _plain(text: str) -> str:
    return text.strip().lower()


def _normalize(text: str) -> str:
    s = text.strip().lower()
    s = _TAG_RE.sub("", s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    for src, dst in _SPECIAL_FOLDS.items():
        s = s.replace(src, dst)
    return _WS_RE.sub(" ", s).strip()


def reference_tables(aliases_file, curated, added, long_form=None):
    """The original team_map._build() + canonical_map construction, verbatim."""
    long_form = long_form or {}
    with open(aliases_file, encoding="utf-8") as f:
        raw = json.load(f)

    def prefer(orig, keys):
        pinned = long_form.get(orig)
        if pinned is not None and pinned in keys:
            return pinned
        return max(keys, key=len)

    alias_to_keys: dict[str, list[str]] = {}
    for canon in raw:
        alias_to_keys.setdefault(_plain(canon), []).append(canon)
        for alias in raw[canon]:
            alias_to_keys.setdefault(_plain(alias), []).append(canon)

    alias_rev: dict[str, str] = {}
    for canon in raw:
        for alias in raw[canon]:
            alias_rev[_plain(alias)] = prefer(alias, alias_to_keys[_plain(alias)])
        alias_rev[_plain(canon)] = prefer(canon, alias_to_keys[_plain(canon)])

    curated_rev = {_plain(s): c for s, c in curated.items()}

    canonical_set: set[str] = set()
    canonical_set.update(alias_rev.values())
    canonical_set.update(raw)
    canonical_set.update(added)
    canonical_keys = sorted(canonical_set)

    norm_rev: dict[str, str] = {}
    for canon in canonical_keys:
        norm_rev.setdefault(_normalize(canon), canon)
    for canon in raw:
        for alias in raw[canon]:
            norm_rev.setdefault(_normalize(alias), prefer(alias, alias_to_keys[_plain(alias)]))
    for source, canon in curated.items():
        norm_rev.setdefault(_normalize(source), canon)

    def resolve(team):
        plain = _plain(team)
        if not plain:
            return None
        key = alias_rev.get(plain)
        if key is not None:
            return key
        key = curated_rev.get(plain)
        if key is not None:
            return key
        norm = _normalize(team)
        if not norm:
            return None
        return norm_rev.get(norm)

    def canonical(team):
        if not isinstance(team, str) or not team.strip():
            raise KeyError(f"cannot canonicalise empty team key: {team!r}")
        key = resolve(team)
        if key is None:
            raise KeyError(f"unmapped team key: {team!r}")
        return key

    canonical_map: dict[str, str] = {}
    for canon in raw:
        for alias in raw[canon]:
            canonical_map[alias] = canonical(alias)
    for source, canon in curated.items():
        canonical_map[source] = canon
    for key in canonical_keys:
        canonical_map[key] = canonical(key)

    return {
        "ALIAS_REV": alias_rev, "CURATED_REV": curated_rev,
        "CANONICAL_KEYS": canonical_keys, "NORM_REV": norm_rev,
        "canonical_map": canonical_map, "canonical": canonical,
    }


def reference_ece_points(conf, hit, n_bins=10):
    ece = 0.0
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        mask = ((conf >= lo) & (conf < hi)) | ((b == n_bins - 1) & (conf == 1.0))
        cnt = int(mask.sum())
        if cnt == 0:
            continue
        ece += (cnt / conf.size) * abs(float(conf[mask].mean()) - float(hit[mask].sum() / cnt))
    return ece


# ── team-key tables: identical to the pre-refactor construction ──

CASES = [
    pytest.param(
        "competitions.ucl.historical_backfill.team_map", id="ucl",
    ),
    pytest.param(
        "competitions.laliga.historical_backfill.team_map", id="laliga",
    ),
]


@pytest.mark.parametrize("module_name", CASES)
def test_team_key_tables_match_pre_refactor_construction(module_name):
    import importlib

    mod = importlib.import_module(module_name)
    ref = reference_tables(
        mod._ALIASES_FILE, mod._CURATED, mod._ADDED_CANONICAL_KEYS,
        getattr(mod, "_LONG_FORM", None),
    )
    assert mod.ALIAS_REV == ref["ALIAS_REV"]
    assert mod.CURATED_REV == ref["CURATED_REV"]
    assert mod.CANONICAL_KEYS == ref["CANONICAL_KEYS"]
    assert mod.NORM_REV == ref["NORM_REV"]
    # order-sensitive: provenance/reporting iterates canonical_map in order
    assert list(mod.canonical_map.items()) == list(ref["canonical_map"].items())


@pytest.mark.parametrize("module_name", CASES)
def test_every_table_key_resolves_the_same_way(module_name):
    import importlib

    mod = importlib.import_module(module_name)
    for table in (mod.ALIAS_REV, mod.CURATED_REV, mod.NORM_REV):
        for probe in table:
            ref = mod.canonical(probe)
            assert mod.is_known(probe)
            assert ref == mod.canonical(ref), f"{probe!r} not direction-consistent"


# ── storage / contract helpers ──

def test_write_json_is_atomic_and_returns_sha256(tmp_path):
    import hashlib

    path = str(tmp_path / "nested" / "x.json")
    digest = shared.write_json(path, {"b": 1, "a": "é"})
    with open(path, "rb") as f:
        raw = f.read()
    assert digest == hashlib.sha256(raw).hexdigest()
    assert raw.decode("utf-8").endswith("\n")
    assert shared.read_json(path) == {"b": 1, "a": "é"}
    assert not os.path.exists(path + ".tmp")


def test_duplicate_keys_preserves_first_seen_order():
    matches = [{"match_id": "a"}, {"match_id": "b"}, {"match_id": "a"},
               {"match_id": "c"}, {"match_id": "c"}, {}]
    assert shared.duplicate_keys(matches) == ["a", "c"]


def test_season_paths_and_year_key():
    assert shared.season_path("/d", "2020_21", "matches.json") == os.path.join(
        "/d", "2020_21", "matches.json")
    assert shared.season_dir("/d", "2020_21") == os.path.join("/d", "2020_21")
    assert shared.year_key("2020_21") == 2020


# ── metrics helpers ──

def test_renormalize_drops_zero_and_non_subset():
    raw = {"market_odds": 0.2, "refined_elo": 0.4, "squad_value": 0.4,
           "rest_days": 0.0}
    assert shared.renormalize(raw, ["market_odds", "refined_elo"]) == {
        "market_odds": 1 / 3, "refined_elo": 2 / 3}
    assert shared.renormalize(raw, ["rest_days"]) == {}


def test_completed_indices_skips_incomplete_and_uses_uniform_placeholder():
    matches = [{"i": 0}, {"i": None}, {"i": 1}]
    probs, actuals, completed = shared.completed_indices(matches, lambda m: m["i"])
    assert probs == [[1 / 3, 1 / 3, 1 / 3]] * 2
    assert actuals == [0, 1]
    assert [m["i"] for m in completed] == [0, 1]


def test_metrics_from_empty_is_n_zero():
    assert shared.metrics_from([], []) == {"n": 0}


def test_uniform_metrics_and_has_odds():
    matches = [{"i": 0, "odds_home": 1.0, "odds_draw": 2.0, "odds_away": 3.0},
               {"i": 1, "odds_home": 1.0}]
    assert shared.has_odds(matches[0]) is True
    assert shared.has_odds(matches[1]) is False
    assert shared.has_odds({}) is False
    um = shared.uniform_metrics(matches, lambda m: m["i"])
    assert um["n"] == 2
    assert um["uniform_log_loss"] == pytest.approx(round(np.log(3), 6))
    assert um["uniform_brier"] == pytest.approx(
        round(multi_class_brier([[1 / 3] * 3] * 2, [0, 1]), 6))
    assert shared.uniform_metrics([{"i": None}], lambda m: m["i"]) is None


def test_freq_metrics_on_uses_prior_frequency_vector():
    m = shared.metrics_from([[0.6, 0.3, 0.1], [0.6, 0.3, 0.1]], [0, 1])
    out = shared.freq_metrics_on({"home": 0.6, "draw": 0.3, "away": 0.1},
                                 [{"i": 0}, {"i": 1}], lambda x: x["i"])
    assert out == m
    assert shared.freq_metrics_on({"home": 1.0, "draw": 0, "away": 0},
                                  [{"i": None}], lambda x: x["i"]) is None


def test_first_date_is_earliest_event_date():
    assert shared.first_date([{"event_date": "2020-01-02"},
                              {"event_date": "2019-05-06"}]) == "2019-05-06"
    # a missing date collapses to "" and therefore wins the min (unchanged)
    assert shared.first_date([{"event_date": "2020-01-02"},
                              {"event_date": None}]) == ""


# ── bootstrap primitives ──

def test_per_match_arrays_match_closed_form():
    probs = [[0.7, 0.2, 0.1], [0.2, 0.5, 0.3]]
    c = shared.per_match(probs, [0, 1])
    assert c["n"] == 2
    assert c["ll"] == pytest.approx([-np.log(0.7), -np.log(0.5)])
    assert c["brier"][0] == pytest.approx(0.3 ** 2 + 0.2 ** 2 + 0.1 ** 2)
    assert list(c["conf"]) == [0.7, 0.5]
    assert list(c["hit"]) == [True, True]


def test_cache_merge_concatenates_and_counts():
    cache: dict = {}
    shared.cache_merge(cache, "m", [[0.7, 0.2, 0.1]], [0])
    shared.cache_merge(cache, "m", [[0.2, 0.5, 0.3]], [1])
    assert cache["m"]["n"] == 2
    assert len(cache["m"]["ll"]) == 2
    shared.cache_merge(cache, "other", [[0.34, 0.33, 0.33]], [0])
    assert set(cache) == {"m", "other"}


def test_ece_points_matches_pre_refactor_formula_and_pins_confidence_one():
    conf = np.array([0.3, 0.55, 1.0, 0.95])
    hit = np.array([True, False, True, True])
    assert shared.ece_points(conf, hit) == pytest.approx(reference_ece_points(conf, hit))
    # every confidence exactly 1.0 must land in the last bin, not drop out
    only_one = np.array([1.0, 1.0])
    assert shared.ece_points(only_one, np.array([True, False])) == pytest.approx(0.5)


# ── build-time validation ──

def test_validate_season_reports_duplicates_and_missing_elo():
    matches = [
        {"match_id": "a", "team_a": "X", "team_b": "Y", "event_date": "2020-01-01",
         "odds_home": 1.0, "odds_draw": 2.0, "odds_away": 3.0},
        {"match_id": "a", "team_a": "Y", "team_b": "Z", "event_date": "2020-06-01"},
    ]
    check = shared.validate_season("2020_21", matches, {"X": 1600.0})
    assert check["n_matches"] == 2
    assert check["duplicate_match_ids"] == ["a"]
    assert check["n_teams"] == 3
    assert check["elo_missing_teams"] == ["Y", "Z"]
    assert check["n_odds"] == 1
    assert (check["min_date"], check["max_date"]) == ("2020-01-01", "2020-06-01")


def test_assert_season_clean_raises_only_on_duplicates(capsys):
    shared.assert_season_clean("2020_21", {"duplicate_match_ids": [],
                                           "elo_missing_teams": ["Q"]})
    assert "WARNING 2020_21" in capsys.readouterr().out
    with pytest.raises(AssertionError, match="duplicate match ids"):
        shared.assert_season_clean("2020_21", {"duplicate_match_ids": ["a"],
                                               "elo_missing_teams": []})


def test_used_elo_map_is_trimmed_and_sorted():
    matches = [{"team_a": "B", "team_b": "A"}, {"team_a": "C", "team_b": "A"}]
    assert list(shared.used_elo_map({"B": 1.0, "A": 2.0, "Z": 9.0}, matches)) == ["A", "B"]


def test_summarize_replay_counts_odds_coverage():
    matches = [{"odds_home": 1, "odds_draw": 2, "odds_away": 3}, {}]
    assert shared.summarize_replay(matches) == {
        "n_matches": 2, "n_matches_with_odds": 1, "odds_coverage": 0.5}
    assert shared.summarize_replay([])["odds_coverage"] is None
