"""Phase 11 — LaLiga Historical Evaluation: leakage audit regression tests.

Audits the integrity invariant: only strictly-earlier information may
influence a prediction. A target match must never see itself, same-kickoff
siblings, or any later match.

Reuses the read-only UCL historical primitives re-exported by
``competitions.laliga.src.historical`` and the unmodified
``historical_backfill/evaluate.py`` evaluation window construction.
"""
from __future__ import annotations

import json
import os
import re

import pytest

from football_core.signals.market_odds import MarketOddsSignal
from football_core.signals.refined_elo import RefinedEloSignal
from football_core.signals.rest_days import RestDaysSignal
from football_core.signals.rolling_form import RollingFormSignal

from competitions.laliga.src.historical import (
    ReplayResultProvider,
    build_context_for_match,
    frequency_baseline,
    order_matches,
    prior_matches,
)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
HISTORICAL_DIR = os.path.join(REPO, "competitions", "laliga", "data", "historical")
REPLAY_PATH = os.path.join(HISTORICAL_DIR, "replay_2019_20_2023_24.json")

SEASONS = ["2019_20", "2020_21", "2021_22", "2022_23", "2023_24"]
N_PER_SEASON = 380  # 20-team double round-robin expansion

_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


# ── data loaders ─────────────────────────────────────────────────────────


def _replay_pool() -> list[dict]:
    with open(REPLAY_PATH) as f:
        return json.load(f)["matches"]


def _season_matches(season: str) -> list[dict]:
    with open(os.path.join(HISTORICAL_DIR, season, "matches.json")) as f:
        return json.load(f)["matches"]


def _season_elo(season: str) -> dict[str, float]:
    with open(os.path.join(HISTORICAL_DIR, season, "elo_ratings.json")) as f:
        return json.load(f)


# ── 1. strict-before across the whole dataset ────────────────────────────


def test_context_is_strictly_before_across_dataset():
    pool = _replay_pool()
    assert len(pool) == 1900
    for m in pool:
        prior = prior_matches(pool, m)
        for p in prior:
            assert p["event_date"] < m["event_date"], (
                m["match_id"], p["event_date"], m["event_date"]
            )
    # per-season context channel (what evaluators actually use)
    for s in SEASONS:
        matches = _season_matches(s)
        elo = _season_elo(s)
        for m in matches:
            ctx = build_context_for_match(m, matches, elo_ratings=elo)
            for f in ctx.fixtures:
                assert f is not m and f["event_date"] < m["event_date"]
            for r in ctx.played_results:
                assert r["event_date"] < m["event_date"]


# ── 2. no same-date matches in context ───────────────────────────────────


def test_no_same_date_matches_in_context():
    pool = _replay_pool()
    for m in pool:
        prior = prior_matches(pool, m)
        assert not any(p["event_date"] == m["event_date"] for p in prior)
    # provider channel: same-kickoff siblings excluded against the anchor
    provider = ReplayResultProvider(order_matches(_season_matches("2022_23")))
    for m in _season_matches("2022_23"):
        rows = provider.get_team_results(m["team_a"], m["event_date"], limit=20)
        assert all(r["event_date"] < m["event_date"] for r in rows)


def test_replay_provider_orders_by_event_date_not_position():
    """Results returned latest-event_date-first regardless of file order."""
    matches = list(reversed(_season_matches("2021_22")))  # scrambled file order
    provider = ReplayResultProvider(matches)
    rows = provider.get_team_results("FC Barcelona", "2023-01-01T00:00:00Z", limit=5)
    assert len(rows) == 5
    dates = [r["event_date"] for r in rows]
    assert dates == sorted(dates, reverse=True)


# ── 3. rest days exclude same-date matches ───────────────────────────────


def test_rest_days_excludes_same_date_match():
    sig = RestDaysSignal()
    target = "2024-03-10T12:00:00Z"
    sibling = {"team_a": "A", "team_b": "C", "event_date": target}
    prior = {"team_a": "A", "team_b": "D", "event_date": "2024-03-01T12:00:00Z"}
    # a same-kickoff sibling must NOT count as a rest opportunity
    assert sig._compute_rest_days("A", target, [sibling]) == 7
    # only strictly-prior matches reduce/inform rest
    assert sig._compute_rest_days("A", target, [sibling, prior]) == 9


# ── 4. market odds: no look-ahead ────────────────────────────────────────


def test_market_odds_no_lookahead():
    pool = _replay_pool()
    for m in pool:
        assert m.get("odds_known_at") == m["event_date"]
    sig = MarketOddsSignal()
    m0 = dict(pool[0])
    bare = sig.predict(m0, type("C", (), {"fixtures": [], "elo_ratings": {}})())
    rich = sig.predict(m0, type("C", (), {"fixtures": pool, "elo_ratings": {}})())
    assert (bare.home_prob, bare.draw_prob, bare.away_prob) == (
        rich.home_prob, rich.draw_prob, rich.away_prob,
    )


# ── 5. rolling form sensitivity ──────────────────────────────────────────


def test_form_changes_after_removing_prior_result():
    pool = _replay_pool()
    changed = 0
    for m in pool[:400]:
        provider = ReplayResultProvider(order_matches(pool))
        sig = RollingFormSignal(result_provider=provider)
        ctx = build_context_for_match(m, pool)
        full = sig.predict(m, ctx)
        last = provider.get_team_results(m["team_a"], m["event_date"], limit=1)
        if not last:
            continue
        dropped = {r["match_id"] for r in last}
        assert all(r["event_date"] < m["event_date"] for r in last)
        reduced = [x for x in pool if x.get("match_id") not in dropped]
        sig2 = RollingFormSignal(result_provider=ReplayResultProvider(order_matches(reduced)))
        alt = sig2.predict(m, ctx)
        if abs(full.home_prob - alt.home_prob) > 1e-9:
            changed += 1
    assert changed > 0, "form must be sensitive to which prior results are visible"


# ── 6. learned weights: strictly prior training seasons ──────────────────


def test_weights_fit_uses_only_prior_seasons():
    # structural: for target SEASONS[i], fit pool is SEASONS[:i] only
    for idx, target in enumerate(SEASONS[1:], start=1):
        prior_seasons = set(SEASONS[:idx])
        assert target not in prior_seasons
        fit_ids: set[str] = set()
        for prev in SEASONS[:idx]:
            fit_ids.update(m["match_id"] for m in _season_matches(prev))
        target_ids = {m["match_id"] for m in _season_matches(target)}
        assert not (fit_ids & target_ids), f"{target}: eval season leaked into fit"
        assert len(fit_ids) == N_PER_SEASON * idx
    # committed fits (when present) recorded the same strictly-prior pool
    ev_path = os.path.join(HISTORICAL_DIR, "evaluation", "eval_results.json")
    if os.path.exists(ev_path):
        with open(ev_path) as f:
            learned = json.load(f)["weights_learned"]["per_season"]
        for idx, target in enumerate(SEASONS[1:], start=1):
            assert learned[target]["train_pool_n"] == N_PER_SEASON * idx


# ── 7. frequency baseline excludes self/later ────────────────────────────


def test_frequency_baseline_excludes_self():
    for s in SEASONS:
        matches = _season_matches(s)
        ordered = order_matches(matches)
        split_at = max(1, int(round(len(ordered) * 0.7)))
        fit, oos = ordered[:split_at], ordered[split_at:]
        fit_ids = {m["match_id"] for m in fit}
        assert not (fit_ids & {m["match_id"] for m in oos})
        freq = frequency_baseline(fit)
        assert abs(sum(freq.values()) - 1.0) < 1e-9
        n = len([m for m in fit if any(m.get(k) is not None for k in ("home_score", "away_score"))])
        assert n == len(fit)  # all fit matches completed, none un-ordered


# ── 8. adversarial: same team two matches at same kickoff ────────────────


def test_two_matches_same_team_same_kickoff_no_crossover():
    base = {"home_score": 1, "away_score": 0, "team_a": "A", "team_b": "B",
            "event_date": "2024-03-10T20:00:00Z", "match_id": "XA"}
    sibling = {**base, "team_b": "C", "match_id": "XB"}
    earlier = {**base, "event_date": "2024-02-20T20:00:00Z", "match_id": "XP"}
    later = {**base, "event_date": "2024-03-24T20:00:00Z", "match_id": "XL"}
    matches = [earlier, sibling, later, base]

    ctx = build_context_for_match(base, matches)
    assert not any(f["event_date"] == base["event_date"] for f in ctx.fixtures)
    prior = [f["match_id"] for f in ctx.fixtures]
    assert "XA" not in prior and "XB" not in prior and "XL" not in prior
    assert "XP" in prior

    provider = ReplayResultProvider(matches)
    rows = provider.get_team_results("A", base["event_date"])
    assert "XB" not in {r["match_id"] for r in rows}
    assert "XL" not in {r["match_id"] for r in rows}
    assert [r["match_id"] for r in rows] == ["XP"]


# ── 9. adversarial: elo snapshot fixed across the season ─────────────────


def test_elo_snapshot_constant_across_season():
    sig = RefinedEloSignal()
    for s in SEASONS:
        matches = _season_matches(s)
        elo = _season_elo(s)
        first_seen: dict[tuple[str, str], tuple[float, float, float]] = {}
        for m in matches:
            assert m["team_a"] in elo and m["team_b"] in elo
            out = sig.predict(m, build_context_for_match(m, matches, elo_ratings=elo))
            key = (m["team_a"], m["team_b"])
            if key in first_seen:
                assert first_seen[key] == (out.home_prob, out.draw_prob, out.away_prob)
            else:
                first_seen[key] = (out.home_prob, out.draw_prob, out.away_prob)


# ── 10. adversarial: match_id collision self-exclusion ───────────────────


def test_match_id_collision_self_exclusion():
    early = {"match_id": "X", "team_a": "A", "team_b": "B",
             "event_date": "2024-01-10T12:00:00Z", "home_score": 1, "away_score": 0}
    late = {**early, "event_date": "2024-01-20T12:00:00Z"}
    matches = [early, late]
    # the target object itself never appears in its own prior window
    assert early not in prior_matches(matches, early)
    for p in prior_matches(matches, late):
        assert p is not late and p["event_date"] < late["event_date"]
    # a target absent from the list (unknown id) yields no context guesses
    ghost = {"match_id": "GHOST", "event_date": "2024-02-01T12:00:00Z"}
    assert prior_matches(matches, ghost) == []


# ── 11. adversarial: homogeneous ISO-UTC ordering (timezone/id edge) ─────


def test_dataset_dates_are_homogeneous_iso_utc():
    pool = _replay_pool()
    dates = [m["event_date"] for m in pool]
    for d in dates:
        assert _ISO_UTC.match(d), f"heterogeneous date format would break lexical ordering: {d}"
    assert all(a <= b for a, b in zip(dates, dates[1:])), "pool must be time-ordered"


# ── 12. adversarial: empty-anchor provider never leaks future results ─────


def test_provider_empty_or_absent_anchor_returns_nothing():
    provider = ReplayResultProvider(order_matches(_replay_pool()))
    assert provider.get_team_results("FC Barcelona", "") == []
    assert provider.get_team_results("FC Barcelona", "1990-01-01T00:00:00Z") == []