"""LaLiga pipeline — acquisition, stores, deterministic compute, insight.

Mirrors the UCL brain's responsibilities while staying league-only:
the web layer owns transport selection (``web.common.get_data_provider``),
this module owns every normalization and store-write decision, and the
shared generic season store (``football_core.seasons``) owns persistence.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from football_core.blender import EnsembleEngine
from football_core.fetcher import IngestReport, fold_team_key
from football_core.insight import (
    form_trend as _core_form_trend,
    head_to_head as _core_head_to_head,
    outcome_distribution as _core_outcome_dist,
    insight_text as _core_insight_text,
)

from competitions.laliga.src import seasons as _season_store
from competitions.laliga.src.constants import (
    CONFIG_DIR,
    DATA_DIR,
    LALIGA_BSD_LEAGUE_ID,
    LALIGA_FDO_COMPETITION_ID,
    N_MATCHDAYS,
    SHIPPED_SEASON,
)
from competitions.laliga.src.groups import compute_laliga_standings, played_map_from_rows

logger = logging.getLogger(__name__)

STATUS_FINISHED = "finished"


def load_config() -> dict:
    path = CONFIG_DIR / "config.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def load_fixtures(data_dir=DATA_DIR, season_token=None) -> list[dict]:
    payload = _season_store.read_fixtures(data_dir, season_token)
    fixtures = payload.get("fixtures", []) if isinstance(payload, dict) else []
    return [f for f in fixtures if isinstance(f, dict)]


def load_results(data_dir=DATA_DIR, season_token=None) -> list[dict]:
    payload = _season_store.read_results(data_dir, season_token)
    rows = payload.get("matches", []) if isinstance(payload, dict) else []
    return [m for m in rows if isinstance(m, dict)]


def load_played_flat(data_dir=DATA_DIR, season_token=None) -> dict[str, dict]:
    return played_map_from_rows(load_results(data_dir, season_token))


def load_team_names(data_dir=DATA_DIR, season_token=None) -> list[str]:
    names: set[str] = set()
    for f in load_fixtures(data_dir, season_token):
        if f.get("home_team"):
            names.add(f["home_team"])
        if f.get("away_team"):
            names.add(f["away_team"])
    return sorted(names)


def load_elo_ratings(data_dir=DATA_DIR, season_token=None) -> dict[str, float]:
    path = Path(data_dir) / "elo_seed.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    ratings = payload.get("ratings", {}) if isinstance(payload, dict) else {}
    return {k: float(v) for k, v in ratings.items() if isinstance(v, (int, float))}


def _alias_lookup(data_dir=DATA_DIR) -> dict[str, str]:
    """Fold-key -> canonical team name from the shipped alias file."""
    path = Path(data_dir) / "team_aliases.json"
    if not path.exists():
        return {}
    try:
        aliases = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    from football_core.fetcher import fold_team_key

    lookup: dict[str, str] = {}
    for canonical, variants in aliases.items():
        lookup[fold_team_key(canonical)] = canonical
        for variant in variants or []:
            lookup[fold_team_key(str(variant))] = canonical
    return lookup


def canonicalize_teams(home: str, away: str, alias_lookup: dict[str, str]) -> tuple[str, str]:
    return (
        alias_lookup.get(fold_team_key(home), home),
        alias_lookup.get(fold_team_key(away), away),
    )


class LaligaReplayResultProvider:
    """ResultHistoryProvider over a replay results file (RollingFormSignal)."""

    def __init__(self, results: list[dict]) -> None:
        self._results = results

    def get_team_results(self, team: str, before_date: str, limit: int = 10) -> list[dict]:
        out = []
        for m in self._results:
            if m.get("team_a") == team:
                out.append({
                    "winner": m.get("team_a") if (m.get("home_score") or 0) > (m.get("away_score") or 0)
                              else (m.get("team_b") if (m.get("home_score") or 0) < (m.get("away_score") or 0) else None),
                    "is_draw": (m.get("home_score") or 0) == (m.get("away_score") or 0),
                    "event_date": m.get("event_date") or str(m.get("match_id", "")),
                })
            elif m.get("team_b") == team:
                out.append({
                    "winner": m.get("team_b") if (m.get("home_score") or 0) < (m.get("away_score") or 0)
                              else (m.get("team_a") if (m.get("home_score") or 0) > (m.get("away_score") or 0) else None),
                    "is_draw": (m.get("home_score") or 0) == (m.get("away_score") or 0),
                    "event_date": m.get("event_date") or str(m.get("match_id", "")),
                })
        out.sort(key=lambda r: r["event_date"], reverse=True)
        return out[:limit]


def build_signal_engine(
    elo_ratings: dict[str, float],
    weights_override: dict[str, float] | None = None,
    results_file: str | None = None,
    squad_values_path: str | None = None,
    *,
    strategy: str = "production",
) -> EnsembleEngine:
    """The standard five-signal ensemble (parity with the UCL brain); non-production strategies dispatch to build_strategy_engine."""
    if strategy != "production":
        from competitions.laliga.src.ensemble import build_strategy_engine as _build_strategy_engine

        return _build_strategy_engine(strategy, elo_ratings=elo_ratings)
    from football_core.signals.refined_elo import RefinedEloSignal
    from football_core.signals.market_odds import MarketOddsSignal
    from football_core.signals.rolling_form import RollingFormSignal
    from football_core.signals.squad_value import SquadValueSignal
    from football_core.signals.rest_days import RestDaysSignal

    if results_file and os.path.exists(results_file):
        rows = json.loads(Path(results_file).read_text(encoding="utf-8"))
        provider = LaligaReplayResultProvider(
            rows.get("matches", []) if isinstance(rows, dict) else []
        )
    else:
        provider = LaligaReplayResultProvider([])

    signals = [
        RefinedEloSignal(),
        MarketOddsSignal(),
        RollingFormSignal(result_provider=provider),
        SquadValueSignal(data_path=squad_values_path or str(DATA_DIR / "squad_values.json")),
        RestDaysSignal(),
    ]

    weights_path = CONFIG_DIR / "signal_weights.json"
    if weights_override is not None:
        return EnsembleEngine(signals, weights=weights_override)
    if weights_path.exists():
        return EnsembleEngine(signals, weights_path=str(weights_path))
    return EnsembleEngine(signals)


# ── deterministic results-mode compute ───────────────────────────────────


def compute_signal_eval(
    results: list[dict],
    engine,
    elo_ratings: dict[str, float],
    elo_provenance: str | None = None,
) -> dict:
    """Evaluate the ensemble's signal accuracy against real results.

    Mirrors the UCL brain's ``compute_signal_eval`` contract (per-signal
    ``accuracy``/``brier``/``available_pct``/``weight``) adapted to the
    LaLiga result-row shape (``home_team``/``away_team``/``home_score``).
    """
    if elo_provenance is None:
        elo_provenance = "shipped" if elo_ratings else "unavailable"
    from football_core.signal import PredictionContext

    signal_matches = [
        {"team_a": m["home_team"], "team_b": m["away_team"], "match_id": m["match_id"]}
        for m in results if m.get("match_id")
    ]
    if not signal_matches:
        return {}
    ctx = PredictionContext(fixtures=signal_matches, elo_ratings=elo_ratings,
                            played_results=results)
    sig_data: dict[str, dict] = {}
    try:
        blended = [engine.evaluate(m, ctx) for m in signal_matches]
        for i, bp in enumerate(blended):
            m = results[i]
            hs = int(m.get("home_score") or 0)
            aws = int(m.get("away_score") or 0)
            if hs > aws:
                actual = [1.0, 0.0, 0.0]
            elif hs < aws:
                actual = [0.0, 0.0, 1.0]
            else:
                actual = [0.0, 1.0, 0.0]
            for sig, sd in bp.signal_breakdown.items():
                if sig not in sig_data:
                    sig_data[sig] = {"probs": [], "n": 0, "available": 0,
                                     "brier_sum": 0.0, "correct": 0, "n_eval": 0}
                sig_data[sig]["n"] += 1
                if sd.get("available", True):
                    sig_data[sig]["available"] += 1
                ph = sd.get("home", 0.5)
                pd = sd.get("draw", 0.0)
                pa = sd.get("away", 0.5)
                sig_data[sig]["brier_sum"] += (ph - actual[0]) ** 2 + (pd - actual[1]) ** 2 + (pa - actual[2]) ** 2
                sig_data[sig]["n_eval"] += 1
                pred_idx = 0 if (ph >= pd and ph >= pa) else (1 if pd >= pa else 2)
                actual_idx = 0 if actual[0] == 1 else (1 if actual[1] == 1 else 2)
                if pred_idx == actual_idx:
                    sig_data[sig]["correct"] += 1
                if sd.get("weight", 0) > 0:
                    sig_data[sig].setdefault("probs", []).extend([ph, pd, pa])
        sig_stats = {}
        for sig, sd in sorted(sig_data.items()):
            probs = sd.get("probs", [])
            sig_stats[sig] = {
                "n_matches": sd["n"],
                "available": sd["available"],
                "available_pct": round(sd["available"] / sd["n"] * 100, 1) if sd["n"] else 0,
                "avg_probability": round((sum(probs) / len(probs)) if probs else 0, 4),
                "weight": round(engine.weights.get(sig, 0), 4),
                "brier": round(sd["brier_sum"] / sd["n_eval"], 4) if sd["n_eval"] else 0,
                "accuracy": round(sd["correct"] / sd["n_eval"], 4) if sd["n_eval"] else 0,
            }
        return sig_stats
    except Exception:
        return {}


def _matchday_of(row: dict) -> int:
    try:
        return int(row.get("matchday") or 0)
    except (TypeError, ValueError):
        return 0


def compute_deterministic(data_dir=DATA_DIR, season_token=None) -> dict:
    """Build the factual (results-mode) competition cache payload."""
    season_token = season_token or _season_store.active_season(data_dir)
    fixtures = load_fixtures(data_dir, season_token)
    results = load_results(data_dir, season_token)
    elo_ratings = load_elo_ratings(data_dir, season_token)

    played = played_map_from_rows(results)
    standings = compute_laliga_standings(played, elo_ratings)

    finished_ids = set(played)
    odds = []
    for f in fixtures:
        mid = f["match_id"]
        if mid in finished_ids:
            m = played[mid]
            sa, sb = m["score_a"], m["score_b"]
            if sa > sb:
                probs = (1.0, 0.0, 0.0)
            elif sb > sa:
                probs = (0.0, 0.0, 1.0)
            else:
                probs = (0.0, 1.0, 0.0)
        else:
            probs = (None, None, None)
        odds.append({
            "match_id": mid, "team_a": f["home_team"], "team_b": f["away_team"],
            "matchday": _matchday_of(f), "home_prob": probs[0],
            "draw_prob": probs[1], "away_prob": probs[2],
        })

    n_unplayed = sum(1 for f in fixtures if f["match_id"] not in finished_ids)
    n_played = len(played)

    teams_top = [
        {"rank": s["position"], "team": s["team"], "pts": s["points"], "gd": s["goal_diff"]}
        for s in standings[:4]
    ]
    all_teams = [
        {"rank": s["position"], "team": s["team"], "pts": s["points"], "gd": s["goal_diff"]}
        for s in standings
    ]

    availability = {
        "fixtures": "available" if fixtures else "missing",
        "results": "available" if results else "empty",
        "elo_ratings": "available" if elo_ratings else "missing",
    }
    current_md = (
        max(_matchday_of(f) for f in fixtures if f["match_id"] in finished_ids)
        if n_played else 0
    )
    phase = {
        "phase": "league",
        "label": "Regular Season",
        "champion": None,
        "progress": {"n_played": n_played, "n_total": len(fixtures), "n_unplayed": n_unplayed,
                     "n_matchdays": N_MATCHDAYS, "current_matchday": current_md},
        "stores": availability,
    }

    engine = build_signal_engine(elo_ratings,
                                 results_file=str(_season_store.season_dir(data_dir, season_token) / "results.json"))
    signals = compute_signal_eval(results, engine, elo_ratings) if results else {}

    return {
        "mode": "results",
        "teams": teams_top,
        "all_teams": all_teams,
        "standings": standings,
        "odds": odds,
        "signals": signals,
        "n_teams": len(all_teams),
        "n_iterations": 0,
        "snapshot_date": "",
        "season": season_token,
        "champion": None,
        "availability": availability,
        "phase": phase,
        "elo_ratings": elo_ratings,
        "fixtures": fixtures,
        "_results": results,
        "_elo_fallback": not elo_ratings,
    }


# ── acquisition (live refresh) ───────────────────────────────────────────


def fetch_live_data(
    data_dir=DATA_DIR,
    bsd_api_key: str = "",
    provider=None,
    football_data_org_key: str = "",
    league_id: int = LALIGA_BSD_LEAGUE_ID,
    fdo_competition_id: str = LALIGA_FDO_COMPETITION_ID,
) -> dict:
    """Refresh the active season from a live provider. Never raises.

    Providers return BSD-compatible flat events; each is normalized onto
    the shipped canonical team vocabulary and written to the season store.
    Returns the truth-ingestion summary the web layer records.
    """
    report = IngestReport(provider=None, attempted=True, success=True, error=None)
    if provider is None:
        report.attempted = False
        report.success = False
        report.error = "no data provider configured"
        return {"report": report.to_dict(), "status": "error", "reason": "no_provider",
                "provider_name": None, "n_raw": 0, "n_updated": 0, "per_season": {}}

    alias_lookup = _alias_lookup(data_dir)
    try:
        import inspect

        try:
            fetch_sig = inspect.signature(provider.fetch_matches)
            accepts_season = (
                "season" in fetch_sig.parameters
                or any(p.kind is inspect.Parameter.VAR_KEYWORD
                       for p in fetch_sig.parameters.values())
            )
        except (TypeError, ValueError):
            accepts_season = False
        if accepts_season:
            try:
                season_year = int(SHIPPED_SEASON.split("/", 1)[0])
            except (TypeError, ValueError):
                season_year = None
            events = provider.fetch_matches(
                competition_id=fdo_competition_id,
                **({"season": season_year} if season_year is not None else {}),
            )
        else:
            events = provider.fetch_matches(competition_id=fdo_competition_id)
    except Exception as exc:
        logger.warning("LaLiga provider fetch raised: %s", exc)
        report.success = False
        report.error = f"{exc.__class__.__name__}: {exc}"
        report.stale = True
        return {"report": report.to_dict(), "status": "error", "reason": "fetch_error",
                "provider_name": type(provider).__name__, "n_raw": 0, "n_updated": 0,
                "per_season": {}}

    events = events or []
    fixtures: list[dict] = []
    results: list[dict] = []
    canonical = set(alias_lookup.values())
    n_unmatchable = 0
    for e in events:
        if not isinstance(e, dict):
            continue
        home = alias_lookup.get(fold_team_key(str(e.get("home_team", ""))), str(e.get("home_team", "")))
        away = alias_lookup.get(fold_team_key(str(e.get("away_team", ""))), str(e.get("away_team", "")))
        if home not in canonical or away not in canonical:
            n_unmatchable += 1
            continue
        status = str(e.get("status") or "scheduled")
        try:
            matchday = int(e.get("round_number") or 0)
        except (TypeError, ValueError):
            matchday = 0
        row = {
            "match_id": str(e.get("match_id") or e.get("id")),
            "home_team": home,
            "away_team": away,
            "event_date": e.get("event_date"),
            "status": status,
            "matchday": matchday,
            "stage": e.get("stage") or "REGULAR_SEASON",
        }
        fixtures.append(row)
        if status == STATUS_FINISHED:
            hs, aws = e.get("home_score"), e.get("away_score")
            if hs is None or aws is None:
                report.finished["skipped_missing_score"] += 1
                continue
            winner = home if hs > aws else (away if aws > hs else None)
            results.append({
                **row, "home_score": int(hs), "away_score": int(aws),
                "winner": winner, "status": STATUS_FINISHED,
            })

    fixtures_payload = {
        "provider": type(provider).__name__,
        "availability": {"all_played": bool(fixtures) and len(results) == len(fixtures),
                         "fully_received": bool(fixtures), "n_fixtures": len(fixtures),
                         "n_played": len(results)},
        "fixtures": fixtures,
    }
    results_payload = {"provider": type(provider).__name__, "error": None,
                       "matches": results}
    _season_store.write_fixtures(fixtures_payload, data_dir, SHIPPED_SEASON)
    _season_store.write_results(results_payload, data_dir, SHIPPED_SEASON)

    report.provider = type(provider).__name__
    report.finished["received"] = sum(1 for r in results if r.get("status") == STATUS_FINISHED)
    report.finished["normalized"] = len(results)
    report.finished["ingested"] = len(results)
    if n_unmatchable:
        report.finished["skipped_unmatchable"] = n_unmatchable

    return {
        "report": report.to_dict(),
        "status": "ok",
        "provider_name": type(provider).__name__,
        "n_raw": len(events),
        "n_updated": len(results),
        "per_season": {SHIPPED_SEASON: {"fixtures": len(fixtures), "results": len(results)}},
    }


# ── insight helpers (parity delegates to the shared kernel) ──────────────


def laliga_form_trend(team: str, results: list[dict]) -> list[dict]:
    return _core_form_trend(results, team, limit=5)


def laliga_head_to_head(ta: str, tb: str, results: list[dict]) -> dict:
    return _core_head_to_head(results, ta, tb)


def laliga_outcome_dist(blended_prob: float, elo_a: float, elo_b: float) -> dict | None:
    if blended_prob is None:
        return None
    return _core_outcome_dist(blended_prob, elo_a, elo_b)


def laliga_insight_text(ta, tb, signals, form_trends, h2h, outcome, eval_data) -> str:
    return _core_insight_text(ta, tb, signals, form_trends, h2h, outcome, eval_data)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()