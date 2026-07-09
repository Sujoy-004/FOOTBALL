"""UCL 2025/26 — FastAPI sub-app mounted under /ucl."""

from __future__ import annotations

import json
import os
import random
import re
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import fastapi
import requests
import uvicorn
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from competitions.ucl.main import build_simulation_result, _build_signal_engine
from competitions.ucl.result import SimulationResult
from competitions.ucl.src.elo_fetcher import fetch_team_elos, get_clubelo_snapshot_date
from competitions.ucl.src.provider import RepoFixtureProvider
from competitions.ucl.src.groups import compute_swiss_standings
from football_core.blender import compute_signal_contributions
from football_core.constants import EXPECTED_GOALS_BASE_RATE
from football_core.elo import expected_score
from football_core.signal import PredictionContext

from web.common import ts, boot_step
from web.whatif_engine import handle_instant_scenario, parse_scenario

BSD_API_KEY: str = os.environ.get("BSD_API_KEY", "")
UCL_LEAGUE_ID: int = 7

_BSD_TEAM_ALIASES: dict[str, str] = {
    "Real Madrid": "Real Madrid",
    "FC Bayern M\u00fcnchen": "Bayern",
    "Liverpool FC": "Liverpool",
    "Inter": "Inter",
    "Chelsea": "Chelsea",
    "Borussia Dortmund": "Dortmund",
    "FC Barcelona": "Barcelona",
    "Arsenal": "Arsenal",
    "Bayer 04 Leverkusen": "Leverkusen",
    "Benfica": "Benfica",
    "Atalanta": "Atalanta",
    "Villarreal": "Villarreal",
    "Juventus": "Juventus",
    "Eintracht Frankfurt": "Frankfurt",
    "Club Brugge KV": "Brugge",
    "Tottenham Hotspur": "Tottenham",
    "PSV Eindhoven": "PSV",
    "AFC Ajax": "Ajax",
    "SSC Napoli": "Napoli",
    "Sporting CP": "Sporting",
    "Olympiacos FC": "Olympiacos",
    "Olympique de Marseille": "Marseille",
    "AS Monaco": "Monaco",
    "Galatasaray": "Galatasaray",
    "Athletic Club": "Athletic",
    "Newcastle United": "Newcastle",
    "Pafos FC": "Pafos",
    "Kairat Almaty": "Kairat",
    "Paris Saint-Germain": "PSG",
    "Paris SG": "PSG",
    "Manchester City": "Man City",
    "Atl\u00e9tico Madrid": "Atletico",
    "SK Slavia Praha": "Slavia Prague",
    "Slavia Prague": "Slavia Prague",
    "Bodo/Glimt": "Bodoe Glimt",
    "FC K\u00f8benhavn": "Copenhagen",
    "FC Kobenhavn": "Copenhagen",
    "Royale Union Saint-Gilloise": "Union SG",
    "Qarabag FK": "Qarabag",
}

DATA_DIR = Path(__file__).parent.parent / "competitions" / "ucl" / "data"
UCL_DIR = Path(__file__).parent.parent / "competitions" / "ucl"

cache: dict = {}
boot_log_local: list[dict] = []
sim_result: SimulationResult | None = None
_mode: str = "results"

active_simulations: dict[str, dict] = {}
sim_lock = threading.Lock()


def _parse_what_if_scenario(scenario: str, match: dict) -> dict | None:
    ta = match.get("team_a", "")
    tb = match.get("team_b", "")
    text = scenario.lower()
    deltas: dict[str, float] = {}
    for team, direction, base_delta in [
        (ta, ["stronger", "boosted", "improved", "better", "upgraded", "advantage", "favorite"], 50),
        (ta, ["weaker", "injured", "suspended", "down", "struggling", "worse", "underdog"], -50),
        (tb, ["stronger", "boosted", "improved", "better", "upgraded", "advantage", "favorite"], 50),
        (tb, ["weaker", "injured", "suspended", "down", "struggling", "worse", "underdog"], -50),
    ]:
        for kw in direction:
            if kw in text:
                name_key = team.lower().replace(" ", "")
                text_key = text.replace(" ", "")
                if name_key in text_key:
                    delta = base_delta
                    if "very" in text or "significantly" in text or "major" in text:
                        delta = int(delta * 2)
                    if "slightly" in text or "somewhat" in text or "a bit" in text:
                        delta = int(delta * 0.5)
                    deltas[team] = deltas.get(team, 0) + delta
    return deltas if deltas else None


def _fetch_ucl_managers(api_key: str) -> dict[str, dict]:
    try:
        url = f"https://sports.bzzoiro.com/api/managers/?league={UCL_LEAGUE_ID}"
        resp = requests.get(url, headers={"Authorization": f"Token {api_key}"}, timeout=15)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        results = data.get("results", [])
        mapped: dict[str, dict] = {}
        for m in results:
            ct = m.get("current_team")
            bsd_name = ct.get("name") if isinstance(ct, dict) else (ct if isinstance(ct, str) else "")
            our_name = _BSD_TEAM_ALIASES.get(bsd_name)
            if not our_name:
                continue
            mapped[our_name] = {
                "name": m.get("name", ""),
                "team": our_name,
                "win_pct": m.get("win_pct") or 0.0,
                "avg_goals_scored": m.get("avg_goals_scored") or 0.0,
                "avg_goals_conceded": m.get("avg_goals_conceded") or 0.0,
                "avg_xg_for": m.get("avg_xg_for") or 0.0,
                "avg_xg_against": m.get("avg_xg_against") or 0.0,
                "clean_sheet_pct": m.get("clean_sheet_pct") or 0.0,
                "btts_pct": m.get("btts_pct") or 0.0,
                "over_25_pct": m.get("over_25_pct") or 0.0,
                "avg_possession": m.get("avg_possession") or 0.0,
                "preferred_formation": m.get("preferred_formation", ""),
                "formations_used": m.get("formations_used", []),
                "team_style": m.get("team_style", "balanced"),
                "pressing_intensity": m.get("pressing_intensity", ""),
                "defensive_line": m.get("defensive_line", ""),
                "profile": m.get("profile", ""),
            }
        return mapped
    except Exception:
        return {}


def _load_results() -> list[dict]:
    path = DATA_DIR / "results.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "matches" in data:
        return data["matches"]
    return data if isinstance(data, list) else []


def _load_knockout_results() -> dict | None:
    path = DATA_DIR / "knockout_results.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "matches" in data:
        return data["matches"]
    return data if isinstance(data, dict) else None


def _compute_deterministic_standings(results: list[dict]) -> list[dict]:
    from collections import defaultdict
    stats: dict[str, dict] = defaultdict(lambda: {
        "pts": 0, "gd": 0, "gs": 0, "ga": 0,
        "wins": 0, "draws": 0, "losses": 0,
        "away_wins": 0, "away_gs": 0, "away_ga": 0,
        "home_wins": 0, "home_gs": 0, "home_ga": 0,
    })
    for m in results:
        ta, tb = m["team_a"], m["team_b"]
        hs, aw = m["home_score"], m["away_score"]
        stats[ta]["gs"] += hs
        stats[ta]["ga"] += aw
        stats[ta]["gd"] += (hs - aw)
        stats[ta]["home_gs"] += hs
        stats[ta]["home_ga"] += aw
        stats[tb]["gs"] += aw
        stats[tb]["ga"] += hs
        stats[tb]["gd"] += (aw - hs)
        stats[tb]["away_gs"] += aw
        stats[tb]["away_ga"] += hs
        if hs > aw:
            stats[ta]["pts"] += 3
            stats[ta]["wins"] += 1
            stats[ta]["home_wins"] += 1
            stats[tb]["losses"] += 1
        elif hs < aw:
            stats[tb]["pts"] += 3
            stats[tb]["wins"] += 1
            stats[tb]["away_wins"] += 1
            stats[ta]["losses"] += 1
        else:
            stats[ta]["pts"] += 1
            stats[tb]["pts"] += 1
            stats[ta]["draws"] += 1
            stats[tb]["draws"] += 1
    standings_list = []
    for team, s in stats.items():
        standings_list.append({
            "team": team, "pts": s["pts"], "gd": s["gd"], "gs": s["gs"], "ga": s["ga"],
            "wins": s["wins"], "draws": s["draws"], "losses": s["losses"],
            "away_wins": s["away_wins"], "away_gs": s["away_gs"],
            "home_wins": s["home_wins"], "home_gs": s["home_gs"],
        })
    standings_list.sort(key=lambda x: (-x["pts"], -x["gd"], -x["gs"], -x["away_gs"], -x["wins"], -x["away_wins"]))
    for i, entry in enumerate(standings_list, start=1):
        entry["position"] = i
        if i <= 8:
            entry["zone"] = "top_8"
        elif i <= 24:
            entry["zone"] = "playoff"
        else:
            entry["zone"] = "eliminated"
    return standings_list


def _build_league_matchdays(results: list[dict]) -> dict[str, list[dict]]:
    from collections import defaultdict
    mds: dict[str, list[dict]] = defaultdict(list)
    for m in results:
        prefix = m.get("match_id", "").split("_")[0]
        mds[prefix].append(m)
    return dict(sorted(mds.items()))


def _build_deterministic_bracket(knockout: dict, standings: list[dict]) -> dict:
    bracket_rules_path = DATA_DIR / "bracket_rules.json"
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
        prefix = rnd.lower().replace("final", "final")
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
            entry = {
                "match_id": mid,
                "round": rnd,
                "team_a": m.get("team_a", ""),
                "team_b": m.get("team_b", ""),
                "score": {"home": m.get("score_a", 0), "away": m.get("score_b", 0)},
                "winner": m.get("winner", ""),
                "played": True,
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


def _compute_signal_eval(results: list[dict], engine, elo_ratings: dict[str, float], bsd_manager_data: dict) -> dict:
    result_lookup = {}
    for m in results:
        result_lookup[(m["team_a"], m["team_b"])] = (m["home_score"], m["away_score"])
    signal_matches = []
    for m in results:
        signal_matches.append({"team_a": m["team_a"], "team_b": m["team_b"], "match_id": m["match_id"]})
    ctx = PredictionContext(fixtures=signal_matches, elo_ratings=elo_ratings, played_results=[], manager_data=bsd_manager_data)
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


def deterministic_compute() -> dict:
    global boot_log_local, _mode
    boot_log_local = []
    data: dict = {"boot": boot_log_local}
    _mode = "results"
    results = boot_step("Load real results", lambda: _load_results(), boot_log_local)
    if not results:
        data["error"] = "results.json not found"
        return data
    data["_results"] = results
    knockout = boot_step("Load knockout results", lambda: _load_knockout_results(), boot_log_local)
    if not knockout:
        data["error"] = "knockout_results.json not found"
        return data
    fixtures_path = str(DATA_DIR / "fixtures.json")
    provider = boot_step("Load fixtures", lambda: RepoFixtureProvider(fixtures_path=fixtures_path).load(), boot_log_local)
    if not provider:
        data["error"] = "fixtures load failed"
        return data
    team_names = [t.name for t in provider.teams]
    elo_ratings = boot_step("Fetch Elo ratings", lambda: fetch_team_elos(team_names), boot_log_local)
    if not elo_ratings:
        elo_ratings = {}
        coefficients = {t.name: t.coefficient for t in provider.teams}
        max_coeff = max(coefficients.values()) if coefficients else 100
        for t in team_names:
            c = coefficients.get(t, 50)
            elo_ratings[t] = 1400.0 + (c / max_coeff) * 400.0
        boot_log_local.append({"step": "Elo fallback (coefficients)", "status": "ok", "elapsed": 0.0, "output": f"[{ts()}] Elo fallback — using UEFA coefficients for {len(elo_ratings)} teams"})
    bsd_manager_data: dict[str, dict] = {}
    if BSD_API_KEY:
        bsd_manager_data = boot_step("Fetch BSD managers", lambda: _fetch_ucl_managers(BSD_API_KEY), boot_log_local)
    cache["bsd_manager_data"] = bsd_manager_data
    standings = boot_step("Compute standings", lambda: _compute_deterministic_standings(results), boot_log_local)
    if not standings:
        data["error"] = "standings computation failed"
        return data
    bracket_data = boot_step("Build bracket", lambda: _build_deterministic_bracket(knockout, standings), boot_log_local)
    engine = boot_step("Build signal engine", lambda: _build_signal_engine(elo_ratings), boot_log_local)
    data["_signal_engine"] = engine
    signal_stats = boot_step("Evaluate signals", lambda: _compute_signal_eval(results, engine, elo_ratings, bsd_manager_data), boot_log_local)
    odds_display = []
    champ = knockout.get("champion", "")
    for i, entry in enumerate(standings, start=1):
        is_champ = entry["team"] == champ
        odds_display.append({
            "rank": i, "team": entry["team"],
            "champion_prob": 1.0 if is_champ else 0.0,
            "final_prob": 1.0 if is_champ else 0.0,
            "sf_prob": 1.0 if is_champ or _was_in_semis(entry["team"], knockout) else 0.0,
            "qf_prob": 1.0 if is_champ or _was_in_qf(entry["team"], knockout) else 0.0,
            "top_8_prob": 1.0 if entry.get("position", 99) <= 8 else 0.0,
            "playoff_prob": 1.0 if entry.get("zone") == "playoff" else 0.0,
            "avg_position": float(entry.get("position", 36)),
        })
    odds_display.sort(key=lambda x: (0 if x["team"] == champ else 1, x["rank"]))
    top4 = [odds_display[i] for i in range(min(4, len(odds_display)))]
    enriched_bracket: dict[str, list[dict]] = {}
    for round_name, matches in bracket_data.get("bracket_rounds", {}).items():
        enriched_bracket[round_name] = matches
    data["mode"] = "results"
    data["teams"] = top4
    data["all_teams"] = odds_display
    data["n_teams"] = len(standings)
    n_total_matches = len(results)
    n_matchdays = len({m.get("match_id", "").split("_")[0] for m in results if "_" in m.get("match_id", "")}) or 1
    data["n_iterations"] = n_matchdays
    data["n_total_matches"] = n_total_matches
    data["seed"] = 0
    data["snapshot_date"] = "2025/26 Season — Real Results"
    data["champion"] = champ
    data["standings"] = standings
    data["playoff"] = bracket_data.get("playoff", [])
    data["bracket_rounds"] = enriched_bracket
    data["league_matchdays"] = _build_league_matchdays(results)
    data["odds"] = odds_display
    data["signals"] = signal_stats
    data["elo_ratings"] = elo_ratings
    return data


def _was_in_semis(team: str, knockout: dict) -> bool:
    for m in knockout.get("rounds", {}).get("SF", []):
        if team in (m.get("team_a"), m.get("team_b")):
            return True
    return False


def _was_in_qf(team: str, knockout: dict) -> bool:
    for m in knockout.get("rounds", {}).get("QF", []):
        if team in (m.get("team_a"), m.get("team_b")):
            return True
    return False


def compute_all() -> dict:
    results_path = DATA_DIR / "results.json"
    ko_path = DATA_DIR / "knockout_results.json"
    if results_path.exists() and ko_path.exists():
        return deterministic_compute()
    global boot_log_local, sim_result, _mode
    _mode = "simulation"
    boot_log_local = []
    data: dict = {"boot": boot_log_local}
    fixtures_path = str(DATA_DIR / "fixtures.json")
    provider = boot_step("Load fixtures", lambda: RepoFixtureProvider(fixtures_path=fixtures_path).load(), boot_log_local)
    if not provider:
        data["error"] = "fixtures load failed"
        return data
    team_names = [t.name for t in provider.teams]
    elo_ratings = boot_step("Fetch Elo ratings", lambda: fetch_team_elos(team_names), boot_log_local)
    if not elo_ratings:
        elo_ratings = {}
        coefficients = {t.name: t.coefficient for t in provider.teams}
        max_coeff = max(coefficients.values()) if coefficients else 100
        for t in team_names:
            c = coefficients.get(t, 50)
            elo_ratings[t] = 1400.0 + (c / max_coeff) * 400.0
        boot_log_local.append({"step": "Elo fallback (coefficients)", "status": "ok", "elapsed": 0.0, "output": f"[{ts()}] Elo fallback — using UEFA coefficients for {len(elo_ratings)} teams"})
    bsd_manager_data: dict[str, dict] = {}
    if BSD_API_KEY:
        bsd_manager_data = boot_step("Fetch BSD managers", lambda: _fetch_ucl_managers(BSD_API_KEY), boot_log_local)
    else:
        boot_log_local.append({"step": "BSD managers", "status": "ok", "elapsed": 0.0, "output": f"[{ts()}] BSD_API_KEY not set — skipping manager data"})
    cache["bsd_manager_data"] = bsd_manager_data
    if bsd_manager_data and elo_ratings:
        blended_count = 0
        for t in team_names:
            base = elo_ratings.get(t, 1400.0)
            mgr = bsd_manager_data.get(t)
            if mgr:
                win_pct = mgr.get("win_pct", 0.0) / 100.0
                if win_pct > 0:
                    mgr_elo = 1400.0 + (win_pct - 0.5) * 400.0
                    elo_ratings[t] = round(base * 0.7 + mgr_elo * 0.3, 1)
                    blended_count += 1
        if blended_count > 0:
            boot_log_local.append({"step": "Elo blend (BSD managers)", "status": "ok", "elapsed": 0.0, "output": f"[{ts()}] Blended manager win% into Elo for {blended_count} teams"})
    seed = 42
    n_iterations = 10000
    result = boot_step("Monte Carlo simulation", lambda: build_simulation_result(provider, elo_ratings, seed, n_iterations), boot_log_local)
    if not result:
        data["error"] = "simulation failed"
        return data
    sim_result = result
    engine = boot_step("Build signal engine", lambda: _build_signal_engine(elo_ratings), boot_log_local)
    data["_signal_engine"] = engine
    bracket_rules_path = DATA_DIR / "bracket_rules.json"
    bracket_rules = {}
    try:
        bracket_rules = json.loads(bracket_rules_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    source_map: dict[str, list[str]] = {}
    for m in bracket_rules.get("matches", []):
        if m.get("source_matches"):
            source_map[m["match_id"]] = m["source_matches"]
    enriched_bracket: dict[str, list[dict]] = {}
    for round_name, matches in result.bracket_rounds.items():
        enriched_bracket[round_name] = []
        for m in matches:
            entry = dict(m)
            if m["match_id"] in source_map:
                entry["source_matches"] = source_map[m["match_id"]]
            enriched_bracket[round_name].append(entry)
    playoff_display: list[dict] = []
    for tie_num in sorted(result.playoff_ties):
        tie = result.playoff_ties[tie_num]
        winner = result.playoff_winners.get(tie_num, "?")
        loser = tie.get("loser", "?")
        agg_a = tie.get("aggregate_a", 0)
        agg_b = tie.get("aggregate_b", 0)
        et_played = tie.get("et_played", False)
        penalties_played = tie.get("penalties_played", False)
        playoff_display.append({
            "tie_num": tie_num, "team_a": winner, "team_b": loser,
            "winner": winner, "aggregate_a": agg_a, "aggregate_b": agg_b,
            "et_played": et_played, "penalties_played": penalties_played,
            "et_a": tie.get("et_a", 0), "et_b": tie.get("et_b", 0),
            "penalty_a": tie.get("penalty_a", 0), "penalty_b": tie.get("penalty_b", 0),
        })
    sorted_teams = sorted(result.teams.items(), key=lambda x: (-x[1].get("champion_prob", 0.0), x[0]))
    odds_display: list[dict] = []
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
    standings_display: list[dict] = []
    for entry in result.standings:
        zone = entry.get("zone", "eliminated")
        standings_display.append({
            "position": entry.get("position"), "team": entry.get("team"),
            "pts": entry.get("pts"), "gd": entry.get("gd"),
            "gs": entry.get("gs"), "zone": zone,
        })
    top4 = [odds_display[i] for i in range(min(4, len(odds_display)))]
    signal_stats: dict[str, dict] = {}
    try:
        signal_matches: list[dict] = []
        for md in provider.matchdays:
            for m in md:
                signal_matches.append({"team_a": m.team_a, "team_b": m.team_b, "match_id": m.match_id})
        manager_data = cache.get("bsd_manager_data", {})
        signal_context = PredictionContext(fixtures=signal_matches, elo_ratings=elo_ratings, played_results=[], manager_data=manager_data)
        blended = [engine.evaluate(m, signal_context) for m in signal_matches]
        sig_data: dict[str, dict] = {}
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
    data["teams"] = top4
    data["all_teams"] = odds_display
    data["n_teams"] = len(result.teams)
    data["n_iterations"] = result.n_iterations
    data["seed"] = result.seed
    data["snapshot_date"] = result.snapshot_date
    data["champion"] = result.bracket_champion
    data["standings"] = standings_display
    data["playoff"] = playoff_display
    data["bracket_rounds"] = enriched_bracket
    data["odds"] = odds_display
    data["signals"] = signal_stats
    data["elo_ratings"] = elo_ratings
    data["league_matchdays"] = {}
    data["mode"] = _mode
    return data


@asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    global cache
    cache = compute_all()
    yield


ucl_app = fastapi.FastAPI(lifespan=lifespan)


@ucl_app.get("/api/data")
def api_data():
    return JSONResponse({
        "teams": cache.get("teams", []),
        "all_teams": cache.get("all_teams", []),
        "n_teams": cache.get("n_teams", 0),
        "n_iterations": cache.get("n_iterations", 0),
        "snapshot_date": cache.get("snapshot_date", ""),
        "champion": cache.get("champion"),
        "mode": _mode,
    })


@ucl_app.get("/api/boot")
def api_boot():
    return JSONResponse(cache.get("boot", []))


@ucl_app.get("/api/standings")
def api_standings():
    return JSONResponse({"standings": cache.get("standings", []), "mode": _mode})


@ucl_app.get("/api/bracket")
def api_bracket():
    return JSONResponse({
        "playoff": cache.get("playoff", []),
        "bracket_rounds": cache.get("bracket_rounds", {}),
        "league_matchdays": cache.get("league_matchdays", {}),
        "champion": cache.get("champion"),
        "mode": _mode,
    })


@ucl_app.get("/api/odds")
def api_odds():
    return JSONResponse({"odds": cache.get("odds", []), "mode": _mode})


@ucl_app.get("/api/signals")
def api_signals():
    return JSONResponse({"signals": cache.get("signals", {}), "mode": _mode})


@ucl_app.post("/api/simulate")
def api_simulate(req: dict = None):
    global _mode
    _mode = "simulation"
    task_id = str(uuid.uuid4())
    n_iterations = max(10, min(1000000, int((req or {}).get("n_iterations", 10000))))
    with sim_lock:
        active_simulations[task_id] = {
            "status": "starting", "progress": 0, "iteration": 0,
            "total_iterations": n_iterations, "error": None, "result": None,
        }

    def _task(tid):
        try:
            def on_progress(pct, iteration):
                with sim_lock:
                    s = active_simulations.get(tid)
                    if s:
                        s["status"] = "running"
                        s["progress"] = pct
                        if iteration:
                            s["iteration"] = iteration
            _run_mc_simulation(progress_cb=on_progress, n_iterations=n_iterations)
            with sim_lock:
                s = active_simulations.get(tid)
                if s:
                    s["status"] = "complete"
                    s["progress"] = 100.0
                    s["iteration"] = n_iterations
        except Exception as e:
            with sim_lock:
                s = active_simulations.get(tid)
                if s:
                    s["status"] = "error"
                    s["error"] = str(e)

    t = threading.Thread(target=_task, args=(task_id,), daemon=True)
    t.start()
    return JSONResponse({"status": "ok", "task_id": task_id, "mode": _mode})



def _run_mc_simulation(progress_cb=None, n_iterations=10000):
    global boot_log_local, sim_result, _mode, cache
    _mode = "simulation"
    boot_log_local = []
    if progress_cb: progress_cb(0, 0)
    fixtures_path = str(DATA_DIR / "fixtures.json")
    provider = RepoFixtureProvider(fixtures_path=fixtures_path).load()
    if progress_cb: progress_cb(5, 0)
    team_names = [t.name for t in provider.teams]
    elo_ratings = fetch_team_elos(team_names)
    if not elo_ratings:
        elo_ratings = {}
        coefficients = {t.name: t.coefficient for t in provider.teams}
        max_coeff = max(coefficients.values()) if coefficients else 100
        for t in team_names:
            c = coefficients.get(t, 50)
            elo_ratings[t] = 1400.0 + (c / max_coeff) * 400.0
    if progress_cb: progress_cb(10, 0)
    bsd_manager_data = cache.get("bsd_manager_data", {})
    if not bsd_manager_data and BSD_API_KEY:
        bsd_manager_data = _fetch_ucl_managers(BSD_API_KEY)
    if bsd_manager_data and elo_ratings:
        for t in team_names:
            base = elo_ratings.get(t, 1400.0)
            mgr = bsd_manager_data.get(t)
            if mgr:
                win_pct = mgr.get("win_pct", 0.0) / 100.0
                if win_pct > 0:
                    mgr_elo = 1400.0 + (win_pct - 0.5) * 400.0
                    elo_ratings[t] = round(base * 0.7 + mgr_elo * 0.3, 1)
    seed = 42
    if progress_cb:
        def _mc_progress(current, total):
            pct = 10 + (current / total) * 75
            progress_cb(pct, current)
    else:
        _mc_progress = None
    result = build_simulation_result(provider, elo_ratings, seed, n_iterations, progress_cb=_mc_progress)
    if progress_cb: progress_cb(85, n_iterations)
    sim_result = result
    engine = _build_signal_engine(elo_ratings)
    bracket_rules_path = DATA_DIR / "bracket_rules.json"
    bracket_rules = {}
    try:
        bracket_rules = json.loads(bracket_rules_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    source_map = {}
    for m in bracket_rules.get("matches", []):
        if m.get("source_matches"):
            source_map[m["match_id"]] = m["source_matches"]
    enriched_bracket = {}
    for round_name, matches in result.bracket_rounds.items():
        enriched_bracket[round_name] = []
        for m in matches:
            entry = dict(m)
            if m["match_id"] in source_map:
                entry["source_matches"] = source_map[m["match_id"]]
            enriched_bracket[round_name].append(entry)
    playoff_display = []
    for tie_num in sorted(result.playoff_ties):
        tie = result.playoff_ties[tie_num]
        winner = result.playoff_winners.get(tie_num, "?")
        loser = tie.get("loser", "?")
        agg_a = tie.get("aggregate_a", 0)
        agg_b = tie.get("aggregate_b", 0)
        playoff_display.append({"tie_num": tie_num, "team_a": winner, "team_b": loser, "winner": winner, "aggregate_a": agg_a, "aggregate_b": agg_b, "et_played": tie.get("et_played", False), "penalties_played": tie.get("penalties_played", False), "et_a": tie.get("et_a", 0), "et_b": tie.get("et_b", 0), "penalty_a": tie.get("penalty_a", 0), "penalty_b": tie.get("penalty_b", 0)})
    sorted_teams = sorted(result.teams.items(), key=lambda x: (-x[1].get("champion_prob", 0.0), x[0]))
    odds_display = []
    for rank, (name, td) in enumerate(sorted_teams, start=1):
        odds_display.append({"rank": rank, "team": name, "champion_prob": td.get("champion_prob", 0.0), "final_prob": td.get("stage_final_prob", 0.0), "sf_prob": td.get("stage_sf_prob", 0.0), "qf_prob": td.get("stage_qf_prob", 0.0), "top_8_prob": td.get("top_8_prob", 0.0), "playoff_prob": td.get("playoff_prob", 0.0), "avg_position": td.get("avg_position", 0.0)})
    standings_display = []
    for entry in result.standings:
        zone = entry.get("zone", "eliminated")
        standings_display.append({"position": entry.get("position"), "team": entry.get("team"), "pts": entry.get("pts"), "gd": entry.get("gd"), "gs": entry.get("gs"), "zone": zone})
    top4 = [odds_display[i] for i in range(min(4, len(odds_display)))]
    signal_stats = {}
    try:
        signal_matches = []
        for md in provider.matchdays:
            for m in md:
                signal_matches.append({"team_a": m.team_a, "team_b": m.team_b, "match_id": m.match_id})
        manager_data = cache.get("bsd_manager_data", {})
        signal_context = PredictionContext(fixtures=signal_matches, elo_ratings=elo_ratings, played_results=[], manager_data=manager_data)
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
            signal_stats[sig] = {"n_matches": sd["n"], "available": sd["available"], "available_pct": round(sd["available"] / sd["n"] * 100, 1) if sd["n"] else 0, "avg_probability": round(avg, 4), "weight": round(engine.weights.get(sig, 0), 4)}
    except Exception:
        signal_stats = {}
    if progress_cb: progress_cb(95, n_iterations)
    cache = {
        "mode": "simulation", "teams": top4, "all_teams": odds_display,
        "n_teams": len(result.teams), "n_iterations": result.n_iterations,
        "seed": result.seed, "snapshot_date": result.snapshot_date,
        "champion": result.bracket_champion, "standings": standings_display,
        "playoff": playoff_display, "bracket_rounds": enriched_bracket,
        "odds": odds_display, "signals": signal_stats, "elo_ratings": elo_ratings,
        "boot": [],
    }
    if progress_cb: progress_cb(100, n_iterations)


@ucl_app.post("/api/reset")
def api_reset():
    global cache, _mode
    try:
        cache = compute_all()
        return JSONResponse({"status": "ok", "mode": _mode})
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)})


@ucl_app.get("/api/simulation/progress/{task_id}")
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
    }
    if sim["status"] == "complete" and sim.get("result"):
        response["result"] = sim["result"]
        if sim.get("insight"):
            response["insight"] = sim["insight"]
        with sim_lock:
            del active_simulations[task_id]
    if sim["status"] == "error":
        response["error"] = sim.get("error")
        with sim_lock:
            del active_simulations[task_id]
    return JSONResponse(response)


# ── Match insight helpers ──


def _ucl_form_trend(team: str, results: list[dict]) -> list[dict]:
    """Return last 5 results for a team from results list."""
    entries: list[dict] = []
    for m in results:
        ta, tb = m["team_a"], m["team_b"]
        hs, aws = m["home_score"], m["away_score"]
        if ta == team:
            winner = ta if hs > aws else (tb if aws > hs else None)
            r = "W" if winner == ta else ("L" if winner == tb else "D")
            entries.append({"result": r, "gf": hs, "ga": aws, "opponent": tb, "match_id": m["match_id"]})
        elif tb == team:
            winner = ta if hs > aws else (tb if aws > hs else None)
            r = "W" if winner == tb else ("L" if winner == ta else "D")
            entries.append({"result": r, "gf": aws, "ga": hs, "opponent": ta, "match_id": m["match_id"]})
    return entries[-5:]


def _ucl_head_to_head(ta: str, tb: str, results: list[dict]) -> dict:
    """Return H2H stats between two teams from results list."""
    a_wins = b_wins = draws = 0
    matches: list[dict] = []
    for m in results:
        mt_a, mt_b = m["team_a"], m["team_b"]
        if (mt_a == ta and mt_b == tb) or (mt_a == tb and mt_b == ta):
            swapped = mt_a == tb
            hs, aws = m["home_score"], m["away_score"]
            a_score, b_score = (aws, hs) if swapped else (hs, aws)
            if a_score > b_score:
                a_wins += 1
            elif b_score > a_score:
                b_wins += 1
            else:
                draws += 1
            matches.append({"match_id": m["match_id"], "team_a": ta, "score": f"{a_score}-{b_score}", "team_b": tb})
    return {"matches": matches, "a_wins": a_wins, "b_wins": b_wins, "draws": draws, "total": a_wins + b_wins + draws}


def _ucl_outcome_dist(blended_prob: float, elo_a: float, elo_b: float) -> dict:
    """Estimate outcome distribution from blended probability."""
    elo_diff = abs(elo_a - elo_b)
    draw_est = 0.26 if elo_diff < 50 else (0.20 if elo_diff < 150 else (0.14 if elo_diff < 300 else 0.09))
    a_win = round(blended_prob * (1 - draw_est), 4)
    draw = round(draw_est, 4)
    b_win = round((1 - blended_prob) * (1 - draw_est), 4)
    total = a_win + draw + b_win
    if abs(total - 1.0) > 0.001:
        a_win = round(a_win / total, 4)
        draw = round(draw / total, 4)
        b_win = round(b_win / total, 4)
    return {"a_win": a_win, "draw": draw, "b_win": b_win}


def _ucl_insight_text(ta: str, tb: str, signals: dict, form_trends: dict, h2h: dict, outcome: dict, eval_data: dict) -> str:
    lines: list[str] = []
    if signals:
        winner_sig = max(signals.items(), key=lambda x: x[1].get("weight", 0) * x[1].get("probability", 0.5))[0]
        sp = signals[winner_sig]
        label = winner_sig.replace("_", " ").title()
        lines.append(f"{ta} is led by {label} (P={sp.get('probability', 0.5)*100:.0f}%).")
    for team in (ta, tb):
        ft = form_trends.get(team, [])
        if ft:
            streak = "".join(r["result"] for r in ft)
            lines.append(f"{team} form: {streak} in last {len(ft)}.")
    if h2h and h2h["total"] > 0:
        lines.append(f"H2H: {ta} {h2h['a_wins']}-{h2h['draws']}-{h2h['b_wins']} {tb} ({h2h['total']} meetings).")
    if outcome:
        lines.append(f"Predicted: {ta} {outcome['a_win']*100:.0f}% / Draw {outcome['draw']*100:.0f}% / {tb} {outcome['b_win']*100:.0f}%.")
    if eval_data:
        valid = {k: v for k, v in eval_data.items() if v.get("n_matches", 0) > 5}
        if valid:
            best = max(valid.items(), key=lambda x: x[1].get("accuracy", 0))
            lines.append(f"Most reliable: {best[0].replace('_',' ').title()} ({best[1]['accuracy']*100:.0f}% accuracy).")
            worst = max(valid.items(), key=lambda x: x[1].get("brier", 0))
            if worst[1].get("brier", 0) >= 0.25:
                lines.append(f"Warning: {worst[0].replace('_',' ').title()} signal unreliable (Brier {worst[1]['brier']:.2f}).")
    return " >> ".join(lines) if lines else f"{ta} vs {tb}: no insight data available."


@ucl_app.get("/api/match/insight")
def api_match_insight(match_id: str = ""):
    if not match_id:
        return JSONResponse({"error": "match_id parameter required"})
    br = cache.get("bracket_rounds", {})
    match_data = None
    for r, matches in br.items():
        for m in matches:
            if m["match_id"] == match_id:
                match_data = m
                break
        if match_data:
            break
    if not match_data:
        return JSONResponse({"error": "match not found"})
    ta = match_data.get("team_a", "")
    tb = match_data.get("team_b", "")
    if not ta or not tb:
        return JSONResponse({"error": "match teams not set"})

    elo_map = cache.get("elo_ratings", {})
    elo_a = elo_map.get(ta, 1500.0)
    elo_b = elo_map.get(tb, 1500.0)
    elo_prob = expected_score(elo_a, elo_b)

    engine = cache.get("_signal_engine")
    signals_with_weights: dict = {}
    blended_prob = 0.5

    if engine:
        try:
            ctx = PredictionContext(
                fixtures=[{"team_a": ta, "team_b": tb, "match_id": match_id}],
                elo_ratings=elo_map,
                played_results=[],
                manager_data=cache.get("bsd_manager_data", {}),
            )
            bp = engine.evaluate({"team_a": ta, "team_b": tb, "match_id": match_id}, ctx)
            blended_prob = bp.home_prob
            for sig, sd in bp.signal_breakdown.items():
                prob = sd.get("home", 0.5)
                weight = sd.get("weight", 0)
                signals_with_weights[sig] = {
                    "probability": round(prob, 4),
                    "weight": round(weight, 4),
                    "label": sig.replace("_", " ").title(),
                }
        except Exception:
            pass

    results = cache.get("_results", [])
    form_trends: dict = {}
    h2h: dict = {"a_wins": 0, "b_wins": 0, "draws": 0, "total": 0}
    if results:
        form_trends = {ta: _ucl_form_trend(ta, results), tb: _ucl_form_trend(tb, results)}
        h2h = _ucl_head_to_head(ta, tb, results)

    outcome = _ucl_outcome_dist(blended_prob, elo_a, elo_b)
    eval_data = cache.get("signals", {})
    insight = _ucl_insight_text(ta, tb, signals_with_weights, form_trends, h2h, outcome, eval_data)

    return JSONResponse({
        "match_id": match_id,
        "round": match_data.get("round"),
        "teams": {"a": ta, "b": tb},
        "played": bool(match_data.get("winner")),
        "score": match_data.get("score"),
        "winner": match_data.get("winner"),
        "signals": signals_with_weights,
        "blended_prob": round(blended_prob, 4),
        "elo_prob": round(elo_prob, 4),
        "form_trends": form_trends,
        "head_to_head": h2h,
        "outcome_distribution": outcome,
        "insight": insight,
    })


@ucl_app.post("/api/what-if")
def api_what_if(req: dict = None):
    """What-if with instant AND simulate modes (mirrors WC pattern)."""
    if not req:
        return JSONResponse({"error": "request body required"})
    match_id = req.get("match_id", "")
    scenario = req.get("scenario", "")
    mode = req.get("mode", "instant")

    if not match_id or not scenario:
        return JSONResponse({"error": "match_id and scenario required"})

    br = cache.get("bracket_rounds", {})
    match_data = None
    for r, matches in br.items():
        for m in matches:
            if m["match_id"] == match_id:
                match_data = m
                break
        if match_data:
            break

    if not match_data:
        return JSONResponse({"error": "match not found"})

    ta = match_data.get("team_a", "") or "?"
    tb = match_data.get("team_b", "") or "?"

    # Use the whatif_engine for rich response — same as WC
    elo_map = cache.get("elo_ratings", {})
    elo_a = elo_map.get(ta, 1500.0)
    elo_b = elo_map.get(tb, 1500.0)
    elo_p = expected_score(elo_a, elo_b)
    elo_p = round(max(0.01, min(0.99, elo_p)), 4)

    # Build original signals from cache data
    sigs = cache.get("signals", {})
    original_signals = {}
    for sk, sv in sigs.items():
        w = sv.get("weight", 0)
        p = sv.get("avg_probability", 0.5)
        original_signals[sk] = {"probability": p, "weight": w}
    if "elo" not in original_signals:
        original_signals["elo"] = {"probability": elo_p, "weight": 0.1874}

    parsed = parse_scenario(scenario, ta, tb, {})
    if parsed.confidence == 0.0:
        return JSONResponse({"mode": mode, "error": "No meaningful scenario detected. Try describing a specific condition (e.g., 'injury', 'strong form', 'weak defense')."})
    if mode == "instant":
        result = handle_instant_scenario(scenario, ta, tb, original_signals, {}, elo_prob=elo_p)
        return JSONResponse({"mode": "instant", **result})

    elif mode == "simulate":
        task_id = str(uuid.uuid4())
        with sim_lock:
            active_simulations[task_id] = {
                "status": "starting", "progress": 0, "iteration": 0,
                "total_iterations": 0, "error": None, "result": None,
            }

        def _run_sim(task_id, scenario, match_id, ta, tb):
            try:
                with sim_lock:
                    active_simulations[task_id]["status"] = "running"
                fixtures_path = str(DATA_DIR / "fixtures.json")
                provider = RepoFixtureProvider(fixtures_path=fixtures_path).load()
                team_names = [t.name for t in provider.teams]
                elo_ratings = fetch_team_elos(team_names)
                if not elo_ratings:
                    elo_ratings = {}
                    coefficients = {t.name: t.coefficient for t in provider.teams}
                    max_coeff = max(coefficients.values()) if coefficients else 100
                    for t in team_names:
                        c = coefficients.get(t, 50)
                        elo_ratings[t] = 1400.0 + (c / max_coeff) * 400.0

                n_iterations = 10000
                with sim_lock:
                    active_simulations[task_id]["total_iterations"] = n_iterations

                def _on_progress(current, total):
                    with sim_lock:
                        pct = round(current / total * 100, 1)
                        active_simulations[task_id]["progress"] = pct
                        active_simulations[task_id]["iteration"] = current

                baseline_elos = dict(elo_ratings)
                result = build_simulation_result(
                    provider, baseline_elos, seed=42, n_iterations=n_iterations,
                    progress_cb=_on_progress,
                )

                baseline_champ_probs = {
                    t: td.get("champion_prob", 0)
                    for t, td in result.teams.items()
                }

                adjustments = handle_instant_scenario(
                    scenario, ta, tb, original_signals, {}, elo_prob=elo_p
                ).get("adjusted_signals", {})

                adj_factor = 1.0
                for sk, sv in adjustments.items():
                    if sv.get("was_adjusted"):
                        orig = original_signals.get(sk, {}).get("probability", 0.5)
                        if orig > 0:
                            adj_factor *= sv["probability"] / orig

                adjusted_elos = dict(baseline_elos)
                if ta in adjusted_elos:
                    adjusted_elos[ta] = adjusted_elos[ta] * (1.0 + 0.1 * (adj_factor - 1.0))
                if tb in adjusted_elos:
                    adjusted_elos[tb] = adjusted_elos[tb] * (1.0 - 0.1 * (adj_factor - 1.0))

                adj_result = build_simulation_result(
                    provider, adjusted_elos, seed=42, n_iterations=n_iterations,
                    progress_cb=_on_progress,
                )

                insight_parts = [f"Scenario: {scenario}"]
                for t in [ta, tb]:
                    base = baseline_champ_probs.get(t, 0)
                    adj = adj_result.teams.get(t, {}).get("champion_prob", 0)
                    delta_str = f"+{adj-base:.1%}" if adj >= base else f"{adj-base:.1%}"
                    insight_parts.append(f"{t}: {base:.1%} → {adj:.1%} ({delta_str})")

                with sim_lock:
                    active_simulations[task_id]["status"] = "complete"
                    active_simulations[task_id]["progress"] = 100.0
                    active_simulations[task_id]["iteration"] = n_iterations
                    active_simulations[task_id]["result"] = {
                        "baseline": {t: baseline_champ_probs.get(t, 0) for t in [ta, tb]},
                        "adjusted": {t: adj_result.teams.get(t, {}).get("champion_prob", 0) for t in [ta, tb]},
                    }
                    active_simulations[task_id]["insight"] = "\n>> ".join(insight_parts)
            except Exception as e:
                with sim_lock:
                    active_simulations[task_id]["status"] = "error"
                    active_simulations[task_id]["error"] = str(e)

        t = threading.Thread(target=_run_sim, args=(task_id, scenario, match_id, ta, tb), daemon=True)
        t.start()
        return JSONResponse({"mode": "simulate", "task_id": task_id, "status": "started"})

    return JSONResponse({"error": f"unknown mode: {mode}"})
