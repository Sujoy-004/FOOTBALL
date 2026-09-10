"""Leak-free historical context construction and chronological splits.

Shared by the calibration and validation harnesses so that every
historical prediction consumes ONLY information available strictly before
the match being predicted. This module never fabricates data: when a field
(Elo ratings, odds, event dates) is absent from the source data, signals
that need it are reported as unavailable instead of being fitted against
constant/empty placeholders.

Chronological ordering rules
---------------------------
A match's chronological key is derived, in priority order, from:
    1. ``event_date`` (ISO-8601, e.g. "2026-10-21T19:00:00Z")
    2. a matchday prefix in ``match_id`` (e.g. "MD06_15" -> matchday 6)
    3. its position in the source file (only a "position" ordering —
       NOT treated as trustworthy chronology for verification gates)

The ``split_chronological`` helper is only considered fully chronological
when ordering is driven by dates or matchdays; a pure positional split is
flagged as such so gates can refuse to certify it.
"""

from __future__ import annotations

import json
import re
from typing import Any

from football_core.signal import PredictionContext

_MD_RE = re.compile(r"^MD(\d{2})[_\-]", re.IGNORECASE)


def outcome_index(match: dict) -> int | None:
    """0 = home win, 1 = draw, 2 = away win. None if scores missing."""
    hs = match.get("home_score")
    aws = match.get("away_score")
    if hs is None or aws is None:
        return None
    if hs > aws:
        return 0
    if aws > hs:
        return 2
    return 1


def is_completed(match: dict) -> bool:
    """True when the match has a real (non-invented) outcome."""
    return outcome_index(match) is not None


def result_row(match: dict) -> dict:
    """Normalized result-shaped row consumed by RollingFormSignal et al.

    Never mutates the input match. The winner/is_draw fields are derived
    from actual scores (not fabricated) when absent.
    """
    idx = outcome_index(match)
    team_a = match.get("team_a", "")
    team_b = match.get("team_b", "")
    winner = match.get("winner")
    if winner is None and idx is not None:
        winner = team_a if idx == 0 else (team_b if idx == 2 else None)
    return {
        "team_a": team_a,
        "team_b": team_b,
        "home_score": match.get("home_score", 0),
        "away_score": match.get("away_score", 0),
        "winner": winner,
        "is_draw": bool(idx == 1),
        "event_date": match.get("event_date", ""),
        "match_id": match.get("match_id", ""),
    }


class ReplayResultProvider:
    """Leak-free result-history provider over an ordered match list.

    Exposes the same strictly-before guarantee as build_context_for_match
    to signals (e.g. RollingFormSignal) that fetch history through a result
    provider rather than the PredictionContext.

    get_team_results(team, before_date, limit) returns the team's rows with
    an event_date STRICTLY before ``before_date`` (an ISO date), most recent
    first. Rows lacking an event_date cannot be safely ordered against an
    ISO anchor and are excluded; when ``before_date`` is empty (no anchor)
    it returns [] rather than guessing, so no future result can leak.
    """

    def __init__(self, matches: list[dict]) -> None:
        self._rows = [result_row(m) for m in matches]

    def get_team_results(
        self, team: str, before_date: str = "", limit: int = 10
    ) -> list[dict]:
        if not before_date:
            return []
        rows: list[dict] = []
        for r in self._rows:
            if r.get("team_a") != team and r.get("team_b") != team:
                continue
            ed = r.get("event_date") or ""
            if not ed or ed >= before_date:
                continue
            rows.append(r)
        rows.sort(key=lambda r: r.get("event_date", ""), reverse=True)
        return rows[:limit]


def chronological_key(match: dict, index: int = 0) -> tuple[str, Any]:
    """Return a sortable chronological key for a match.

    Returns (kind, value) where kind is "date", "matchday" or "position".
    Tuples sort correctly within a dataset as long as one kind is used
    consistently (dates are ISO and therefore lexicographically ordered).
    """
    event_date = match.get("event_date") or ""
    if event_date:
        return ("date", event_date)
    md = _MD_RE.match(str(match.get("match_id", "")))
    if md:
        return ("matchday", int(md.group(1)))
    return ("position", index)


def order_matches(matches: list[dict]) -> list[dict]:
    """Return matches sorted by chronological key (stable for ties)."""
    indexed = [(i, m) for i, m in enumerate(matches)]
    indexed.sort(key=lambda t: chronological_key(t[1], t[0]))
    return [m for _, m in indexed]


def distinct_keys(matches: list[dict]) -> list[tuple[str, Any]]:
    """Chronological keys in first-seen order (deduplicated)."""
    keys: list[tuple[str, Any]] = []
    for i, m in enumerate(matches):
        k = chronological_key(m, i)
        if k not in keys:
            keys.append(k)
    return keys


def prior_matches(all_matches: list[dict], target: dict) -> list[dict]:
    """All matches strictly before ``target`` in chronological order.

    ``target`` may be the same object as an element of ``all_matches`` or
    a structurally-equal dict sharing its ``match_id``.
    """
    target_key = None
    target_id = target.get("match_id")
    for i, m in enumerate(all_matches):
        if m is target or (target_id and m.get("match_id") == target_id):
            target_key = chronological_key(m, i)
            break
    if target_key is None:
        return []
    out: list[dict] = []
    for i, m in enumerate(all_matches):
        if m is target:
            continue
        if chronological_key(m, i) < target_key:
            out.append(m)
    return out


def build_context_for_match(
    target: dict,
    all_matches: list[dict],
    *,
    squad_values: dict[str, float] | None = None,
    elo_ratings: dict[str, float] | None = None,
) -> PredictionContext:
    """Build a PredictionContext containing only pre-match information.

    - ``fixtures``: prior matches (needed by RestDaysSignal).
    - ``played_results``: completed prior matches as result rows.
    - ``elo_ratings``: only what the caller actually holds (no fabrication).
    - ``squad_values``: only what the caller actually holds.
    """
    prior = prior_matches(all_matches, target)
    played_results = [
        result_row(m) for m in prior if is_completed(m)
    ]
    return PredictionContext(
        fixtures=list(prior),
        elo_ratings=dict(elo_ratings or {}),
        played_results=played_results,
        squad_values=dict(squad_values) if squad_values else None,
    )


def split_chronological(
    matches: list[dict],
    *,
    oos_matchdays: int | None = None,
    oos_fraction: float = 0.3,
) -> tuple[list[dict], list[dict], dict]:
    """Chronological (fit, out-of-sample) split of historical matches.

    When ordering is matchday-driven, ``oos_matchdays`` selects whole
    trailing matchdays for the out-of-sample set (the default None uses
    ``oos_fraction`` by count). Raises ValueError when no valid split is
    possible or when asked for more out-of-sample matchdays than exist.

    Returns (fit, oos, meta) where meta describes the split: n_fit, n_oos,
    chronology ("date" | "matchday" | "position"), splittable, reason.
    """
    ordered = order_matches(matches)
    if len(ordered) < 2:
        raise ValueError(
            "Not enough matches for a chronological split "
            f"(got {len(ordered)}, need >= 2)"
        )

    keys = distinct_keys(ordered)
    kinds = {k[0] for k in keys}

    if oos_matchdays is not None and "matchday" in kinds:
        md_keys = [k for k in keys if k[0] == "matchday"]
        if oos_matchdays <= 0:
            raise ValueError("oos_matchdays must be >= 1")
        if len(md_keys) < oos_matchdays + 1:
            raise ValueError(
                f"Cannot reserve {oos_matchdays} out-of-sample matchdays: "
                f"only {len(md_keys)} distinct matchdays available"
            )
        cutoff = md_keys[-oos_matchdays]
        fit: list[dict] = []
        oos: list[dict] = []
        for i, m in enumerate(ordered):
            if chronological_key(m, i) < cutoff:
                fit.append(m)
            else:
                oos.append(m)
        chronology = "matchday"
    else:
        split_at = max(1, int(round(len(ordered) * (1 - oos_fraction))))
        if split_at >= len(ordered):
            raise ValueError(
                f"oos_fraction={oos_fraction} leaves no out-of-sample matches"
            )
        fit, oos = ordered[:split_at], ordered[split_at:]
        chronology = list(kinds)[0] if len(kinds) == 1 else "mixed"

    meta = {
        "n_fit": len(fit),
        "n_oos": len(oos),
        "chronology": chronology,
        "splittable": len(oos) > 0,
        "reason": None if len(oos) > 0 else "no out-of-sample matches",
    }
    return fit, oos, meta


def frequency_baseline(fit_matches: list[dict]) -> dict[str, float]:
    """Empirical home/draw/away outcome rates from the fit (train) set.

    A simple non-ensemble baseline: constant probabilities equal to the
    observed base rates. Fitted only on prior data and applied as a
    constant to any evaluation set.
    """
    counts = {0: 0, 1: 0, 2: 0}
    for m in fit_matches:
        o = outcome_index(m)
        if o is not None:
            counts[o] += 1
    total = sum(counts.values())
    if total == 0:
        return {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}
    return {
        "home": counts[0] / total,
        "draw": counts[1] / total,
        "away": counts[2] / total,
    }


def available_signals(
    matches: list[dict],
    *,
    squad_values: dict[str, float] | None = None,
    elo_ratings: dict[str, float] | None = None,
) -> dict[str, str]:
    """Map signal name -> "available" or "insufficient_data:<reason>".

    A signal is only "available" when the historical dataset really
    provides the inputs it needs. Everything else is reported honestly so
    calibration/validation never fit against placeholders.
    """
    has_any_date = any(m.get("event_date") for m in matches)
    has_any_odds = any(
        m.get("odds_home") is not None
        and m.get("odds_draw") is not None
        and m.get("odds_away") is not None
        for m in matches
    )
    return {
        "refined_elo": (
            "available" if elo_ratings else "insufficient_data:no_elo_ratings"
        ),
        "market_odds": (
            "available" if has_any_odds else "insufficient_data:no_odds_fields"
        ),
        "rolling_form": (
            "available" if has_any_date else "insufficient_data:no_event_dates"
        ),
        "rest_days": (
            "available" if has_any_date else "insufficient_data:no_event_dates"
        ),
        "squad_value": (
            "available"
            if squad_values else "insufficient_data:no_squad_values"
        ),
    }


def gate_verdict(
    *,
    n_oos: int,
    chronology: str,
    ensemble_ll: float,
    uniform_ll: float | None,
    freq_ll: float | None,
    n_real_signals: int,
    min_oos: int = 30,
    min_signals: int = 2,
) -> dict:
    """Decide PASS / UNVERIFIED for a match-level evaluation gate.

    Conservative by design: champion probabilities should only be treated
    as verified when there is a real, chronologically-held-out, out-of-sample
    evaluation where the ensemble beats BOTH baselines (uniform 1/3 and the
    empirical-frequency baseline) with at least ``min_signals`` real
    (non-constant) signals contributing.

    Returns {"status": "PASS" | "UNVERIFIED", "reasons": [...]}.
    """
    reasons: list[str] = []
    if n_oos < min_oos:
        reasons.append(
            f"out-of-sample matches ({n_oos}) below minimum ({min_oos})"
        )
    if chronology not in ("date", "matchday"):
        reasons.append(
            f"chronology '{chronology}' is not a trustworthy date/matchday "
            "ordering — cannot verify out-of-sample"
        )
    eff_uniform = uniform_ll if uniform_ll is not None else float("inf")
    eff_freq = freq_ll if freq_ll is not None else float("inf")
    if not (ensemble_ll < eff_uniform):
        reasons.append("ensemble log-loss does not beat the uniform 1/3 baseline")
    if not (ensemble_ll < eff_freq):
        reasons.append(
            "ensemble log-loss does not beat the empirical-frequency baseline"
        )
    if n_real_signals < min_signals:
        reasons.append(
            f"only {n_real_signals} real signal(s) contributing "
            f"(need {min_signals})"
        )
    status = "PASS" if not reasons else "UNVERIFIED"
    return {"status": status, "reasons": reasons}


def load_replay_matches(path: str) -> list[dict]:
    """Load match dicts from a replay/results JSON preserving order.

    Accepts either a top-level list or a dict with a "matches"/"results"
    list key. Preserves file order (prior_matches/split_chronological
    derive real chronology from dates or matchday ids when present).
    """
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("matches", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    raise ValueError(
        f"Unknown replay data format in {path}: expected a list or a "
        "dict with a 'matches'/'results' list"
    )