"""UCL 2025/26 dashboard — FastAPI server.

Separate from the WC server (port 8081). Serves real results by default
(season completed, PSG champion) with MC simulation available on demand.

Endpoints:
    GET  /              — serve ucl_index.html
    GET  /api/data      — summary stats (teams, champion, mode)
    GET  /api/standings — 36-row Swiss league table with zones
    GET  /api/bracket   — playoff ties + bracket_rounds (R16→Final)
    GET  /api/odds      — teams sorted by champion probability
    GET  /api/signals   — per-signal aggregate statistics
    GET  /api/boot      — boot step log for terminal animation
    POST /api/simulate  — run MC simulation (switches to sim mode)
    POST /api/reset     — back to real results mode
    POST /api/what-if   — instant Elo-driven scenario analysis
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import time
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

BSD_API_KEY: str = os.environ.get("BSD_API_KEY", "")
UCL_LEAGUE_ID: int = 7

# BSD team name → our fixture team name alias mapping
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
boot_log: list[dict] = []
sim_result: SimulationResult | None = None
_mode: str = "results"  # "results" or "simulation"


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def boot_step(step_name: str, action):
    t0 = time.time()
    try:
        result = action()
        elapsed = time.time() - t0
        boot_log.append({
            "step": step_name, "status": "ok",
            "elapsed": round(elapsed, 2),
            "output": f"[{ts()}] {step_name} — done in {elapsed:.1f}s",
        })
        return result
    except Exception as e:
        elapsed = time.time() - t0
        boot_log.append({
            "step": step_name, "status": "error",
            "elapsed": round(elapsed, 2),
            "output": f"[{ts()}] {step_name} — FAILED ({e})",
        })
        return None


def _parse_what_if_scenario(scenario: str, match: dict) -> dict | None:
    """Parse a natural-language scenario into Elo delta adjustments.

    Returns {team_name: elo_delta} or None if no adjustment.
    """
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
                team_key = team.lower().replace(" ", "")
                name_key = team.lower().replace(" ", "")
                text_key = text.replace(" ", "")
                if name_key in text_key:
                    # Scale delta by intensity modifiers
                    delta = base_delta
                    if "very" in text or "significantly" in text or "major" in text:
                        delta = int(delta * 2)
                    if "slightly" in text or "somewhat" in text or "a bit" in text:
                        delta = int(delta * 0.5)
                    deltas[team] = deltas.get(team, 0) + delta

    return deltas if deltas else None


def _fetch_ucl_managers(api_key: str) -> dict[str, dict]:
    """Fetch UCL manager data from BSD API and map team names to our fixture names.

    Returns {our_team_name: manager_profile_dict} for teams found in BSD.
    """
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


# ── Deterministic (real results) mode ─────────────────────────────────────


def _load_results() -> list[dict]:
    """Load league phase results from results.json."""
    path = DATA_DIR / "results.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _load_knockout_results() -> dict | None:
    """Load knockout results from knockout_results.json."""
    path = DATA_DIR / "knockout_results.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _compute_deterministic_standings(results: list[dict]) -> list[dict]:
    """Compute actual league phase standings from real results.
    
    Returns per-team dicts with pts, gd, gs, ga, wins, away_wins, away_gs,
    then sorts by UCL tiebreaker chain (pts → gd → gs → away_gs → wins → away_wins).
    """
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

    # Build list and sort by UCL tiebreaker: pts → gd → gs → away_gs → wins → away_wins
    standings_list = []
    for team, s in stats.items():
        standings_list.append({
            "team": team,
            "pts": s["pts"],
            "gd": s["gd"],
            "gs": s["gs"],
            "ga": s["ga"],
            "wins": s["wins"],
            "draws": s["draws"],
            "losses": s["losses"],
            "away_wins": s["away_wins"],
            "away_gs": s["away_gs"],
            "home_wins": s["home_wins"],
            "home_gs": s["home_gs"],
        })

    standings_list.sort(
        key=lambda x: (-x["pts"], -x["gd"], -x["gs"], -x["away_gs"], -x["wins"], -x["away_wins"])
    )

    # Assign positions and zones
    for i, entry in enumerate(standings_list, start=1):
        entry["position"] = i
        if i <= 8:
            entry["zone"] = "top_8"
        elif i <= 24:
            entry["zone"] = "playoff"
        else:
            entry["zone"] = "eliminated"

    return standings_list


def _build_deterministic_bracket(knockout: dict, standings: list[dict]) -> dict:
    """Build bracket display data from known knockout results.

    Returns {playoff: [...], bracket_rounds: {R16:[], QF:[], SF:[], FINAL:[]}}.
    Uses bracket_rules.json for match_ids and tree structure so bracket
    connectors render correctly.
    """
    bracket_rules_path = DATA_DIR / "bracket_rules.json"
    try:
        bracket_rules = json.loads(bracket_rules_path.read_text(encoding="utf-8"))
    except Exception:
        bracket_rules = {"matches": []}

    # Build source_map
    source_map: dict[str, list[str]] = {}
    for m in bracket_rules.get("matches", []):
        if m.get("source_matches"):
            source_map[m["match_id"]] = m["source_matches"]

    # Map real R16 teams to bracket_rules slots
    # Real bracket mapped to match the slot quarters so tree connectors work:
    # Q1: PSG/Chelsea + Liverpool/Galatasaray → PSG/Liverpool → PSG
    # Q2: Bayern/Atalanta + Real/ManCity → Bayern/Real → Bayern
    # Q3: Atletico/Tottenham + Barca/Newcastle → Atletico/Barca → Atletico
    # Q4: Arsenal/Leverkusen + Sporting/Bodo → Arsenal/Sporting → Arsenal
    r16_real = {
        "r16_01": ("PSG", "Chelsea", "PSG", 8, 2),
        "r16_02": ("Liverpool", "Galatasaray", "Liverpool", 4, 1),
        "r16_03": ("Bayern", "Atalanta", "Bayern", 10, 2),
        "r16_04": ("Real Madrid", "Man City", "Real Madrid", 5, 1),
        "r16_05": ("Atletico Madrid", "Tottenham", "Atletico Madrid", 7, 5),
        "r16_06": ("Barcelona", "Newcastle", "Barcelona", 8, 3),
        "r16_07": ("Arsenal", "Bayer Leverkusen", "Arsenal", 3, 1),
        "r16_08": ("Sporting", "Bodo/Glimt", "Sporting", 5, 3),
    }
    qf_real = {
        "qf_01": ("PSG", "Liverpool", "PSG", 4, 0),
        "qf_02": ("Bayern", "Real Madrid", "Bayern", 6, 4),
        "qf_03": ("Atletico Madrid", "Barcelona", "Atletico Madrid", 3, 2),
        "qf_04": ("Arsenal", "Sporting", "Arsenal", 1, 0),
    }
    sf_real = {
        "sf_01": ("PSG", "Bayern", "PSG", 6, 5),
        "sf_02": ("Atletico Madrid", "Arsenal", "Arsenal", 2, 1),
    }
    final_real = {
        "final_01": ("PSG", "Arsenal", "PSG", 1, 1),
    }

    rounds_out: dict[str, list[dict]] = {"R16": [], "QF": [], "SF": [], "FINAL": []}

    for mid, (ta, tb, winner, ha, aa) in r16_real.items():
        rounds_out["R16"].append({
            "match_id": mid, "round": "R16",
            "team_a": ta, "team_b": tb,
            "score": {"home": ha, "away": aa},
            "winner": winner, "played": True,
        })
    for mid, (ta, tb, winner, ha, aa) in qf_real.items():
        rounds_out["QF"].append({
            "match_id": mid, "round": "QF",
            "team_a": ta, "team_b": tb,
            "score": {"home": ha, "away": aa},
            "winner": winner, "played": True,
            "source_matches": source_map.get(mid, []),
        })
    for mid, (ta, tb, winner, ha, aa) in sf_real.items():
        rounds_out["SF"].append({
            "match_id": mid, "round": "SF",
            "team_a": ta, "team_b": tb,
            "score": {"home": ha, "away": aa},
            "winner": winner, "played": True,
            "source_matches": source_map.get(mid, []),
        })
    for mid, (ta, tb, winner, ha, aa) in final_real.items():
        rounds_out["FINAL"].append({
            "match_id": mid, "round": "FINAL",
            "team_a": ta, "team_b": tb,
            "score": {"home": ha, "away": aa},
            "winner": winner, "played": True,
            "source_matches": source_map.get(mid, []),
            "penalties": {"winner": "PSG", "loser": "Arsenal", "psg": 4, "arsenal": 3},
        })

    # Build playoff display from knockout data
    playoff_display: list[dict] = []
    ko_playoff = knockout.get("playoff", [])
    for tie in ko_playoff:
        playoff_display.append({
            "tie_num": tie.get("tie_num"),
            "team_a": tie.get("winner") or tie.get("team_a", ""),
            "team_b": tie.get("loser") or tie.get("team_b", ""),
            "winner": tie.get("winner"),
            "aggregate_a": tie.get("aggregate_a", 0),
            "aggregate_b": tie.get("aggregate_b", 0),
            "et_played": tie.get("et_played", False),
            "penalties_played": tie.get("penalties_played", False),
        })

    return {
        "playoff": playoff_display,
        "bracket_rounds": rounds_out,
    }


def _compute_signal_eval(results: list[dict], engine, elo_ratings: dict[str, float],
                         bsd_manager_data: dict) -> dict:
    """Compute per-signal Brier scores and accuracy against real results."""
    # Build match lookup: {(team_a, team_b): (home_score, away_score)}
    result_lookup = {}
    for m in results:
        result_lookup[(m["team_a"], m["team_b"])] = (m["home_score"], m["away_score"])

    signal_matches = []
    for m in results:
        signal_matches.append({"team_a": m["team_a"], "team_b": m["team_b"], "match_id": m["match_id"]})

    ctx = PredictionContext(
        fixtures=signal_matches,
        elo_ratings=elo_ratings,
        played_results=[],
        manager_data=bsd_manager_data,
    )

    sig_data: dict[str, dict] = {}
    try:
        blended = [engine.evaluate(m, ctx) for m in signal_matches]
        for i, bp in enumerate(blended):
            m = results[i]
            ta, tb = m["team_a"], m["team_b"]
            hs, aws = m["home_score"], m["away_score"]
            # Determine actual outcome encoded as [1,0,0] for home win, [0,1,0] for draw, [0,0,1] for away win
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
                prob_h = sd.get("home", 0.5)
                prob_d = sd.get("draw", 0.0)
                prob_a = sd.get("away", 0.5)
                # Brier score for 3-outcome
                brier = (prob_h - actual[0])**2 + (prob_d - actual[1])**2 + (prob_a - actual[2])**2
                sig_data[sig]["brier_sum"] += brier
                sig_data[sig]["n_eval"] += 1
                # Accuracy: predicted winner (or draw) matches actual
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
                "n_matches": sd["n"],
                "available": sd["available"],
                "available_pct": round(sd["available"] / sd["n"] * 100, 1) if sd["n"] else 0,
                "avg_probability": round(avg, 4),
                "weight": round(engine.weights.get(sig, 0), 4),
                "brier": round(brier_avg, 4),
                "accuracy": round(acc, 4),
            }
        return sig_stats
    except Exception:
        return {}


def deterministic_compute() -> dict:
    """Compute dashboard data from real results (no MC simulation).
    
    Loads results.json and knockout_results.json, computes standings
    and bracket display deterministically. All probabilities are 0/100
    (real outcomes). Mode = "results".
    """
    global boot_log, _mode
    boot_log = []
    data: dict = {"boot": boot_log}
    _mode = "results"

    results = boot_step("Load real results",
                        lambda: _load_results())
    if not results:
        data["error"] = "results.json not found"
        return data

    knockout = boot_step("Load knockout results",
                         lambda: _load_knockout_results())
    if not knockout:
        data["error"] = "knockout_results.json not found"
        return data

    # Load fixtures for team info
    fixtures_path = str(DATA_DIR / "fixtures.json")
    provider = boot_step("Load fixtures",
                         lambda: RepoFixtureProvider(fixtures_path=fixtures_path).load())
    if not provider:
        data["error"] = "fixtures load failed"
        return data

    team_names = [t.name for t in provider.teams]

    # Elo ratings (for signals, not simulation)
    elo_ratings = boot_step("Fetch Elo ratings",
                            lambda: fetch_team_elos(team_names))
    if not elo_ratings:
        elo_ratings = {}
        coefficients = {t.name: t.coefficient for t in provider.teams}
        max_coeff = max(coefficients.values()) if coefficients else 100
        for t in team_names:
            c = coefficients.get(t, 50)
            elo_ratings[t] = 1400.0 + (c / max_coeff) * 400.0
        boot_log.append({
            "step": "Elo fallback (coefficients)", "status": "ok",
            "elapsed": 0.0,
            "output": f"[{ts()}] Elo fallback — using UEFA coefficients for {len(elo_ratings)} teams",
        })

    # BSD manager data (for signals)
    bsd_manager_data: dict[str, dict] = {}
    if BSD_API_KEY:
        bsd_manager_data = boot_step("Fetch BSD managers",
                                     lambda: _fetch_ucl_managers(BSD_API_KEY))
    cache["bsd_manager_data"] = bsd_manager_data

    # Compute standings from real results
    standings = boot_step("Compute standings",
                          lambda: _compute_deterministic_standings(results))

    # Build bracket from real knockout results
    bracket_data = boot_step("Build bracket",
                             lambda: _build_deterministic_bracket(knockout, standings))

    # Build signal engine
    engine = boot_step("Build signal engine",
                       lambda: _build_signal_engine(elo_ratings))

    # Signal evaluation against real results
    signal_stats = boot_step("Evaluate signals",
                             lambda: _compute_signal_eval(results, engine, elo_ratings, bsd_manager_data))

    # Build odds display — deterministic (champion prob 1.0/0.0)
    odds_display = []
    champ = knockout.get("champion", "")
    for i, entry in enumerate(standings, start=1):
        is_champ = entry["team"] == champ
        odds_display.append({
            "rank": i,
            "team": entry["team"],
            "champion_prob": 1.0 if is_champ else 0.0,
            "final_prob": 1.0 if is_champ else 0.0,
            "sf_prob": 1.0 if is_champ or _was_in_semis(entry["team"], knockout) else 0.0,
            "qf_prob": 1.0 if is_champ or _was_in_qf(entry["team"], knockout) else 0.0,
            "top_8_prob": 1.0 if entry.get("position", 99) <= 8 else 0.0,
            "playoff_prob": 1.0 if entry.get("zone") == "playoff" else 0.0,
            "avg_position": float(entry.get("position", 36)),
        })

    # Top 4 by position
    top4 = [odds_display[i] for i in range(min(4, len(odds_display)))]

    # Build bracket rounds display
    enriched_bracket: dict[str, list[dict]] = {}
    for round_name, matches in bracket_data.get("bracket_rounds", {}).items():
        enriched_bracket[round_name] = matches

    data["mode"] = "results"
    data["teams"] = top4
    data["all_teams"] = odds_display
    data["n_teams"] = len(standings)
    data["n_iterations"] = 1
    data["seed"] = 0
    data["snapshot_date"] = "2025/26 Season — Real Results"
    data["champion"] = champ
    data["standings"] = standings
    data["playoff"] = bracket_data.get("playoff", [])
    data["bracket_rounds"] = enriched_bracket
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


# ── Main compute entry point ──────────────────────────────────────────────


def compute_all() -> dict:
    """Main compute entry point — defaults to real results if results.json exists."""
    results_path = DATA_DIR / "results.json"
    ko_path = DATA_DIR / "knockout_results.json"
    if results_path.exists() and ko_path.exists():
        return deterministic_compute()

    global boot_log, sim_result, _mode
    _mode = "simulation"
    boot_log = []

    data: dict = {"boot": boot_log}

    fixtures_path = str(DATA_DIR / "fixtures.json")
    provider = boot_step("Load fixtures",
                         lambda: RepoFixtureProvider(fixtures_path=fixtures_path).load())
    if not provider:
        data["error"] = "fixtures load failed"
        return data

    team_names = [t.name for t in provider.teams]

    elo_ratings = boot_step("Fetch Elo ratings",
                            lambda: fetch_team_elos(team_names))
    if not elo_ratings:
        # Fallback: derive approximate Elo from UEFA coefficients
        elo_ratings = {}
        coefficients = {t.name: t.coefficient for t in provider.teams}
        max_coeff = max(coefficients.values()) if coefficients else 100
        for t in team_names:
            c = coefficients.get(t, 50)
            elo_ratings[t] = 1400.0 + (c / max_coeff) * 400.0
        boot_log.append({
            "step": "Elo fallback (coefficients)", "status": "ok",
            "elapsed": 0.0,
            "output": f"[{ts()}] Elo fallback — using UEFA coefficients for {len(elo_ratings)} teams",
        })

    # ── BSD API: fetch manager data ──
    bsd_manager_data: dict[str, dict] = {}
    if BSD_API_KEY:
        bsd_manager_data = boot_step("Fetch BSD managers",
                                     lambda: _fetch_ucl_managers(BSD_API_KEY))
    else:
        boot_log.append({
            "step": "BSD managers", "status": "ok",
            "elapsed": 0.0,
            "output": f"[{ts()}] BSD_API_KEY not set — skipping manager data",
        })
    cache["bsd_manager_data"] = bsd_manager_data

    # ── Blend BSD manager win rates into Elo for better simulation ──
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
            boot_log.append({
                "step": "Elo blend (BSD managers)", "status": "ok",
                "elapsed": 0.0,
                "output": f"[{ts()}] Blended manager win% into Elo for {blended_count} teams",
            })

    # Use a fixed seed for reproducibility
    seed = 42
    n_iterations = 10000

    result = boot_step("Monte Carlo simulation",
                       lambda: build_simulation_result(
                           provider, elo_ratings, seed, n_iterations))
    if not result:
        data["error"] = "simulation failed"
        return data

    sim_result = result

    # Build signal engine for per-match breakdown
    engine = boot_step("Build signal engine",
                       lambda: _build_signal_engine(elo_ratings))

    # Enrich bracket matches with source_matches from bracket_rules
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

    # Build playoff ties display
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
            "tie_num": tie_num,
            "team_a": winner,
            "team_b": loser,
            "winner": winner,
            "aggregate_a": agg_a,
            "aggregate_b": agg_b,
            "et_played": et_played,
            "penalties_played": penalties_played,
            "et_a": tie.get("et_a", 0),
            "et_b": tie.get("et_b", 0),
            "penalty_a": tie.get("penalty_a", 0),
            "penalty_b": tie.get("penalty_b", 0),
        })

    # Build odds display: sort teams by champion_prob descending
    sorted_teams = sorted(
        result.teams.items(),
        key=lambda x: (-x[1].get("champion_prob", 0.0), x[0]),
    )
    odds_display: list[dict] = []
    for rank, (name, td) in enumerate(sorted_teams, start=1):
        odds_display.append({
            "rank": rank,
            "team": name,
            "champion_prob": td.get("champion_prob", 0.0),
            "final_prob": td.get("stage_final_prob", 0.0),
            "sf_prob": td.get("stage_sf_prob", 0.0),
            "qf_prob": td.get("stage_qf_prob", 0.0),
            "top_8_prob": td.get("top_8_prob", 0.0),
            "playoff_prob": td.get("playoff_prob", 0.0),
            "avg_position": td.get("avg_position", 0.0),
        })

    # Build standings display
    standings_display: list[dict] = []
    for entry in result.standings:
        zone = entry.get("zone", "eliminated")
        standings_display.append({
            "position": entry.get("position"),
            "team": entry.get("team"),
            "pts": entry.get("pts"),
            "gd": entry.get("gd"),
            "gs": entry.get("gs"),
            "zone": zone,
        })

    # Build champion leader card data (top 4)
    top4 = [odds_display[i] for i in range(min(4, len(odds_display)))]

    # Signal stats (aggregate from engine if possible)
    signal_stats: dict[str, dict] = {}
    try:
        fixture_dict = {"schedule": asdict(provider)}
        signal_matches: list[dict] = []
        for md in provider.matchdays:
            for m in md:
                signal_matches.append({
                    "team_a": m.team_a,
                    "team_b": m.team_b,
                    "match_id": m.match_id,
                })
        manager_data = cache.get("bsd_manager_data", {})
        signal_context = PredictionContext(
            fixtures=signal_matches,
            elo_ratings=elo_ratings,
            played_results=[],
            manager_data=manager_data,
        )
        blended = [engine.evaluate(m, signal_context) for m in signal_matches]
        # Collect per-signal stats
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
                    sig_data[sig]["probs"].extend(
                        [sd.get("home", 0.5), sd.get("draw", 0), sd.get("away", 0)]
                    )

        for sig, sd in sorted(sig_data.items()):
            probs = [p for p in sd["probs"] if p is not None]
            avg = sum(probs) / len(probs) if probs else 0
            signal_stats[sig] = {
                "n_matches": sd["n"],
                "available": sd["available"],
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
    data["mode"] = _mode

    return data


cache = {}


@asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    global cache
    cache = compute_all()
    yield


app = fastapi.FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/")
def index():
    html = (Path(__file__).parent / "static" / "ucl_index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/api/data")
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


@app.get("/api/boot")
def api_boot():
    return JSONResponse(cache.get("boot", []))


@app.get("/api/standings")
def api_standings():
    return JSONResponse({
        "standings": cache.get("standings", []),
        "mode": _mode,
    })


@app.get("/api/bracket")
def api_bracket():
    return JSONResponse({
        "playoff": cache.get("playoff", []),
        "bracket_rounds": cache.get("bracket_rounds", {}),
        "champion": cache.get("champion"),
        "mode": _mode,
    })


@app.get("/api/odds")
def api_odds():
    return JSONResponse({
        "odds": cache.get("odds", []),
        "mode": _mode,
    })


@app.get("/api/signals")
def api_signals():
    return JSONResponse({
        "signals": cache.get("signals", {}),
        "mode": _mode,
    })


@app.post("/api/simulate")
def api_simulate():
    """Run MC simulation and switch to simulation mode."""
    global _mode
    _run_mc_simulation()
    return JSONResponse({"status": "ok", "mode": _mode})


def _run_mc_simulation():
    """Internal: run MC simulation without played_matches."""
    global boot_log, sim_result, _mode, cache
    _mode = "simulation"
    boot_log = []

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
    n_iterations = 10000

    result = build_simulation_result(provider, elo_ratings, seed, n_iterations)
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
        playoff_display.append({
            "tie_num": tie_num, "team_a": winner, "team_b": loser,
            "winner": winner, "aggregate_a": agg_a, "aggregate_b": agg_b,
            "et_played": tie.get("et_played", False),
            "penalties_played": tie.get("penalties_played", False),
            "et_a": tie.get("et_a", 0), "et_b": tie.get("et_b", 0),
            "penalty_a": tie.get("penalty_a", 0), "penalty_b": tie.get("penalty_b", 0),
        })

    sorted_teams = sorted(
        result.teams.items(),
        key=lambda x: (-x[1].get("champion_prob", 0.0), x[0]),
    )
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
        fixture_dict = {"schedule": asdict(provider)}
        signal_matches = []
        for md in provider.matchdays:
            for m in md:
                signal_matches.append({"team_a": m.team_a, "team_b": m.team_b, "match_id": m.match_id})
        manager_data = cache.get("bsd_manager_data", {})
        signal_context = PredictionContext(
            fixtures=signal_matches, elo_ratings=elo_ratings,
            played_results=[], manager_data=manager_data,
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
                    sig_data[sig]["probs"].extend(
                        [sd.get("home", 0.5), sd.get("draw", 0), sd.get("away", 0)]
                    )
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

    cache = {
        "mode": "simulation",
        "teams": top4, "all_teams": odds_display,
        "n_teams": len(result.teams), "n_iterations": result.n_iterations,
        "seed": result.seed, "snapshot_date": result.snapshot_date,
        "champion": result.bracket_champion,
        "standings": standings_display, "playoff": playoff_display,
        "bracket_rounds": enriched_bracket, "odds": odds_display,
        "signals": signal_stats, "elo_ratings": elo_ratings,
        "boot": [],
    }


@app.post("/api/reset")
def api_reset():
    """Reset back to real results mode."""
    global cache, _mode
    cache = compute_all()
    return JSONResponse({"status": "ok", "mode": _mode})


@app.get("/api/match/insight")
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
    sigs = cache.get("signals", {})

    # Compute Elo probability from actual ratings (not avg_position proxy)
    elo_map = cache.get("elo_ratings", {})
    elo_a = elo_map.get(ta, 1500.0)
    elo_b = elo_map.get(tb, 1500.0)
    prob_a = expected_score(elo_a, elo_b)

    return JSONResponse({
        "match_id": match_id,
        "team_a": ta,
        "team_b": tb,
        "elo_prob_a": round(prob_a, 4),
        "elo_prob_b": round(1 - prob_a, 4),
        "winner": match_data.get("winner"),
        "result": match_data.get("result"),
        "signals": sigs,
    })


@app.post("/api/what-if")
def api_what_if(req: dict = None):
    if not req:
        return JSONResponse({"error": "request body required"})
    match_id = req.get("match_id", "")
    scenario = req.get("scenario", "")

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

    # Parse scenario
    adjustments = _parse_what_if_scenario(scenario, {"team_a": ta, "team_b": tb})

    if not adjustments:
        return JSONResponse({
            "match_id": match_id,
            "team_a": ta,
            "team_b": tb,
            "original_prob_a": 0.5,
            "adjusted_prob_a": 0.5,
            "delta": 0,
            "note": "Could not parse scenario. Try: 'Team X stronger/weaker'",
        })

    # Compute original probability from actual Elo ratings
    elo_map = cache.get("elo_ratings", {})
    elo_a = elo_map.get(ta, 1500.0)
    elo_b = elo_map.get(tb, 1500.0)
    rating_a = elo_a
    rating_b = elo_b

    orig_prob_a = expected_score(rating_a, rating_b)

    # Apply adjustments
    adj_a = rating_a + adjustments.get(ta, 0)
    adj_b = rating_b + adjustments.get(tb, 0)
    adj_prob_a = expected_score(adj_a, adj_b)

    delta = adj_prob_a - orig_prob_a

    return JSONResponse({
        "match_id": match_id,
        "team_a": ta,
        "team_b": tb,
        "original_prob_a": round(orig_prob_a, 4),
        "adjusted_prob_a": round(adj_prob_a, 4),
        "delta": round(delta, 4),
        "delta_pct": round(delta * 100, 1),
        "adjustments": {t: d for t, d in adjustments.items()},
        "note": None,
    })


if __name__ == "__main__":
    uvicorn.run("web.ucl_server:app", host="127.0.0.1", port=8081, reload=False)
