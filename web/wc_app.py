import json, os, sys, time, random, copy, uuid
from pathlib import Path
from datetime import datetime, timezone
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

import fastapi
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from dotenv import load_dotenv
import requests

import competitions.worldcup
from competitions.worldcup.src import constants, elo
from football_core.signal import PredictionContext
from competitions.worldcup.src.knockout import run_full_simulation, resolve_knockout_slot_teams
from competitions.worldcup.src.state import load_groups, load_annex_c, save_signal_cache, save_calibration_params, load_calibration_params
from competitions.worldcup.src.engine import run_calibrate_and_blend
from competitions.worldcup.src.analysis import run_calibrated_validation
from competitions.worldcup.src.evaluation import evaluate_all_matches
from competitions.worldcup.src.constants import (
    CATBOOST_CACHE_FILE, FORM_CACHE_FILE, LINEUP_CACHE_FILE,
    ODDS_CACHE_FILE, DEFENSIVE_CACHE_FILE, MANAGER_EFFECT_CACHE_FILE,
    AVAILABILITY_CACHE_FILE,
)
from football_core.groups import precompute_matchup_lambdas, simulate_group_matches
from competitions.worldcup.src.groups import (
    compute_standings, rank_third_placed, select_advancers, resolve_r32_matchups,
)

from web.insight import compute_team_signal_strengths, compute_ko_signal_probs, compute_match_insight, compute_form_trend, compute_head_to_head, compute_match_outcome
from web.engine_helpers import compute_team_strengths_from_predictions, _build_engine_from_caches
from web.whatif_engine import parse_scenario, handle_instant_scenario, generate_simulate_insight
from web.common import ts, boot_step, load_json, load_json_list

load_dotenv()
BSD_API_KEY = os.getenv("BSD_API_KEY", "")

DATA_DIR = constants.DATA_DIR

cache: dict = {}
boot_log: list[dict] = []
active_simulations: dict[str, dict] = {}
sim_lock = threading.Lock()


def _build_match_score(played_m):
    if not played_m:
        return None
    hs = played_m.get("home_score")
    as_ = played_m.get("away_score")
    if hs is not None and as_ is not None:
        return {"home": hs, "away": as_}
    return played_m.get("score")


def compute_bracket_display(groups, teams, bracket, annex_c, played, played_groups):
    elo_ratings = {n: d["elo"] for n, d in teams.items()}
    known_winners = {mid: data["winner"] for mid, data in played.items() if data.get("winner")}
    slot_teams = resolve_knockout_slot_teams(groups, teams, played_groups, bracket, annex_c, known_winners)
    matchups = []
    for mid, st in sorted(slot_teams.items()):
        ta, tb = st["team_a"], st["team_b"]
        prob_a = round(elo.expected_score(elo_ratings.get(ta, 1500), elo_ratings.get(tb, 1500)), 4) if ta in elo_ratings and tb in elo_ratings else 0.5
        played_m = played.get(mid)
        matchups.append({
            "match_id": mid,
            "team_a": ta,
            "team_b": tb,
            "prob_a": prob_a,
            "winner": played_m.get("winner") if played_m else None,
            "score": _build_match_score(played_m),
            "played": mid in played,
        })
    return {"rounds": {"R32": matchups}, "n_matchups": len(matchups)}


def compute_full_bracket(groups, teams, bracket, annex_c, played, played_groups, engine_predictions=None):
    from web.engine_helpers import compute_team_strengths_from_predictions
    elo_ratings = {n: d["elo"] for n, d in teams.items()}
    known_winners = {mid: data["winner"] for mid, data in played.items() if data.get("winner")}
    slot_teams = resolve_knockout_slot_teams(groups, teams, played_groups, bracket, annex_c, known_winners)
    resolved = {}

    def _entry_for(mid):
        for b in bracket:
            if b["match_id"] == mid:
                return b
        return None

    team_strengths = {}
    all_matches = []
    groups_data = groups.get("groups", groups) if isinstance(groups, dict) else groups
    for g in groups_data.values():
        for m in g.get("matches", []):
            all_matches.append(m)
    for m in bracket:
        all_matches.append(m)

    if engine_predictions and len(engine_predictions) == len(all_matches):
        team_strengths = compute_team_strengths_from_predictions(engine_predictions, all_matches)
    else:
        team_strengths = {}

    def _signal_probs(ta, tb):
        if team_strengths:
            sigs, elo_p = compute_ko_signal_probs(ta, tb, team_strengths, elo_ratings)
            return sigs, elo_p
        return {}, 0.5

    for mid, st in slot_teams.items():
        ta, tb = st["team_a"], st["team_b"]
        be = _entry_for(mid)
        rnd = be["round"] if be else "R32"
        prob_a = round(elo.expected_score(elo_ratings.get(ta, 1500), elo_ratings.get(tb, 1500)), 4) \
            if ta in elo_ratings and tb in elo_ratings else 0.5
        played_m = played.get(mid)
        sigs, elo_p = _signal_probs(ta, tb)
        resolved[mid] = {
            "match_id": mid, "round": rnd,
            "team_a": ta, "team_b": tb,
            "prob_a": prob_a,
            "winner": played_m.get("winner") if played_m else None,
            "score": _build_match_score(played_m),
            "played": mid in played,
            "source_matches": be.get("source_matches") if be else None,
            "signals": sigs,
        }

    def _resolve_teams_from_source(entry):
        sms = entry.get("source_matches", [])
        if not sms:
            return None, None
        if entry["round"] == "TPP":
            teams_ab = []
            for sm in sms:
                src = resolved.get(sm)
                if src and src["winner"] and src["team_a"] and src["team_b"]:
                    teams_ab.append(src["team_b"] if src["winner"] == src["team_a"] else src["team_a"])
                else:
                    teams_ab.append(None)
            return teams_ab[0] if len(teams_ab) > 0 else None, \
                   teams_ab[1] if len(teams_ab) > 1 else None
        ta_src = resolved.get(sms[0])
        tb_src = resolved.get(sms[1]) if len(sms) > 1 else None
        return (ta_src.get("winner") if ta_src else None,
                tb_src.get("winner") if tb_src else None)

    for entry in bracket:
        mid = entry["match_id"]
        if mid in resolved:
            if not resolved[mid].get("source_matches") and entry.get("source_matches"):
                resolved[mid]["source_matches"] = entry["source_matches"]
            continue
        ta, tb = _resolve_teams_from_source(entry)
        prob_a = round(elo.expected_score(elo_ratings.get(ta, 1500), elo_ratings.get(tb, 1500)), 4) \
            if ta and tb and ta in elo_ratings and tb in elo_ratings else 0.5
        played_m = played.get(mid)
        sigs, elo_p = _signal_probs(ta or "", tb or "")
        resolved[mid] = {
            "match_id": mid, "round": entry["round"],
            "team_a": ta, "team_b": tb,
            "prob_a": prob_a,
            "winner": played_m.get("winner") if played_m else None,
            "score": _build_match_score(played_m),
            "played": mid in played,
            "source_matches": entry.get("source_matches"),
            "signals": sigs,
        }

    rounds_order = ["R32", "R16", "QF", "SF", "TPP", "FINAL"]
    rounds_data = {r: [] for r in rounds_order}
    for data in resolved.values():
        r = data["round"]
        if r in rounds_data:
            rounds_data[r].append(data)
    return {"rounds": rounds_data, "n_matchups": len(resolved)}


def build_chronological_matches() -> dict:
    """Build chronological match listing grouped by round.

    Returns: {rounds: [{round_name, round_type, matches}]}
    """
    teams_raw = load_json(DATA_DIR, "teams.json")
    groups = load_groups(DATA_DIR, teams=teams_raw)
    groups_data = groups.get("groups", groups) if isinstance(groups, dict) else groups
    groups_data = groups_data if isinstance(groups_data, dict) else {}
    bracket_raw = json.loads((DATA_DIR / "bracket.json").read_text(encoding="utf-8"))
    played_groups_raw = load_json(DATA_DIR, "played_groups.json") or {}
    played_raw = load_json(DATA_DIR, "played.json") or {}

    rounds = []

    for gk in sorted(groups_data.keys()):
        g = groups_data[gk]
        matches = []
        for m in g.get("matches", []):
            mid = m["match_id"]
            r = played_groups_raw.get(mid, {})
            matches.append({
                "match_id": mid,
                "date": r.get("completed_at"),
                "team_a": m["team_a"],
                "team_b": m["team_b"],
                "home_score": r.get("home_score"),
                "away_score": r.get("away_score"),
                "winner": r.get("winner"),
                "played": mid in played_groups_raw,
                "status": "played" if mid in played_groups_raw else "tbd",
                "matchday": m.get("matchday"),
            })
        if matches:
            rounds.append({"round_name": "Group " + gk, "round_type": "group", "matches": matches})

    KO_ROUND_TYPES = {"R32": "r32", "R16": "r16", "QF": "qf", "SF": "sf", "TPP": "tpp", "FINAL": "final"}
    ko_rounds_order = ["R32", "R16", "QF", "SF", "TPP", "FINAL"]
    for round_name in ko_rounds_order:
        matches = []
        for be in bracket_raw:
            if be.get("round") != round_name:
                continue
            mid = be["match_id"]
            r = played_raw.get(mid, {})
            matches.append({
                "match_id": mid,
                "date": r.get("completed_at"),
                "team_a": r.get("team_a"),
                "team_b": r.get("team_b"),
                "home_score": r.get("home_score"),
                "away_score": r.get("away_score"),
                "winner": r.get("winner"),
                "played": mid in played_raw,
                "status": "played" if mid in played_raw else "tbd",
                "source_matches": be.get("source_matches"),
            })
        if matches:
            rounds.append({"round_name": round_name, "round_type": KO_ROUND_TYPES.get(round_name, "ko"), "matches": matches})

    return {"rounds": rounds}


def build_knockout_tree() -> dict:
    """Build knockout tree structure with resolved teams for all rounds.

    Returns: {round_name: [{match_id, team_a, team_b, score, winner, played, source_matches}]}
    """
    teams_raw = load_json(DATA_DIR, "teams.json")
    groups = load_groups(DATA_DIR, teams=teams_raw)
    bracket_raw = json.loads((DATA_DIR / "bracket.json").read_text(encoding="utf-8"))
    annex_c = load_annex_c(DATA_DIR)
    played_raw = load_json(DATA_DIR, "played.json") or {}
    played_groups_raw = load_json(DATA_DIR, "played_groups.json") or {}

    fb = compute_full_bracket(groups, teams_raw, bracket_raw, annex_c, played_raw, played_groups_raw)
    return fb.get("rounds", {})


def compute_group_standings(groups, teams, played_groups):
    groups_data = groups.get("groups", groups)
    elo_ratings = {n: d["elo"] for n, d in teams.items()}
    rng = random.Random(0)
    lambdas = precompute_matchup_lambdas(groups_data, elo_ratings, base_rate=constants.EXPECTED_GOALS_BASE_RATE)
    results = simulate_group_matches(
        groups_data, teams, elo_ratings, rng,
        fair_play=False, matchup_lambdas=lambdas,
        played_groups=played_groups or {},
        base_rate=constants.EXPECTED_GOALS_BASE_RATE,
    )
    standings = compute_standings(results, elo_ratings)
    third = rank_third_placed(standings)
    return standings, third


def compute_signal_briers_from_predictions(
    engine_predictions: list,
    all_matches: list[dict],
    played: dict,
    played_groups: dict,
) -> dict[str, dict]:
    """Compute per-signal Brier/log-loss/accuracy from engine predictions.

    Uses zip() to associate each BlendedPrediction with its match fixture
    (since BlendedPrediction has no match_id field).

    Returns: {signal_name: {"brier": ..., "log_loss": ..., "accuracy": ..., "n": ...}}
    """
    played_all = dict(played)
    if played_groups:
        played_all.update(played_groups)

    accum: dict[str, list[tuple[float, float]]] = {}

    for bp, match in zip(engine_predictions, all_matches):
        mid = match.get("match_id", "")
        if not mid or mid not in played_all:
            continue
        m = played_all[mid]
        t_a, t_b = m.get("team_a", ""), m.get("team_b", "")
        winner = m.get("winner")
        if winner == t_a:
            actual = 1.0
        elif winner == t_b:
            actual = 0.0
        elif winner is None:
            actual = 0.5
        else:
            continue
        for sig_name, sd in (bp.signal_breakdown or {}).items():
            prob = sd.get("home", 0.33)
            accum.setdefault(sig_name, []).append((prob, actual))

    from football_core.evaluation import compute_metrics
    result = {}
    for sig_name, pairs in sorted(accum.items()):
        preds = [p for p, _ in pairs]
        actuals = [a for _, a in pairs]
        metrics = compute_metrics(preds, actuals)
        result[sig_name] = {
            "brier": round(metrics["brier"], 6),
            "log_loss": round(metrics["log_loss"], 6),
            "accuracy": round(metrics["accuracy"], 6),
            "n": metrics["n"],
        }
    return result


def compute_signal_eval(teams, played, played_groups, engine_predictions, all_matches):
    """Evaluate signals from engine predictions — no ledger dependency."""
    elo_report = evaluate_all_matches(teams, played, played_groups, signal_name="elo")
    signal_briers = compute_signal_briers_from_predictions(
        engine_predictions, all_matches, played, played_groups)
    all_report = evaluate_all_matches(
        teams, played, played_groups, signal_name=None,
        history=_build_eval_history_from_predictions(engine_predictions, all_matches, played, played_groups))
    return {"elo": elo_report, "all_signals": all_report}


def _build_eval_history_from_predictions(predictions, all_matches, played, played_groups):
    """Build eval history from BlendedPrediction list + match fixtures.

    Uses zip() since BlendedPrediction has no match_id field.
    """
    played_all = dict(played)
    if played_groups:
        played_all.update(played_groups)
    played_mids = set(played_all.keys())
    history = []
    for bp, match in zip(predictions, all_matches):
        mid = match.get("match_id", "")
        if not mid or mid not in played_mids:
            continue
        m = played_all[mid]
        t_a, t_b = m.get("team_a", ""), m.get("team_b", "")
        winner = m.get("winner")
        if winner == t_a:
            actual = 1.0
        elif winner == t_b:
            actual = 0.0
        elif winner is None:
            actual = 0.5
        else:
            continue
        sigs = {}
        for sk, sd in (bp.signal_breakdown or {}).items():
            prob = sd.get("home", 0.33)
            sigs[sk] = {"probability": prob, "available": True}
        if sigs:
            history.append({"match_id": mid, "actual": actual, "signals": sigs})
    return history


def compute_real_standings(groups_data: dict, played_groups: dict) -> list[dict]:
    """Compute deterministic real standings from played group matches.

    Returns a flat list sorted by group, then position:
    [{group, position, team, pts, gd, gs, ga, played}, ...]
    """
    standings = []
    for group_letter in sorted(groups_data.keys()):
        group = groups_data[group_letter]
        team_stats: dict[str, dict] = {}
        for match in group.get("matches", []):
            mid = match["match_id"]
            if mid not in played_groups:
                continue
            m = played_groups[mid]
            ta, tb = m["team_a"], m["team_b"]
            hs = m.get("home_score", 0)
            aw = m.get("away_score", 0)
            for team, gs, ga in [(ta, hs, aw), (tb, aw, hs)]:
                if team not in team_stats:
                    team_stats[team] = {"team": team, "group": group_letter, "pts": 0, "gd": 0, "gs": 0, "ga": 0, "played": 0}
                team_stats[team]["gs"] += gs
                team_stats[team]["ga"] += ga
                team_stats[team]["gd"] += (gs - ga)
                team_stats[team]["played"] += 1
            if hs > aw:
                team_stats[ta]["pts"] += 3
            elif aw > hs:
                team_stats[tb]["pts"] += 3
            else:
                team_stats[ta]["pts"] += 1
                team_stats[tb]["pts"] += 1
        sorted_teams = sorted(team_stats.values(), key=lambda t: (-t["pts"], -t["gd"], -t["gs"]))
        for i, t in enumerate(sorted_teams, 1):
            t["position"] = i
            standings.append(t)
    return standings


def compute_signals_meta() -> dict:
    """Check on-disk signal cache files and return metadata."""
    cache_files: list[tuple[str, str]] = [
        ("odds_cache.json", "market_odds"),
        ("catboost_cache.json", "catboost"),
        ("form_cache.json", "form"),
        ("lineup_cache.json", "lineup_strength"),
        ("defensive_cache.json", "defensive_quality"),
        ("manager_effect_cache.json", "manager_effect"),
        ("availability_cache.json", "availability"),
    ]
    signals = []
    for fname, sname in cache_files:
        path = DATA_DIR / fname
        exists = path.exists()
        mtime = None
        if exists:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        signals.append({"name": sname, "available": exists, "last_updated": mtime})
    return {"signals": signals, "n_total": len(signals)}


def compute_overview() -> dict:
    """Real-data-first overview — no simulation, no engine predictions.

    Loads teams, groups, bracket, played results from disk and computes
    deterministic standings and bracket display only.
    """
    global boot_log
    boot_log = []
    data = {"boot": []}

    ld = boot_step("Data Loading", lambda: {
        "teams": load_json(DATA_DIR, "teams.json"),
        "groups": load_groups(DATA_DIR, teams=load_json(DATA_DIR, "teams.json")),
        "bracket": json.loads((DATA_DIR / "bracket.json").read_text(encoding="utf-8")),
        "annex_c": json.loads((DATA_DIR / "annex_c.json").read_text(encoding="utf-8")),
        "played": json.loads((DATA_DIR / "played.json").read_text(encoding="utf-8")) if (DATA_DIR / "played.json").exists() else {},
        "played_groups": json.loads((DATA_DIR / "played_groups.json").read_text(encoding="utf-8")) if (DATA_DIR / "played_groups.json").exists() else {},
        "versions": json.loads((DATA_DIR / "versions.json").read_text(encoding="utf-8")) if (DATA_DIR / "versions.json").exists() else {},
    }, boot_log)
    if not ld:
        return {"boot": boot_log, "error": "data load failed"}
    teams, groups_data = ld["teams"], ld["groups"]["groups"]
    bracket, annex_c = ld["bracket"], ld["annex_c"]
    played, played_groups = ld["played"], ld["played_groups"]
    versions = ld["versions"]

    total_played = sum(1 for m in played.values() if m.get("winner"))
    total_played += sum(1 for m in played_groups.values() if m.get("winner"))

    gs = boot_step("Group Standings", lambda:
        compute_real_standings(groups_data, played_groups)
    , boot_log) or []

    bracket_display = boot_step("Bracket Resolution", lambda:
        compute_bracket_display(ld["groups"], teams, bracket, annex_c, played, played_groups)
    , boot_log)

    signals_meta = compute_signals_meta()

    gov = boot_step("Governance", lambda: {
        "versions": versions,
        "n_matches": total_played,
        "n_signals": signals_meta.get("n_total", 0),
        "status": "COLD_START" if total_played < 30 else "HEALTHY",
    }, boot_log)

    team_list = [{"name": name, "elo": round(d["elo"], 1)} for name, d in sorted(teams.items(), key=lambda t: t[1].get("elo", 1500), reverse=True)]

    data["boot"] = boot_log
    data["teams"] = team_list
    data["n_teams"] = len(team_list)
    data["n_played"] = total_played
    data["standings"] = gs
    data["bracket"] = bracket_display
    data["governance"] = gov if gov else {}
    data["signals_meta"] = signals_meta
    return data


def compute_signal_stats():
    """Signal statistics from on-disk caches — no ledger dependency."""
    from competitions.worldcup.src.state import load_signal_cache
    data_dir = constants.DATA_DIR
    cache_files: list[tuple[str, str]] = [
        ("odds_cache.json", "market_odds"),
        ("catboost_cache.json", "catboost"),
        ("form_cache.json", "form"),
        ("lineup_cache.json", "lineup_strength"),
        ("defensive_cache.json", "defensive_quality"),
        ("manager_effect_cache.json", "manager_effect"),
        ("availability_cache.json", "availability"),
    ]
    signal_data: dict[str, dict] = {}
    n_total = 0
    for fname, sname in cache_files:
        cache = load_signal_cache(fname, data_dir)
        matches = (cache or {}).get("matches", {})
        if not matches:
            continue
        n_total += len(matches)
        probs = []
        avail = 0
        for mid, entry in matches.items():
            if entry.get("available", False):
                avail += 1
            prob = entry.get("probability")
            if prob is not None:
                probs.append(prob)
        signal_data[sname] = {
            "n_matches": len(matches),
            "available": avail,
            "available_pct": round(avail / len(matches) * 100, 1) if matches else 0,
            "avg_probability": round(sum(probs) / len(probs), 4) if probs else 0,
            "min_probability": round(min(probs), 4) if probs else 0,
            "max_probability": round(max(probs), 4) if probs else 0,
        }
    return {"signals": signal_data, "n_total": n_total}


def compute_signal_detail(name: str):
    data_dir = constants.DATA_DIR
    ledger = json.loads((data_dir / "predictions_ledger.json").read_text(encoding="utf-8"))
    played = json.loads((data_dir / "played.json").read_text(encoding="utf-8"))
    played_groups_raw = (data_dir / "played_groups.json").read_text(encoding="utf-8")
    played_groups = json.loads(played_groups_raw) if played_groups_raw.strip() else {}
    matches = []
    eval_matches = 0
    correct = 0
    brier_sum = 0.0
    for mid, signals in ledger.items():
        if name not in signals:
            continue
        sv = signals[name]
        match_data = {"match_id": mid, "probability": sv.get("probability"), "available": sv.get("available", False), "reason": sv.get("reason")}
        if mid in played:
            m = played[mid]
            match_data["team_a"] = m.get("team_a", "")
            match_data["team_b"] = m.get("team_b", "")
            match_data["result"] = m.get("winner")
        elif mid in played_groups:
            m = played_groups[mid]
            match_data["team_a"] = m.get("team_a", "")
            match_data["team_b"] = m.get("team_b", "")
            match_data["result"] = m.get("winner")
        else:
            match_data["team_a"] = sv.get("team_a", "")
            match_data["team_b"] = sv.get("team_b", "")
        matches.append(match_data)
        prob = sv.get("probability")
        result = match_data.get("result")
        if prob is not None and result is not None:
            eval_matches += 1
            actual = 1.0 if result == match_data.get("team_a") else (0.0 if result == match_data.get("team_b") else 0.5)
            brier_sum += (prob - actual) ** 2
            if (actual == 1.0 and prob > 0.5) or (actual == 0.0 and prob < 0.5) or (actual == 0.5):
                correct += 1
    ev = cache.get("evaluation", {})
    sig_eval = ev.get(name, {})
    return {
        "name": name,
        "n_matches": len(matches),
        "n_with_results": eval_matches,
        "live_eval": {
            "brier": round(brier_sum / eval_matches, 4) if eval_matches else None,
            "accuracy": round(correct / eval_matches, 4) if eval_matches else None,
            "n": eval_matches,
        },
        "cache_eval": sig_eval if sig_eval.get("n_matches", 0) > 0 else None,
        "matches": matches,
    }


def compute_blend_info():
    """Blend info from in-memory cache evaluation + backtest — no cached file."""
    data_dir = constants.DATA_DIR
    backtest_path = data_dir / "eval_backtest_report.json"
    backtest = json.loads(backtest_path.read_text(encoding="utf-8")) if backtest_path.exists() else {}
    eval_data = cache.get("evaluation", {})
    available_signals = sorted(k for k in eval_data if k != "elo" and eval_data[k].get("n_matches", 0) > 0)
    n_available = len(available_signals)
    per_signal = backtest.get("per_signal", {})
    briers = {}
    for sk, sv in per_signal.items():
        b = sv.get("brier")
        if b is not None:
            briers[sk] = b
    for sk in available_signals:
        if sk not in briers:
            briers[sk] = 0.25
    total_inv = sum(1.0 / max(b, 0.01) for b in briers.values()) if briers else 1
    weights = {sk: round((1.0 / max(b, 0.01)) / total_inv, 4) for sk, b in briers.items()} if total_inv else {}
    gov = cache.get("governance", {})
    n_matches = gov.get("n_matches", 0)
    return {
        "n_signals_available": n_available,
        "available_signals": available_signals,
        "blend_weights": weights,
        "backtest_briers": {sk: round(b, 4) for sk, b in briers.items()},
        "calibration_status": "cold_start" if n_matches < 30 else "calibrated",
        "n_matches_for_calibration": n_matches,
        "threshold": 30,
    }


def _fetch_live_data() -> None:
    """Fetch all live data from BSD API at startup.

    Fetches match results + all 7 signal predictors, saves signal caches
    to DATA_DIR so _build_engine_from_caches() finds them. No ledger writes.
    Called once at server startup if BSD_API_KEY is set.
    """
    if not BSD_API_KEY:
        return
    data_dir = DATA_DIR
    try:
        teams = json.loads((data_dir / "teams.json").read_text(encoding="utf-8"))
        groups = json.loads((data_dir / "groups.json").read_text(encoding="utf-8"))
        bracket_raw = json.loads((data_dir / "bracket.json").read_text(encoding="utf-8"))
        aliases = json.loads((data_dir / "team_aliases.json").read_text(encoding="utf-8"))
    except Exception:
        return

    # 1. Fetch and process match results
    try:
        from competitions.worldcup.src.fetcher import build_historic_url, process_matches, process_group_matches
        from football_core.fetcher import fetch_raw_matches
        url = build_historic_url()
        raw_matches = fetch_raw_matches(BSD_API_KEY, url, constants.DEFAULT_LEAGUE_ID)

        played_groups_path = data_dir / "played_groups.json"
        played_groups = json.loads(played_groups_path.read_text(encoding="utf-8")) if played_groups_path.exists() else {}
        played_group_ids = set(played_groups.keys())
        new_grp = process_group_matches(raw_matches, teams, groups, aliases, played_group_ids, set())
        for m in new_grp:
            played_groups[m["match_id"]] = m
        played_groups_path.write_text(json.dumps(played_groups, indent=2, ensure_ascii=False), encoding="utf-8")

        annex_c = load_annex_c(DATA_DIR)
        played_path = data_dir / "played.json"
        played = json.loads(played_path.read_text(encoding="utf-8")) if played_path.exists() else {}
        known_winners = {mid: d["winner"] for mid, d in played.items() if d.get("winner")}
        slot_teams = resolve_knockout_slot_teams(groups, teams, played_groups, bracket_raw, annex_c, known_winners)
        resolved_bracket = [
            {"match_id": mid, "team_a": st["team_a"], "team_b": st["team_b"]}
            for mid, st in slot_teams.items()
            if st.get("team_a") and st.get("team_b")
        ]
        played_ids = set(played.keys())
        new_ko = process_matches(raw_matches, teams, resolved_bracket, aliases, played_ids)
        for m in new_ko:
            played[m["match_id"]] = m
        played_path.write_text(json.dumps(played, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    # 2. Fetch and cache all 7 signal predictors
    try:
        from competitions.worldcup.src.predictors.catboost import fetch_and_cache_catboost
        from competitions.worldcup.src.predictors.lineup import compute_lineup_signal
        from competitions.worldcup.src.predictors.form import compute_form_signal
        from competitions.worldcup.src.predictors.odds import fetch_and_cache_odds
        from competitions.worldcup.src.predictors.manager_signals import fetch_and_cache_manager_signals
        from competitions.worldcup.src.predictors.availability import fetch_and_cache_availability_signal

        cb_cache = fetch_and_cache_catboost(BSD_API_KEY, aliases, groups, bracket_raw)
        save_signal_cache(cb_cache, CATBOOST_CACHE_FILE, DATA_DIR)

        lineup_cache = compute_lineup_signal(groups, bracket=bracket_raw)
        save_signal_cache(lineup_cache, LINEUP_CACHE_FILE, DATA_DIR)

        form_cache = compute_form_signal(teams, groups, bracket=bracket_raw)
        save_signal_cache(form_cache, FORM_CACHE_FILE, DATA_DIR)

        odds_cache = fetch_and_cache_odds(BSD_API_KEY, raw_matches, aliases, groups, bracket=bracket_raw)
        save_signal_cache(odds_cache, ODDS_CACHE_FILE, DATA_DIR)

        defensive_cache, manager_cache = fetch_and_cache_manager_signals(BSD_API_KEY, groups, bracket=bracket_raw)
        save_signal_cache(defensive_cache, DEFENSIVE_CACHE_FILE, DATA_DIR)
        save_signal_cache(manager_cache, MANAGER_EFFECT_CACHE_FILE, DATA_DIR)

        ex = ThreadPoolExecutor(max_workers=1)
        try:
            f = ex.submit(fetch_and_cache_availability_signal, BSD_API_KEY, groups, bracket=bracket_raw)
            avail_cache = f.result(timeout=30)
            save_signal_cache(avail_cache, AVAILABILITY_CACHE_FILE, DATA_DIR)
        except FuturesTimeout:
            pass
        finally:
            ex.shutdown(wait=False)
    except Exception:
        pass



wc_app = fastapi.FastAPI()


@wc_app.get("/api/data")
def api_data():
    return JSONResponse({
        "teams": cache.get("teams", []),
        "n_teams": cache.get("n_teams", 0),
        "total_iterations": cache.get("total_iterations", 0),
        "n_played": cache.get("n_played", 0),
    })


@wc_app.get("/api/overview")
def api_overview():
    return JSONResponse({
        "standings": cache.get("standings", []),
        "teams": cache.get("teams", []),
        "n_teams": cache.get("n_teams", 0),
        "n_played": cache.get("n_played", 0),
        "signals_meta": cache.get("signals_meta", {"signals": [], "n_total": 0}),
        "governance": cache.get("governance", {}),
        "top_teams": cache.get("top_teams", []),
        "signal_eval": cache.get("signal_eval", {}),
        "simulation_meta": cache.get("simulation_meta", None),
    })


@wc_app.get("/api/boot")
def api_boot():
    return JSONResponse(cache.get("boot", []))


@wc_app.get("/api/standings")
def api_standings():
    return JSONResponse({"standings": cache.get("standings", {}), "third_place": cache.get("third_place", [])})


@wc_app.get("/api/bracket")
def api_bracket():
    return JSONResponse(cache.get("bracket", {}))


@wc_app.get("/api/bracket/full")
def api_bracket_full():
    return JSONResponse(cache.get("full_bracket", {}))


@wc_app.get("/api/bracket/data")
def api_bracket_data():
    return JSONResponse({
        "chronological_rounds": build_chronological_matches().get("rounds", []),
        "knockout_tree": build_knockout_tree(),
    })


@wc_app.get("/api/evaluation")
def api_evaluation():
    return JSONResponse(cache.get("evaluation", {}))


@wc_app.get("/api/governance")
def api_governance():
    return JSONResponse(cache.get("governance", {}))


@wc_app.get("/api/backtest")
def api_backtest():
    return JSONResponse(cache.get("backtest", {}))


@wc_app.get("/api/coverage")
def api_coverage():
    return JSONResponse(cache.get("coverage", {}))


@wc_app.get("/api/signals")
def api_signals():
    return JSONResponse(compute_signal_stats())


@wc_app.get("/api/signal/{name}")
def api_signal_detail(name: str):
    return JSONResponse(compute_signal_detail(name))


@wc_app.get("/api/blend")
def api_blend():
    return JSONResponse(compute_blend_info())



def _run_simulation_task(
    task_id: str,
    iterations: int = 50000,
    seed: int | None = None,
    weights: dict[str, float] | None = None,
    show_ci: str = "auto",
):
    """Background simulation with progress reporting.

    Loads data from disk, builds engine from signal caches, computes
    predictions, runs Monte Carlo simulation, and updates global cache
    with top_teams and signal_eval.
    """
    try:
        t0 = time.time()
        with sim_lock:
            active_simulations[task_id] = {
                "status": "running", "progress": 0, "iteration": 0,
                "total_iterations": iterations, "stage": "Loading data...",
                "t0": t0, "elapsed": 0,
            }

        def _progress(pct, stage):
            with sim_lock:
                s = active_simulations[task_id]
                s["progress"] = pct
                s["stage"] = stage
                s["elapsed"] = time.time() - s.get("t0", time.time())

        _progress(0, "Loading data files...")
        teams_raw = load_json(DATA_DIR, "teams.json")
        groups_raw = load_groups(DATA_DIR, teams=teams_raw)
        bracket_raw = json.loads((DATA_DIR / "bracket.json").read_text(encoding="utf-8"))
        annex_c = load_annex_c(DATA_DIR)
        played_raw = json.loads((DATA_DIR / "played.json").read_text(encoding="utf-8")) if (DATA_DIR / "played.json").exists() else {}
        played_groups_raw = (DATA_DIR / "played_groups.json").read_text(encoding="utf-8")
        played_groups = json.loads(played_groups_raw) if played_groups_raw.strip() else {}
        elapsed = 0.0

        _progress(5, "Building prediction engine...")
        engine = _build_engine_from_caches(weights=weights)

        _progress(10, "Computing engine predictions...")
        elo_ratings = {n: d["elo"] for n, d in teams_raw.items()}
        groups_data = groups_raw.get("groups", groups_raw) if isinstance(groups_raw, dict) else groups_raw
        all_matches = []
        for g in groups_data.values():
            for m in g.get("matches", []):
                all_matches.append(m)
        for m in bracket_raw:
            all_matches.append(m)

        engine_predictions = []
        if engine:
            context = PredictionContext(
                fixtures=all_matches,
                elo_ratings=elo_ratings,
                played_results=list(played_raw.values()) + list(played_groups.values()),
            )
            for m in all_matches:
                bp = engine.evaluate(m, context)
                engine_predictions.append(bp)

        _progress(15, "Running Monte Carlo simulation...")
        def _sim_progress(current, total):
            pct = 15 + (current / max(total, 1) * 75)
            _progress(pct, f"Simulating match {current} of {total}")

        sim_result = run_full_simulation(
            teams_raw, groups_raw, bracket_raw, annex_c,
            played_raw, iterations=iterations,
            seed=seed if seed is not None else int(time.time()),
            played_groups=played_groups,
            progress_cb=_sim_progress,
        )

        _progress(92, "Computing top team rankings...")
        top_teams = sorted(
            [{"name": name, **probs} for name, probs in sim_result.items()],
            key=lambda t: t.get("champion", 0), reverse=True
        )

        _progress(95, "Evaluating prediction accuracy...")
        eval_metrics = compute_signal_eval(teams_raw, played_raw, played_groups, engine_predictions, all_matches)

        global cache
        overview = compute_overview()
        overview["top_teams"] = top_teams[:20]
        overview["signal_eval"] = eval_metrics
        overview["simulation_meta"] = {
            "iterations": iterations,
            "seed": seed,
            "weights": weights,
            "show_ci": show_ci,
            "n_top_teams": len(top_teams),
            "n_signals_evaluated": len(eval_metrics),
        }

        _progress(97, "Building full bracket tree...")
        full_bracket = compute_full_bracket(
            groups_raw, teams_raw, bracket_raw, annex_c,
            played_raw, played_groups, engine_predictions,
        )
        overview["full_bracket"] = full_bracket
        cache = overview

        _progress(100, "Complete")

        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "iterations": iterations,
            "seed": seed,
            "weights": weights,
            "show_ci": show_ci,
            "n_teams": overview.get("n_teams", 0),
            "n_played": overview.get("n_played", 0),
            "top_teams": top_teams[:20],
            "standings": overview.get("standings", []),
            "bracket": overview.get("bracket", {}),
            "signal_eval": eval_metrics,
            "signals_meta": overview.get("signals_meta", {"signals": [], "n_total": 0}),
            "governance": overview.get("governance", {}),
            "calibration": load_calibration_params(DATA_DIR),
        }
        (DATA_DIR / "snapshot.json").write_text(
            json.dumps(snapshot, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )

        with sim_lock:
            s = active_simulations[task_id]
            s["status"] = "complete"
            s["progress"] = 100
            s["elapsed"] = time.time() - t0
    except Exception as e:
        with sim_lock:
            active_simulations[task_id]["status"] = "error"
            active_simulations[task_id]["error"] = str(e)
            active_simulations[task_id]["elapsed"] = time.time() - t0


@wc_app.post("/api/simulate")
def api_simulate(req: dict = None):
    if not req:
        return JSONResponse({"error": "request body required"})
    iterations = int(req.get("iterations", 50000))
    iterations = max(1000, min(500000, iterations))
    seed = req.get("seed")
    if seed is not None:
        seed = int(seed)
    weights = req.get("weights")
    show_ci = str(req.get("show_ci", "auto"))
    task_id = str(uuid.uuid4())
    t = threading.Thread(
        target=_run_simulation_task,
        args=(task_id, iterations),
        kwargs={"seed": seed, "weights": weights, "show_ci": show_ci},
        daemon=True,
    )
    t.start()
    return JSONResponse({
        "task_id": task_id,
        "status": "started",
        "iterations": iterations,
        "seed": seed,
        "weights": weights,
        "show_ci": show_ci,
    })


@wc_app.get("/api/validation")
def api_validation():
    try:
        teams_raw = load_json(DATA_DIR, "teams.json")
        groups_raw = load_groups(DATA_DIR, teams=teams_raw)
        bracket_raw = json.loads((DATA_DIR / "bracket.json").read_text(encoding="utf-8"))
        annex_c = load_annex_c(DATA_DIR)
        played_raw = json.loads((DATA_DIR / "played.json").read_text(encoding="utf-8")) if (DATA_DIR / "played.json").exists() else {}
        played_groups_raw = (DATA_DIR / "played_groups.json").read_text(encoding="utf-8")
        played_groups = json.loads(played_groups_raw) if played_groups_raw.strip() else {}

        result = run_calibrated_validation(
            teams_raw, groups_raw, bracket_raw, annex_c,
            played_raw, played_groups, str(DATA_DIR),
        )
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@wc_app.get("/api/report")
def api_report():
    snapshot_path = DATA_DIR / "snapshot.json"
    if not snapshot_path.exists():
        return JSONResponse({"error": "no snapshot available — run a simulation first"})
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def _simulate_from_match_sync(match_id: str, iterations: int = 10000) -> dict:
    """Run a full simulation and extract probabilities for target + downstream matches."""
    teams_raw = load_json(DATA_DIR, "teams.json")
    groups_raw = load_groups(DATA_DIR, teams=teams_raw)
    bracket_raw = json.loads((DATA_DIR / "bracket.json").read_text(encoding="utf-8"))
    annex_c = load_annex_c(DATA_DIR)
    played_raw = load_json(DATA_DIR, "played.json") or {}
    played_groups_raw = load_json(DATA_DIR, "played_groups.json") or {}

    engine = _build_engine_from_caches()
    elo_ratings = {n: d["elo"] for n, d in teams_raw.items()}
    groups_data = groups_raw.get("groups", groups_raw) if isinstance(groups_raw, dict) else groups_raw
    all_matches = []
    for g in groups_data.values():
        for m in g.get("matches", []):
            all_matches.append(m)
    for m in bracket_raw:
        all_matches.append(m)

    engine_predictions = []
    if engine:
        from football_core.signal import PredictionContext
        context = PredictionContext(
            fixtures=all_matches,
            elo_ratings=elo_ratings,
            played_results=list(played_raw.values()) + list(played_groups_raw.values()),
        )
        for m in all_matches:
            bp = engine.evaluate(m, context)
            engine_predictions.append(bp)

    def _noop_progress(current, total):
        pass

    sim_result = run_full_simulation(
        teams_raw, groups_raw, bracket_raw, annex_c,
        played_raw, iterations=iterations,
        played_groups=played_groups_raw,
        progress_cb=_noop_progress,
    )

    bracket_entry = None
    for be in bracket_raw:
        if be["match_id"] == match_id:
            bracket_entry = be
            break

    downstream_ids = _collect_downstream_matches(match_id, bracket_raw)
    simulated = []
    for mid in downstream_ids:
        probs = {}
        for team_name, pdata in sim_result.items():
            champion = pdata.get("champion", 0)
            final = pdata.get("final", 0)
            sf = pdata.get("sf", 0)
            qf = pdata.get("qf", 0)
            r16 = pdata.get("r16", 0)
            r32 = pdata.get("r32", 0)
            for stage in ("champion", "final", "sf", "qf", "r16", "r32"):
                prob = pdata.get(stage, 0)
                if prob > 0.001:
                    probs.setdefault(stage, []).append({"name": team_name, "probability": prob})
        sorted_probs = {k: sorted(v, key=lambda x: x["probability"], reverse=True)[:3] for k, v in probs.items()}
        simulated.append({
            "match_id": mid,
            "top_teams": sorted(
                [{"name": name, **pdata} for name, pdata in sim_result.items()],
                key=lambda t: t.get("champion", 0), reverse=True
            )[:5],
        })

    target_probs = {}
    target_round = bracket_entry.get("round", "?") if bracket_entry else "?"
    for team_name, pdata in sim_result.items():
        target_probs[team_name] = {
            stage: pdata.get(stage, 0)
            for stage in ("champion", "final", "sf", "qf", "r16", "r32")
        }
    top_target = sorted(target_probs.items(), key=lambda x: x[1].get("champion", 0), reverse=True)[:4]

    return {
        "match_id": match_id,
        "round": target_round,
        "predictions": [
            {"name": name, **probs} for name, probs in top_target if probs.get("champion", 0) > 0
        ],
        "downstream": simulated,
    }


def _collect_downstream_matches(target_id: str, bracket_raw: list) -> list[str]:
    """Collect all downstream matches reachable from target_id via source_matches."""
    children_of: dict[str, list[str]] = {}
    for be in bracket_raw:
        for sm in (be.get("source_matches") or []):
            children_of.setdefault(sm, []).append(be["match_id"])

    downstream = []
    queue = [target_id]
    visited = set()
    while queue:
        mid = queue.pop(0)
        for child in children_of.get(mid, []):
            if child not in visited:
                visited.add(child)
                downstream.append(child)
                queue.append(child)
    return downstream


@wc_app.post("/api/simulate-from-match")
def api_simulate_from_match(req: dict = None):
    if not req:
        return JSONResponse({"error": "request body required"})
    match_id = req.get("match_id", "")
    iterations = int(req.get("iterations", 10000))
    iterations = max(1000, min(100000, iterations))
    if not match_id:
        return JSONResponse({"error": "match_id required"})

    try:
        result = _simulate_from_match_sync(match_id, iterations)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)})


@wc_app.get("/api/match/insight")
def api_match_insight(match_id: str = ""):
    if not match_id:
        return JSONResponse({"error": "match_id parameter required"})
    fb = cache.get("full_bracket", {})
    ev = cache.get("evaluation", {})
    bl = cache.get("blend_data")
    if not bl:
        bl_info = compute_blend_info()
        blend_weights = bl_info.get("blend_weights", {})
    else:
        blend_weights = bl.get("blend_weights", {})
    insight = compute_match_insight(match_id, fb, ev, blend_weights)
    return JSONResponse(insight)


@wc_app.post("/api/what-if")
def api_what_if(req: dict = None):
    if not req:
        return JSONResponse({"error": "request body required"})
    match_id = req.get("match_id", "")
    scenario = req.get("scenario", "")
    mode = req.get("mode", "instant")
    iterations = int(req.get("iterations", 50000))
    if not match_id or not scenario:
        return JSONResponse({"error": "match_id and scenario required"})
    fb = cache.get("full_bracket", {})
    match_data = None
    for r, ms in fb.get("rounds", {}).items():
        for m in ms:
            if m["match_id"] == match_id:
                match_data = m
                break
        if match_data:
            break
    if not match_data:
        return JSONResponse({"error": "match not found in bracket"})
    ta = match_data.get("team_a", "")
    tb = match_data.get("team_b", "")
    blend_info = compute_blend_info()
    blend_weights = blend_info.get("blend_weights", {})
    parsed = parse_scenario(scenario, ta, tb, blend_weights)
    if parsed.confidence == 0.0:
        return JSONResponse({"mode": mode, "error": "No meaningful scenario detected. Try describing a specific condition (e.g., 'injury', 'strong form', 'weak defense')."})
    if mode == "instant":
        teams_raw = load_json(DATA_DIR, "teams.json")
        elo_ratings = {n: d["elo"] for n, d in teams_raw.items()}
        ledger = json.loads((DATA_DIR / "predictions_ledger.json").read_text(encoding="utf-8"))
        played = json.loads((DATA_DIR / "played.json").read_text(encoding="utf-8"))
        played_groups_raw = (DATA_DIR / "played_groups.json").read_text(encoding="utf-8")
        played_groups = json.loads(played_groups_raw) if played_groups_raw.strip() else {}
        team_strengths = compute_team_signal_strengths(ledger, played_groups)
        sigs, elo_p = compute_ko_signal_probs(ta, tb, team_strengths, elo_ratings)
        original_signals = {}
        elo_w = blend_weights.get("elo", 0.1874)
        original_signals["elo"] = {"probability": elo_p, "weight": elo_w}
        for sk, prob in sigs.items():
            w = blend_weights.get(sk, 0)
            original_signals[sk] = {"probability": prob, "weight": w}
        result = handle_instant_scenario(scenario, ta, tb, original_signals, blend_weights, elo_prob=elo_p, team_strengths=team_strengths)
        return JSONResponse({"mode": "instant", **result})
    elif mode == "simulate":
        task_id = str(uuid.uuid4())
        with sim_lock:
            active_simulations[task_id] = {
                "status": "starting", "progress": 0, "iteration": 0,
                "total_iterations": iterations, "error": None, "result": None,
            }

        def _run_sim(task_id, scenario, match_id, ta, tb, iterations):
            try:
                with sim_lock:
                    active_simulations[task_id]["status"] = "running"
                teams_raw = load_json(DATA_DIR, "teams.json")
                groups_raw = load_groups(DATA_DIR, teams=teams_raw)
                bracket_raw = json.loads((DATA_DIR / "bracket.json").read_text(encoding="utf-8"))
                annex_c = load_annex_c(DATA_DIR)
                played_raw = json.loads((DATA_DIR / "played.json").read_text(encoding="utf-8"))
                played_groups_raw = (DATA_DIR / "played_groups.json").read_text(encoding="utf-8")
                played_groups = json.loads(played_groups_raw) if played_groups_raw.strip() else {}
                ledger = json.loads((DATA_DIR / "predictions_ledger.json").read_text(encoding="utf-8"))
                blend_info = compute_blend_info()
                blend_weights = blend_info.get("blend_weights", {})
                team_strengths = compute_team_signal_strengths(ledger, played_groups)
                elo_ratings = {n: d["elo"] for n, d in teams_raw.items()}
                sigs, elo_p = compute_ko_signal_probs(ta, tb, team_strengths, elo_ratings)
                original_signals = {}
                elo_w = blend_weights.get("elo", 0.1874)
                original_signals["elo"] = {"probability": elo_p, "weight": elo_w}
                for sk, prob in sigs.items():
                    w = blend_weights.get(sk, 0)
                    original_signals[sk] = {"probability": prob, "weight": w}
                scenario_result = handle_instant_scenario(scenario, ta, tb, original_signals, blend_weights, elo_prob=elo_p)
                xg_overrides = None
                adj_sigs = scenario_result.get("adjusted_signals", {})
                for sk, sv in adj_sigs.items():
                    if sv.get("was_adjusted") and sk == "defensive_quality":
                        xg_overrides = {}
                        for s_name, s_val in adj_sigs.items():
                            if s_val.get("was_adjusted"):
                                override_factor = s_val["probability"] / max(original_signals.get(s_name, {}).get("probability", 0.5), 0.01)
                                xg_overrides[ta] = (1.0, override_factor)
                                xg_overrides[tb] = (override_factor, 1.0)
                with sim_lock:
                    active_simulations[task_id]["status"] = "running"
                    active_simulations[task_id]["progress"] = 0.0
                    active_simulations[task_id]["iteration"] = 0

                def _on_progress(current, total):
                    with sim_lock:
                        pct = round(current / total * 100, 1)
                        active_simulations[task_id]["progress"] = pct
                        active_simulations[task_id]["iteration"] = current

                sim_result = run_full_simulation(
                    teams_raw, groups_raw, bracket_raw, annex_c,
                    played_raw, iterations=iterations,
                    played_groups=played_groups,
                    xg_overrides=xg_overrides,
                    progress_cb=_on_progress,
                )
                baseline_raw = cache.get("simulation_raw")
                if baseline_raw:
                    insight = generate_simulate_insight(baseline_raw, sim_result, scenario, ta, tb, iterations)
                else:
                    insight = "No baseline data available for comparison."
                with sim_lock:
                    active_simulations[task_id]["status"] = "complete"
                    active_simulations[task_id]["progress"] = 100.0
                    active_simulations[task_id]["iteration"] = iterations
                    active_simulations[task_id]["result"] = sim_result
                    active_simulations[task_id]["insight"] = insight
            except Exception as e:
                with sim_lock:
                    active_simulations[task_id]["status"] = "error"
                    active_simulations[task_id]["error"] = str(e)

        t = threading.Thread(target=_run_sim, args=(task_id, scenario, match_id, ta, tb, iterations), daemon=True)
        t.start()
        return JSONResponse({"mode": "simulate", "task_id": task_id, "status": "started"})
    return JSONResponse({"error": "invalid mode"})


def _run_calibration_task(task_id: str):
    """Background calibration: Brier-weighted blend optimization + temperature scaling."""
    try:
        t0 = time.time()
        with sim_lock:
            active_simulations[task_id] = {
                "status": "running", "progress": 0, "stage": "Loading data...",
                "t0": t0, "elapsed": 0, "total_iterations": 100,
            }

        def _progress(pct, stage):
            with sim_lock:
                s = active_simulations.get(task_id)
                if s:
                    s["progress"] = pct
                    s["stage"] = stage
                    s["elapsed"] = time.time() - t0

        _progress(5, "Loading teams and groups...")
        teams_raw = load_json(DATA_DIR, "teams.json")
        groups_raw = load_groups(DATA_DIR, teams=teams_raw)
        bracket_raw = json.loads((DATA_DIR / "bracket.json").read_text(encoding="utf-8"))

        _progress(15, "Loading signal caches...")
        from competitions.worldcup.src.state import load_signal_cache
        odds_cache = load_signal_cache("odds_cache.json", DATA_DIR)
        cb_cache = load_signal_cache("catboost_cache.json", DATA_DIR)
        form_cache = load_signal_cache("form_cache.json", DATA_DIR)
        lineup_cache = load_signal_cache("lineup_cache.json", DATA_DIR)
        defensive_cache = load_signal_cache("defensive_cache.json", DATA_DIR)
        manager_cache = load_signal_cache("manager_effect_cache.json", DATA_DIR)
        availability_cache = load_signal_cache("availability_cache.json", DATA_DIR)

        _progress(30, "Running calibration...")

        def _cal_progress(pct):
            _progress(30 + int(pct * 0.6), f"Calibrating... {pct:.0f}%")

        blend_params = run_calibrate_and_blend(
            teams=teams_raw,
            groups=groups_raw,
            bracket=bracket_raw,
            odds_cache=odds_cache,
            cb_cache=cb_cache,
            form_cache=form_cache,
            lineup_cache=lineup_cache,
            defensive_cache=defensive_cache,
            manager_cache=manager_cache,
            availability_cache=availability_cache,
            data_dir=str(DATA_DIR),
        )

        _progress(95, "Saving calibration params...")
        calib_params = load_calibration_params(DATA_DIR)

        _progress(100, "Complete")
        with sim_lock:
            s = active_simulations.get(task_id)
            if s:
                s["status"] = "complete"
                s["progress"] = 100
                s["elapsed"] = time.time() - t0
                s["result"] = {
                    "status": "calibrated" if blend_params else "failed",
                    "weights": (blend_params or {}).get("weights"),
                    "calibration_params": calib_params,
                    "n_signals_calibrated": len((blend_params or {}).get("weights", {})),
                }
    except Exception as e:
        with sim_lock:
            s = active_simulations.get(task_id)
            if s:
                s["status"] = "error"
                s["error"] = str(e)
                s["elapsed"] = time.time() - t0


@wc_app.post("/api/calibrate")
def api_calibrate(req: dict = None):
    task_id = str(uuid.uuid4())
    t = threading.Thread(target=_run_calibration_task, args=(task_id,), daemon=True)
    t.start()
    return JSONResponse({"task_id": task_id, "status": "started"})


@wc_app.get("/api/simulation/progress/{task_id}")
def api_simulation_progress(task_id: str):
    with sim_lock:
        sim = active_simulations.get(task_id)
    if not sim:
        return JSONResponse({"error": "task not found"})
    response = {
        "status": sim["status"],
        "progress": sim.get("progress", 0),
        "iteration": sim.get("iteration", 0),
        "total_iterations": sim.get("total_iterations", 0),
        "stage": sim.get("stage", ""),
        "elapsed": round(sim.get("elapsed", 0), 1),
    }
    if sim["status"] == "complete":
        result = sim.get("result")
        if result:
            response["result"] = result
        with sim_lock:
            del active_simulations[task_id]
    if sim["status"] == "error":
        response["error"] = sim.get("error")
        with sim_lock:
            del active_simulations[task_id]
    return JSONResponse(response)
