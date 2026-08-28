"""UCL data pipeline — pure functions extracted from web/ucl_app.py.

These functions accept all dependencies as parameters, have no module-level
globals, and can be imported/reused independently of the web layer.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from competitions.ucl.src.orchestrator import (
    _top_champion_probs,
    build_sim_state_payload,
    build_signal_engine,
    build_simulation_result,
)
from football_core.signal import PredictionContext

logger = logging.getLogger(__name__)


# ── 1 ─────────────────────────────────────────────────────────────────────


# ── 2 ─────────────────────────────────────────────────────────────────────


def compute_deterministic_standings(results: list[dict]) -> list[dict]:
    """Compute league standings from finished match results.

    Exchange 2 unification: delegates to the UCL brain's canonical
    ``compute_swiss_standings`` (full UEFA 10-step tiebreaker) instead of a
    weaker parallel chain, so real-results and simulated tables are ordered
    by identical rules. Result-ledger rows are adapted into the swiss match
    shape with zero cards (no card data exists in the ledger).
    """
    from competitions.ucl.src.groups import compute_swiss_standings

    matches: dict[str, dict] = {}
    for m in results:
        mid = m.get("match_id")
        if not mid:
            continue
        try:
            hs, aw = int(m["home_score"]), int(m["away_score"])
        except (KeyError, TypeError, ValueError):
            continue
        matches[mid] = {
            "team_a": m["team_a"],
            "team_b": m["team_b"],
            "score_a": hs,
            "score_b": aw,
            "yellow_cards_a": 0,
            "red_cards_a": 0,
            "yellow_cards_b": 0,
            "red_cards_b": 0,
        }
    return compute_swiss_standings(matches)


# ── 3 ─────────────────────────────────────────────────────────────────────


def build_deterministic_bracket(knockout: dict, standings: list[dict], data_dir: str | Path) -> dict:
    """Build deterministic bracket display from real knockout results."""
    data_dir = Path(data_dir) if isinstance(data_dir, str) else data_dir
    bracket_rules_path = data_dir / "bracket_rules.json"
    try:
        bracket_rules = json.loads(bracket_rules_path.read_text(encoding="utf-8"))
    except Exception:
        bracket_rules = {"matches": []}
    source_map: dict[str, list[str]] = {}
    for m in bracket_rules.get("matches", []):
        if m.get("source_matches"):
            source_map[m["match_id"]] = m["source_matches"]
    mid_index: dict[str, int] = {"R16": 0, "QF": 0, "SF": 0, "FINAL": 0}

    def _next_mid(rnd: str) -> str:
        mid_index[rnd] += 1
        if rnd == "R16":
            return f"r16_{mid_index[rnd]:02d}"
        if rnd == "QF":
            return f"qf_{mid_index[rnd]:02d}"
        if rnd == "SF":
            return f"sf_{mid_index[rnd]:02d}"
        return f"final_{mid_index[rnd]:02d}"

    rounds_out: dict[str, list[dict]] = {"R16": [], "QF": [], "SF": [], "FINAL": []}
    ko_rounds = knockout.get("rounds", {})
    for rnd in ["R16", "QF", "SF", "FINAL"]:
        for m in ko_rounds.get(rnd, []):
            mid = _next_mid(rnd)
            winner = m.get("winner", "")
            entry = {
                "match_id": mid,
                "round": rnd,
                "team_a": m.get("team_a", ""),
                "team_b": m.get("team_b", ""),
                "score": {"home": m.get("score_a", 0), "away": m.get("score_b", 0)},
                "winner": winner,
                "played": True,
                # Explicit canonical state (Exchange 2): a stored tie is a
                # played fact only when a winner exists.
                "status": "played" if winner else "scheduled",
                "provenance": "official",
                "source_matches": source_map.get(mid) or None,
            }
            if rnd == "FINAL" and m.get("penalties"):
                pens = m["penalties"]
                entry["penalties"] = {
                    "winner": pens.get("winner", m.get("winner", "")),
                    "loser": pens.get("loser", ""),
                }
                ps = pens.get("score", "0-0").split("-")
                if len(ps) == 2:
                    entry["penalties"]["home"] = int(ps[0])
                    entry["penalties"]["away"] = int(ps[1])
            rounds_out[rnd].append(entry)
    playoff_display: list[dict] = []
    for tie in knockout.get("playoff", []):
        ta = tie.get("team_a", "")
        tb = tie.get("team_b", "")
        winner = tie.get("winner", "")
        loser = tb if winner == ta else ta
        playoff_display.append({
            "tie_num": tie.get("tie_num"),
            "team_a": winner or ta,
            "team_b": loser or tb,
            "winner": winner,
            "aggregate_a": tie.get("aggregate_a", 0),
            "aggregate_b": tie.get("aggregate_b", 0),
            "et_played": tie.get("et_played", False),
            "penalties_played": tie.get("penalties_played", False),
        })
    return {"playoff": playoff_display, "bracket_rounds": rounds_out}


# ── 4 ─────────────────────────────────────────────────────────────────────


def compute_signal_eval(
    results: list[dict],
    engine,
    elo_ratings: dict[str, float],
) -> dict:
    """Evaluate signal accuracy against real results."""
    signal_matches = []
    for m in results:
        signal_matches.append({"team_a": m["team_a"], "team_b": m["team_b"], "match_id": m["match_id"]})
    ctx = PredictionContext(fixtures=signal_matches, elo_ratings=elo_ratings, played_results=results)
    sig_data: dict[str, dict] = {}
    try:
        blended = [engine.evaluate(m, ctx) for m in signal_matches]
        for i, bp in enumerate(blended):
            m = results[i]
            ta, tb = m["team_a"], m["team_b"]
            hs, aws = m["home_score"], m["away_score"]
            if hs > aws:
                actual = [1.0, 0.0, 0.0]
            elif hs < aws:
                actual = [0.0, 0.0, 1.0]
            else:
                actual = [0.0, 1.0, 0.0]
            for sig, sd in bp.signal_breakdown.items():
                if sig not in sig_data:
                    sig_data[sig] = {"probs": [], "n": 0, "available": 0, "brier_sum": 0.0, "correct": 0, "n_eval": 0}
                sig_data[sig]["n"] += 1
                if sd.get("available", True):
                    sig_data[sig]["available"] += 1
                prob_h = sd.get("home", 0.5)
                prob_d = sd.get("draw", 0.0)
                prob_a = sd.get("away", 0.5)
                brier = (prob_h - actual[0])**2 + (prob_d - actual[1])**2 + (prob_a - actual[2])**2
                sig_data[sig]["brier_sum"] += brier
                sig_data[sig]["n_eval"] += 1
                pred_idx = 0 if prob_h >= prob_d and prob_h >= prob_a else (1 if prob_d >= prob_a else 2)
                actual_idx = 0 if actual[0] == 1 else (1 if actual[1] == 1 else 2)
                if pred_idx == actual_idx:
                    sig_data[sig]["correct"] += 1
                if sd.get("weight", 0) > 0:
                    sig_data[sig].setdefault("probs", []).extend([prob_h, prob_d, prob_a])
        sig_stats = {}
        for sig, sd in sorted(sig_data.items()):
            probs = sd.get("probs", [])
            avg = sum(probs) / len(probs) if probs else 0
            brier_avg = sd["brier_sum"] / sd["n_eval"] if sd["n_eval"] else 0
            acc = sd["correct"] / sd["n_eval"] if sd["n_eval"] else 0
            sig_stats[sig] = {
                "n_matches": sd["n"], "available": sd["available"],
                "available_pct": round(sd["available"] / sd["n"] * 100, 1) if sd["n"] else 0,
                "avg_probability": round(avg, 4),
                "weight": round(engine.weights.get(sig, 0), 4),
                "brier": round(brier_avg, 4), "accuracy": round(acc, 4),
            }
        return sig_stats
    except Exception:
        return {}


# ── 5 ─────────────────────────────────────────────────────────────────────


def _select_provider(bsd_api_key: str, football_data_org_key: str, ucl_league_id: int):
    """Select a data provider based on available keys and env override."""
    from football_core.data_providers.bsd_provider import BSDDataProvider
    from football_core.data_providers.football_data_org_provider import FootballDataOrgProvider

    mode = os.environ.get("DATA_PROVIDER", "").lower()
    if mode == "bsd" and bsd_api_key:
        return BSDDataProvider(bsd_api_key, league_id=ucl_league_id)
    if mode == "football-data" and football_data_org_key:
        return FootballDataOrgProvider(football_data_org_key)
    if bsd_api_key:
        return BSDDataProvider(bsd_api_key, league_id=ucl_league_id)
    if football_data_org_key:
        return FootballDataOrgProvider(football_data_org_key)
    return None


def fetch_live_data(
    data_dir: str | Path,
    bsd_api_key: str,
    football_data_org_key: str = "",
    ucl_league_id: int = 7,
    team_aliases_data: dict | None = None,
    provider=None,
) -> dict:
    """Fetch live match data from the configured provider and ingest it.

    Exchange 5: routes through the multi-season ingestion system so that
    provider events with a non-historical season are stored under
    ``data/seasons/<season>/`` instead of the root stores.  Historical
    2025/26 events are routed to the legacy path exactly as before.

    Both finished AND scheduled/timed events are preserved: finished events
    create factual results; scheduled events populate season fixtures without
    fabricated scores.

    Returns a superset of the legacy refresh dict — ``status`` (ok/skip),
    ``n_raw``, ``n_updated``, ``provider_name`` — plus ``report`` holding
    the structured :class:`~football_core.fetcher.IngestReport` payload.
    """
    from football_core.fetcher import (
        IngestReport,
        _build_alias_lookup,
        count_finished,
        new_ingestion_stats,
        note_unmatchable,
        normalize_team,
    )
    from competitions.ucl.src.ingest import (
        EVENT_PASSTHROUGH_FIELDS,
        ingest_ucl_events_multi_season,
    )
    from competitions.ucl.src.seasons import (
        LOCAL_HISTORICAL_SEASON,
        normalize_season_token,
        set_current_season,
    )

    # The web layer owns transport selection (web.common.get_data_provider)
    # and may pass a pre-selected provider; offline/backfill callers fall
    # back to the local key-based selection.
    if provider is None:
        provider = _select_provider(bsd_api_key, football_data_org_key, ucl_league_id)
    if provider is None:
        logger.warning("[UCL] No data provider — skipping live fetch")
        report = IngestReport(provider="none", attempted=False, success=True, error=None, stale=True)
        return {"status": "skip", "n_raw": 0, "n_updated": 0,
                "provider_name": "none", "report": report.to_dict()}

    provider_label = type(provider).__name__
    raw = provider.fetch_matches(competition_id="CL")
    if not raw:
        err = getattr(provider, "last_error", None) or "provider returned 0 matches"
        logger.warning("[UCL] No matches returned from provider: %s", err)
        report = IngestReport(provider=provider_label, attempted=True, success=False,
                              error=err, stale=True)
        return {"status": "skip", "n_raw": 0, "n_updated": 0,
                "provider_name": provider_label, "report": report.to_dict()}

    logger.info("[UCL] Fetched %d raw matches from %s", len(raw), provider_label)

    data_dir_path = Path(data_dir) if isinstance(data_dir, str) else data_dir

    # Build alias lookup from root fixtures + team_aliases
    if team_aliases_data:
        aliases = team_aliases_data
    else:
        aliases_path = data_dir_path / "team_aliases.json"
        aliases = json.loads(aliases_path.read_text(encoding="utf-8")) if aliases_path.exists() else {}
    alias_lookup = _build_alias_lookup(aliases, bracket=[])

    # Exchange 5: root fixtures.json is optional — new seasons don't require it.
    # The multi-season ingest creates season-dir fixtures dynamically.
    root_fixtures_path = data_dir_path / "fixtures.json"
    if root_fixtures_path.exists():
        try:
            fixtures = json.loads(root_fixtures_path.read_text(encoding="utf-8"))
            for team in fixtures.get("schedule", {}).get("teams", []):
                alias_lookup[team["name"].strip().lower()] = team["name"]
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            pass

    # Normalize ALL events (finished + scheduled) — do not discard scheduled.
    norm_stats = new_ingestion_stats()
    normalized_events: list[dict] = []
    n_unmatchable = 0
    for event in raw:
        status = (event.get("status") or "").lower()
        is_finished = status == "finished"
        if is_finished:
            count_finished(norm_stats)
        norm_stats["normalized"] += 1

        home_name = event.get("home_team", "")
        away_name = event.get("away_team", "")
        home_norm = normalize_team(home_name, alias_lookup)
        away_norm = normalize_team(away_name, alias_lookup)

        if home_norm is None or away_norm is None:
            note_unmatchable(norm_stats, logger, home_name, away_name,
                             (event.get("home_score"), event.get("away_score")))
            n_unmatchable += 1
            continue

        ev = {
            "home_team": home_norm,
            "away_team": away_norm,
            "home_score": event.get("home_score") or 0,
            "away_score": event.get("away_score") or 0,
            "status": "finished" if is_finished else (event.get("status") or "scheduled"),
            "stage": event.get("stage", ""),
        }
        # Exchange 5: preserve season identity for multi-season routing.
        # Events without provider season info default to the local historical
        # season — BSD and other non-FDO providers never emit season.
        season_raw = event.get("season", "")
        ev["season"] = season_raw if season_raw else LOCAL_HISTORICAL_SEASON
        # Preserve provider match_id for stable fixture identity.
        match_id = event.get("match_id", "")
        if match_id:
            ev["match_id"] = str(match_id)
        for field_name in EVENT_PASSTHROUGH_FIELDS:
            if field_name in event:
                ev[field_name] = event[field_name]
        normalized_events.append(ev)

    # Exchange 5: route through multi-season ingestion.
    # For events with season == LOCAL_HISTORICAL_SEASON (or no season),
    # the router delegates to the legacy path automatically.
    result = ingest_ucl_events_multi_season(normalized_events, data_dir_path, provider_label)
    report_dict = result.get("report", {})
    per_season = result.get("per_season", {})

    # Extract the IngestReport from the multi-season result for compatibility.
    from football_core.fetcher import IngestReport as _IR
    if isinstance(report_dict, dict):
        report = _IR(
            provider=report_dict.get("provider", provider_label),
            attempted=report_dict.get("attempted", True),
            success=report_dict.get("success", True),
            error=report_dict.get("error"),
        )
        report.stale = report_dict.get("stale", False)
        report.last_success_at = report_dict.get("last_success_at")
        report.finished = report_dict.get("finished", report.finished)
        report.stages = report_dict.get("stages", [])
        report.written_files = report_dict.get("written_files", [])
    else:
        report = _IR(provider=provider_label, attempted=True, success=True, error=None)

    # Fold normalization-side skips back in so the global invariant holds.
    merged_finished = dict(report.finished)
    merged_finished["received"] = merged_finished.get("received", 0) + n_unmatchable
    merged_finished["normalized"] = merged_finished.get("normalized", 0) + n_unmatchable
    merged_finished["skipped_unmatchable"] = (
        merged_finished.get("skipped_unmatchable", 0) + n_unmatchable
    )
    report.finished = merged_finished

    # Exchange 5: activate a newly-discovered season when it has sufficient data.
    _maybe_activate_new_season(data_dir_path, per_season, provider_label)

    # Exchange 5: compute n_updated from per_season data since the combined
    # report may not have stages populated (multi-season function returns
    # per-season stats instead of stage-level breakdowns).
    n_updated = 0
    for _sk, sv in per_season.items():
        if not isinstance(sv, dict):
            continue
        if sv.get("legacy"):
            # Legacy report has stages with counts.
            leg_report = sv.get("report", {})
            for stage in leg_report.get("stages", []):
                if stage.get("key") in ("league", "playoff", "knockout"):
                    n_updated += stage.get("count", 0)
        else:
            n_updated += sv.get("results_added", 0) + sv.get("results_updated", 0)
    logger.info("[UCL] Updated %d matches — files saved", n_updated)

    return {
        "status": "ok",
        "n_raw": len(raw),
        "n_updated": n_updated,
        "provider_name": provider_label,
        "report": report.to_dict(),
        "per_season": per_season,
    }


def _maybe_activate_new_season(
    data_dir: Path,
    per_season: dict,
    provider_name: str,
) -> None:
    """Activate a newly-discovered season if it has sufficient data.

    Checks each non-historical season in the ingest result.  If any season
    has fixtures >= 100 OR results >= 50 and is not the current active
    season, updates ``current.json`` atomically.

    Does NOT downgrade a valid active season to one with less data.
    """
    from competitions.ucl.src.lifecycle import (
        SUFFICIENT_FIXTURES_THRESHOLD,
        SUFFICIENT_RESULTS_THRESHOLD,
    )
    from competitions.ucl.src.seasons import (
        get_current_season,
        read_season_fixtures,
        read_season_results,
        set_current_season,
    )

    for season_key, stats in per_season.items():
        if not isinstance(stats, dict):
            continue
        if stats.get("legacy"):
            continue

        fx_total = stats.get("fixtures_total", 0)
        res_total = stats.get("results_added", 0) + stats.get("results_updated", 0)

        # Also check the season store for cumulative counts (not just this batch).
        fx_doc = read_season_fixtures(data_dir, season_key)
        res_doc = read_season_results(data_dir, season_key)
        if isinstance(fx_doc, dict):
            fx_total = max(fx_total, len(fx_doc.get("fixtures", [])))
        if isinstance(res_doc, dict):
            res_total = max(res_total, len(res_doc.get("matches", [])))

        sufficient = (
            fx_total >= SUFFICIENT_FIXTURES_THRESHOLD
            or res_total >= SUFFICIENT_RESULTS_THRESHOLD
        )
        if not sufficient:
            continue

        current = get_current_season(data_dir)
        current_season = None
        if current and isinstance(current, dict):
            current_season = current.get("season")

        if current_season == season_key:
            continue

        logger.info(
            "[UCL] Activating season %s (fixtures=%d, results=%d) — "
            "previous active: %s",
            season_key, fx_total, res_total, current_season,
        )
        set_current_season(data_dir, season_key, basis="provider", provider=provider_name)


# ── 6 ─────────────────────────────────────────────────────────────────────


def load_results(data_dir: str | Path) -> list[dict]:
    """Load results from results.json in *data_dir*."""
    path = Path(data_dir) / "results.json" if isinstance(data_dir, str) else data_dir / "results.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "matches" in data:
        return data["matches"]
    return data if isinstance(data, list) else []


# ── 7 ─────────────────────────────────────────────────────────────────────


def load_knockout_results(data_dir: str | Path) -> dict | None:
    """Load knockout results from knockout_results.json in *data_dir*."""
    path = Path(data_dir) / "knockout_results.json" if isinstance(data_dir, str) else data_dir / "knockout_results.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "matches" in data:
        return data["matches"]
    return data if isinstance(data, dict) else None


# ── 8 ─────────────────────────────────────────────────────────────────────


def build_league_matchdays(results: list[dict]) -> dict[str, list[dict]]:
    """Group results by matchday prefix.

    Each row gains explicit canonical state fields (Exchange 2 truth
    contract): ``status`` ("played" — rows come from the results ledger),
    derived ``winner``, and ``provenance``.
    """
    from football_core.domain import canonical_from_result_entry

    mds: dict[str, list[dict]] = defaultdict(list)
    for m in results:
        prefix = m.get("match_id", "").split("_")[0]
        row = dict(m)
        cm = canonical_from_result_entry(m, "ucl")
        row.setdefault("winner", cm.winner)
        row["status"] = cm.status.value
        row["provenance"] = "official"
        mds[prefix].append(row)
    return dict(sorted(mds.items()))


# ── 9 ─────────────────────────────────────────────────────────────────────


def ucl_form_trend(team: str, results: list[dict]) -> list[dict]:
    """Return last 5 results for a team from results list.

    Delegates to the shared kernel in football_core.insight.
    """
    from football_core.insight import form_trend as _core_form_trend
    return _core_form_trend(results, team, limit=5)


# ── 10 ────────────────────────────────────────────────────────────────────


def ucl_head_to_head(ta: str, tb: str, results: list[dict]) -> dict:
    """H2H stats between two teams from results list.

    Delegates to the shared kernel in football_core.insight.
    """
    from football_core.insight import head_to_head as _core_head_to_head
    return _core_head_to_head(results, ta, tb)


# ── 11 ────────────────────────────────────────────────────────────────────


def ucl_outcome_dist(blended_prob: float, elo_a: float, elo_b: float) -> dict:
    """Estimate outcome distribution from blended probability.

    Delegates to the shared kernel in football_core.insight.
    """
    from football_core.insight import outcome_distribution as _core_outcome_dist
    return _core_outcome_dist(blended_prob, elo_a, elo_b)


# ── 12 ────────────────────────────────────────────────────────────────────


def ucl_insight_text(ta: str, tb: str, signals: dict, form_trends: dict, h2h: dict, outcome: dict, eval_data: dict) -> str:
    """Generate natural-language insight for a match.

    Delegates to the shared kernel in football_core.insight.
    """
    from football_core.insight import insight_text as _core_insight_text
    return _core_insight_text(ta, tb, signals, form_trends, h2h, outcome, eval_data)


# ── 13 ────────────────────────────────────────────────────────────────────


def run_mc_simulation(
    data_dir: str | Path,
    n_iterations: int = 10000,
    seed: int | None = None,
    weights: dict[str, float] | None = None,
    show_ci: str = "auto",
    bsd_api_key: str = "",
    team_aliases: dict[str, str] | None = None,
    progress_cb=None,
    elo_ratings_override: dict[str, float] | None = None,
    played_matches: dict[tuple[str, str], tuple[int, int]] | None = None,
) -> dict:
    """Run a full Monte Carlo simulation pipeline.

    Exchange 3 truth semantics:
    - real league results on disk are injected as immutable facts into
      every iteration (never resampled);
    - an explicit ``elo_ratings_override`` avoids live ClubElo calls so a
      simulation can run fully offline (snapshot mode);
    - ``seed=None`` lets the generic engine generate a seed that is
      returned in the payload for reproducibility.

    Returns a dict with keys: mode, teams, all_teams, n_teams, n_iterations,
    seed, snapshot_date, champion, standings, playoff, bracket_rounds,
    sim_state_payload, odds, signals, elo_ratings, calibration, show_ci.
    Does NOT write to disk, global cache, or ``boot_log_local``.
    """
    dp = Path(data_dir) if isinstance(data_dir, str) else data_dir
    from competitions.ucl.src.provider import RepoFixtureProvider

    if progress_cb:
        progress_cb(0, 100, "Loading fixtures...")

    fixtures_path = str(dp / "fixtures.json")
    provider = RepoFixtureProvider(fixtures_path=fixtures_path).load()
    if progress_cb:
        progress_cb(5, 100, "Loading fixtures...")

    if elo_ratings_override:
        elo_ratings = dict(elo_ratings_override)
    else:
        from competitions.ucl.src.elo_fetcher import fetch_team_elos
        team_names = [t.name for t in provider.teams]
        elo_ratings = fetch_team_elos(team_names)
        if not elo_ratings:
            elo_ratings = {}
            coefficients = {t.name: t.coefficient for t in provider.teams}
            max_coeff = max(coefficients.values()) if coefficients else 100
            for t in team_names:
                c = coefficients.get(t, 50)
                elo_ratings[t] = 1400.0 + (c / max_coeff) * 400.0
    if progress_cb:
        progress_cb(10, 100, "Resolving Elo ratings...")

    # Real league results are immutable facts for every iteration.
    from competitions.ucl.src.orchestrator import _load_league_played_pairs
    played_pairs = (
        played_matches if played_matches is not None
        else _load_league_played_pairs(dp)
    )

    resolved_seed = seed  # None -> engine generates one and returns it
    if progress_cb:

        def _mc_progress(current, total):
            # Exchange 5 doc-sync fix: report (iteration, total_iterations)
            # directly - the old (pct, current) form made the progress
            # "iteration" field show percentages instead of real counts.
            progress_cb(current, total)
    else:
        _mc_progress = None

    result = build_simulation_result(provider, elo_ratings, resolved_seed, n_iterations, played_matches=played_pairs, progress_cb=_mc_progress)
    if progress_cb:
        progress_cb(85, n_iterations)

    engine = build_signal_engine(elo_ratings, weights_override=weights)

    # Exchange 2 unification: the clean state payload is assembled once
    # (shared with orchestrator.run_compute_all) and feeds both the
    # canonical state layer and the legacy display keys below.
    sim_state_payload = build_sim_state_payload(
        result.playoff_ties,
        result.playoff_winners,
        result.bracket_rounds,
        champion_probs=_top_champion_probs(result.teams),
    )
    playoff_display = sim_state_payload["playoff"]
    enriched_bracket = sim_state_payload["bracket_rounds"]

    sorted_teams = sorted(result.teams.items(), key=lambda x: (-x[1].get("champion_prob", 0.0), x[0]))
    odds_display = []
    for rank, (name, td) in enumerate(sorted_teams, start=1):
        odds_display.append({
            "rank": rank, "team": name,
            "champion_prob": td.get("champion_prob", 0.0),
            "final_prob": td.get("stage_final_prob", 0.0),
            "sf_prob": td.get("stage_sf_prob", 0.0),
            "qf_prob": td.get("stage_qf_prob", 0.0),
            "top_8_prob": td.get("top_8_prob", 0.0),
            "playoff_prob": td.get("playoff_prob", 0.0),
            "avg_position": td.get("avg_position", 0.0),
        })

    standings_display = []
    for entry in result.standings:
        zone = entry.get("zone", "eliminated")
        standings_display.append({
            "position": entry.get("position"), "team": entry.get("team"),
            "pts": entry.get("pts"), "gd": entry.get("gd"),
            "gs": entry.get("gs"), "zone": zone,
        })

    top4 = [odds_display[i] for i in range(min(4, len(odds_display)))]

    signal_stats = {}
    try:
        signal_matches = []
        for md in provider.matchdays:
            for m in md:
                signal_matches.append({"team_a": m.team_a, "team_b": m.team_b, "match_id": m.match_id})
        signal_context = PredictionContext(
            fixtures=signal_matches, elo_ratings=elo_ratings,
        )
        blended = [engine.evaluate(m, signal_context) for m in signal_matches]
        sig_data = {}
        for bp in blended:
            for sig, sd in bp.signal_breakdown.items():
                if sig not in sig_data:
                    sig_data[sig] = {"probs": [], "n": 0, "available": 0}
                sig_data[sig]["n"] += 1
                if sd.get("available", True):
                    sig_data[sig]["available"] += 1
                else:
                    sig_data[sig].setdefault("not_available", 0)
                    sig_data[sig]["not_available"] += 1
                if sd.get("weight", 0) > 0:
                    sig_data[sig]["probs"].extend([sd.get("home", 0.5), sd.get("draw", 0), sd.get("away", 0)])
        for sig, sd in sorted(sig_data.items()):
            probs = [p for p in sd["probs"] if p is not None]
            avg = sum(probs) / len(probs) if probs else 0
            signal_stats[sig] = {
                "n_matches": sd["n"], "available": sd["available"],
                "available_pct": round(sd["available"] / sd["n"] * 100, 1) if sd["n"] else 0,
                "avg_probability": round(avg, 4),
                "weight": round(engine.weights.get(sig, 0), 4),
            }
    except Exception:
        signal_stats = {}

    if progress_cb:
        progress_cb(95, n_iterations)
        progress_cb(100, n_iterations)

    return {
        "mode": "simulation",
        "teams": top4, "all_teams": odds_display,
        "n_teams": len(result.teams), "n_iterations": result.n_iterations,
        "seed": result.seed, "snapshot_date": result.snapshot_date,
        "champion": result.bracket_champion, "standings": standings_display,
        "playoff": playoff_display, "bracket_rounds": enriched_bracket,
        "sim_state_payload": sim_state_payload,
        "odds": odds_display, "signals": signal_stats, "elo_ratings": elo_ratings,
        "show_ci": show_ci,
        "_meta": {
            # SimulationResult.seed is the ENGINE-RESOLVED seed (generated
            # when the request passed None), so runs stay reproducible.
            "n_simulations": result.n_iterations,
            "seed": result.seed,
            "engine_version": "monte-carlo-v1",
            "provenance": {
                "real_results_preserved": True,
                "simulated_matches_only": True,
                "league_matches_conditioned": sorted(played_pairs) if played_pairs else [],
            },
        },
    }


# ── 14 ────────────────────────────────────────────────────────────────────


def run_calibration_task(
    data_dir: str | Path,
    replay_data: str | None = None,
    progress_cb=None,
) -> dict:
    """Run calibration against replay data.

    Pure computation — no threading, no global state.
    Returns a dict with status, n_matches, weights, per_signal, calibration.
    """
    from competitions.ucl.src.calibrate import run_calibration

    dp = Path(data_dir) if isinstance(data_dir, str) else data_dir
    replay_path = replay_data or str(dp / "results.json")
    if progress_cb:
        progress_cb(10, f"Loading replay data from {os.path.basename(replay_path)}...")

    config = run_calibration(replay_data_path=replay_path)
    if progress_cb:
        progress_cb(90, "Saving calibration weights...")
        progress_cb(100, "Complete")

    return {
        "status": "ok",
        "n_matches": config.get("n_matches", 0),
        "weights": config.get("weights", {}),
        "per_signal": config.get("per_signal", {}),
    }
