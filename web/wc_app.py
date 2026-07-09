import json, os, sys, time, random, copy, uuid
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import threading

import fastapi
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from dotenv import load_dotenv
import requests

import competitions.worldcup
from competitions.worldcup.src import constants, elo
from competitions.worldcup.src.knockout import run_full_simulation, resolve_knockout_slot_teams
from competitions.worldcup.src.state import load_groups, load_annex_c
from competitions.worldcup.src.evaluation import evaluate_all_matches
from competitions.worldcup.src.output import coverage_audit
from football_core.groups import precompute_matchup_lambdas, simulate_group_matches
from competitions.worldcup.src.groups import (
    compute_standings, rank_third_placed, select_advancers, resolve_r32_matchups,
)

from web.insight import compute_team_signal_strengths, compute_ko_signal_probs, compute_match_insight, compute_form_trend, compute_head_to_head, compute_match_outcome
from web.whatif_engine import parse_scenario, handle_instant_scenario, generate_simulate_insight
from web.common import ts, boot_step, load_json, load_json_list

load_dotenv()
BSD_API_KEY = os.getenv("BSD_API_KEY", "")

DATA_DIR = constants.DATA_DIR
CACHE_FILE = Path(__file__).parent / "cache.json"

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


def compute_full_bracket(groups, teams, bracket, annex_c, played, played_groups, ledger=None):
    elo_ratings = {n: d["elo"] for n, d in teams.items()}
    known_winners = {mid: data["winner"] for mid, data in played.items() if data.get("winner")}
    slot_teams = resolve_knockout_slot_teams(groups, teams, played_groups, bracket, annex_c, known_winners)
    resolved = {}

    def _entry_for(mid):
        for b in bracket:
            if b["match_id"] == mid:
                return b
        return None

    if ledger:
        played_groups_flat = played_groups or {}
        team_strengths = compute_team_signal_strengths(ledger, played_groups_flat)
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


def compute_signal_eval(teams, played, played_groups, ledger):
    elo_report = evaluate_all_matches(teams, played, played_groups, signal_name="elo")
    history = []
    for mid, signals in ledger.items():
        actual = None
        if mid in played:
            m = played[mid]
        elif mid in played_groups:
            m = played_groups[mid]
        else:
            continue
        t_a, t_b = m["team_a"], m["team_b"]
        winner = m.get("winner")
        if winner == t_a:
            actual = 1.0
        elif winner == t_b:
            actual = 0.0
        elif winner is None:
            actual = 0.5
        if actual is None:
            continue
        sigs = {}
        for sk, sv in signals.items():
            prob = sv.get("probability")
            if prob is not None and sv.get("available"):
                sigs[sk] = {"probability": prob, "available": True}
        if sigs:
            history.append({"match_id": mid, "actual": actual, "signals": sigs})
    all_report = evaluate_all_matches(teams, played, played_groups, signal_name=None, history=history)
    return {"elo": elo_report, "all_signals": all_report}


def compute_all():
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
        "ledger": json.loads((DATA_DIR / "predictions_ledger.json").read_text(encoding="utf-8")) if (DATA_DIR / "predictions_ledger.json").exists() else {},
        "versions": json.loads((DATA_DIR / "versions.json").read_text(encoding="utf-8")) if (DATA_DIR / "versions.json").exists() else {},
        "backtest": json.loads((DATA_DIR / "eval_backtest_report.json").read_text(encoding="utf-8")) if (DATA_DIR / "eval_backtest_report.json").exists() else {},
    }, boot_log)
    if not ld:
        return {"boot": boot_log, "error": "data load failed"}
    teams, groups_data = ld["teams"], ld["groups"]["groups"]
    bracket, annex_c = ld["bracket"], ld["annex_c"]
    played, played_groups = ld["played"], ld["played_groups"]
    ledger, versions, backtest = ld["ledger"], ld["versions"], ld["backtest"]

    n_played_ko = sum(1 for m in played.values() if m.get("winner"))
    n_played_grp = sum(1 for m in played_groups.values() if m.get("winner"))
    total_played = n_played_ko + n_played_grp

    sim = boot_step("Monte Carlo Simulation", lambda:
        run_full_simulation(teams, ld["groups"], bracket, annex_c, played, played_groups=played_groups)
    , boot_log)

    gs = boot_step("Group Standings", lambda:
        compute_group_standings(ld["groups"], teams, played_groups)
    , boot_log)
    standings, third = gs or ({}, [])

    bracket_display = boot_step("Bracket Resolution", lambda:
        compute_bracket_display(ld["groups"], teams, bracket, annex_c, played, played_groups)
    , boot_log)

    eval_result = boot_step("Signal Evaluation", lambda:
        compute_signal_eval(teams, played, played_groups, ledger)
    , boot_log)

    gov = boot_step("Governance", lambda: {
        "versions": versions,
        "n_matches": len(played) + len(played_groups),
        "n_signals": len(ledger),
        "status": "COLD_START" if (len(played) + len(played_groups)) < 30 else "HEALTHY",
        "backtest_summary": backtest.get("governance_recommendation", ""),
    }, boot_log)

    cov = boot_step("Coverage Audit", lambda: coverage_audit(), boot_log)

    sorted_teams = sorted(teams.items(), key=lambda t: (sim or {}).get(t[0], {}).get("champion", 0), reverse=True)
    team_list = [
        {"name": name, "elo": round(d["elo"], 1),
         "champion": round((sim or {}).get(name, {}).get("champion", 0) * 100, 1),
         "final": round((sim or {}).get(name, {}).get("final", 0) * 100, 1),
         "sf": round((sim or {}).get(name, {}).get("sf", 0) * 100, 1),
         "qf": round((sim or {}).get(name, {}).get("qf", 0) * 100, 1)}
        for name, d in sorted_teams
    ]

    standings_display = {}
    for letter in sorted(standings.keys()):
        standings_display[letter] = []
        for row in standings[letter]:
            standings_display[letter].append({
                "team": row["team"], "position": row["position"],
                "pts": row["pts"], "gd": row["gd"], "gs": row["gs"],
            })

    third_display = []
    for r in (third or []):
        third_display.append({"group": r["group"], "team": r["team"],
                              "pts": r["pts"], "gd": r["gd"], "gs": r["gs"]})

    eval_display = {}
    if eval_result:
        elo_r = eval_result["elo"]
        eval_display["elo"] = {
            "brier": elo_r.get("metrics", {}).get("brier", 0),
            "log_loss": elo_r.get("metrics", {}).get("log_loss", 0),
            "accuracy": elo_r.get("metrics", {}).get("accuracy", 0),
            "n_matches": elo_r.get("n_matches", 0),
        }
        all_sig = eval_result["all_signals"].get("signals", {})
        for sk, sr in all_sig.items():
            m = sr.get("metrics", {})
            if m.get("n", 0) > 0:
                eval_display[sk] = {
                    "brier": m["brier"], "log_loss": m["log_loss"],
                    "accuracy": m["accuracy"], "n_matches": m["n"],
                }

    gov_display = {}
    if gov:
        gov_display = {
            "data_version": versions.get("data_version", "D?"),
            "model_version": versions.get("model_version", "M?"),
            "run_version": versions.get("run_version", "R?"),
            "n_matches": len(played) + len(played_groups),
            "status": gov.get("status", "UNKNOWN"),
            "backtest": backtest.get("governance_recommendation", ""),
        }

    total_iters = 50000

    data["boot"] = boot_log
    data["teams"] = team_list
    data["n_teams"] = len(team_list)
    data["total_iterations"] = total_iters
    data["n_played"] = total_played

    data["full_bracket"] = boot_step("Full Bracket Resolution", lambda:
        compute_full_bracket(ld["groups"], teams, bracket, annex_c, played, played_groups, ledger=ledger)
    , boot_log)

    data["standings"] = standings_display
    data["third_place"] = third_display
    data["bracket"] = bracket_display
    data["evaluation"] = eval_display
    data["governance"] = gov_display
    data["backtest"] = backtest
    data["coverage"] = cov

    if sim:
        data["simulation_raw"] = {
            team: {"champion": probs.get("champion", 0), "final": probs.get("final", 0)}
            for team, probs in sim.items()
        }

    return data


def compute_or_load():
    if CACHE_FILE.exists():
        loaded = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if loaded.get("boot") and len(loaded["boot"]) > 5:
            return loaded
    result = compute_all()
    CACHE_FILE.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return result


def compute_signal_stats():
    data_dir = constants.DATA_DIR
    ledger_path = data_dir / "predictions_ledger.json"
    if not ledger_path.exists():
        return {"signals": {}, "n_total": 0}
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    signal_data: dict[str, dict] = {}
    for mid, signals in ledger.items():
        for sk, sv in signals.items():
            if sk not in signal_data:
                signal_data[sk] = {"n": 0, "probs": [], "available": 0}
            signal_data[sk]["n"] += 1
            if sv.get("available"):
                signal_data[sk]["available"] += 1
            prob = sv.get("probability")
            if prob is not None:
                signal_data[sk]["probs"].append(prob)
    result = {}
    for sk, sd in sorted(signal_data.items()):
        probs = sd["probs"]
        avg = sum(probs) / len(probs) if probs else 0
        mn = min(probs) if probs else 0
        mx = max(probs) if probs else 0
        result[sk] = {
            "n_matches": sd["n"],
            "available": sd["available"],
            "available_pct": round(sd["available"] / sd["n"] * 100, 1) if sd["n"] else 0,
            "avg_probability": round(avg, 4),
            "min_probability": round(mn, 4),
            "max_probability": round(mx, 4),
        }
    return {"signals": result, "n_total_ledger": len(ledger)}


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
    cache_file = Path(__file__).parent / "cache.json"
    if cache_file.exists():
        cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
    else:
        cache_data = {}
    ev = cache_data.get("evaluation", {})
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
    data_dir = constants.DATA_DIR
    backtest_path = data_dir / "eval_backtest_report.json"
    backtest = json.loads(backtest_path.read_text(encoding="utf-8")) if backtest_path.exists() else {}
    ledger_path = data_dir / "predictions_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
    signals_in_ledger = set()
    for mid, sigs in ledger.items():
        signals_in_ledger.update(sigs.keys())
    per_signal = backtest.get("per_signal", {})
    briers = {}
    for sk, sv in per_signal.items():
        b = sv.get("brier")
        if b is not None:
            briers[sk] = b
    for sk in signals_in_ledger:
        if sk not in briers:
            briers[sk] = 0.25
    total_inv = sum(1.0 / max(b, 0.01) for b in briers.values()) if briers else 1
    weights = {sk: round((1.0 / max(b, 0.01)) / total_inv, 4) for sk, b in briers.items()} if total_inv else {}
    cache_file = Path(__file__).parent / "cache.json"
    if cache_file.exists():
        cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
    else:
        cache_data = {}
    gov = cache_data.get("governance", {})
    n_matches = gov.get("n_matches", 0)
    return {
        "n_signals_available": len(signals_in_ledger),
        "available_signals": sorted(signals_in_ledger),
        "blend_weights": weights,
        "backtest_briers": {sk: round(b, 4) for sk, b in briers.items()},
        "calibration_status": "cold_start" if n_matches < 30 else "calibrated",
        "n_matches_for_calibration": n_matches,
        "threshold": 30,
    }


def refresh_from_api():
    global cache
    if not BSD_API_KEY:
        return {"status": "error", "message": "No BSD_API_KEY configured. Add to .env file."}
    data_dir = constants.DATA_DIR
    t0 = time.time()
    updated = {}
    errors = []
    try:
        teams = json.loads((data_dir / "teams.json").read_text(encoding="utf-8"))
        groups = json.loads((data_dir / "groups.json").read_text(encoding="utf-8"))
        bracket_raw = json.loads((data_dir / "bracket.json").read_text(encoding="utf-8"))
        aliases = json.loads((data_dir / "team_aliases.json").read_text(encoding="utf-8"))
    except Exception as e:
        return {"status": "error", "message": f"Failed to load data files: {e}"}
    try:
        from competitions.worldcup.src.fetcher import build_historic_url, process_matches, process_group_matches
        from football_core.fetcher import fetch_raw_matches
        url = build_historic_url()
        raw_matches = fetch_raw_matches(BSD_API_KEY, url, constants.DEFAULT_LEAGUE_ID)
        updated["matches_fetched"] = len(raw_matches)
        played_groups_path = data_dir / "played_groups.json"
        played_groups = json.loads(played_groups_path.read_text(encoding="utf-8")) if played_groups_path.exists() else {}
        played_group_ids = set(played_groups.keys())
        new_grp = process_group_matches(raw_matches, teams, groups, aliases, played_group_ids, set())
        for m in new_grp:
            played_groups[m["match_id"]] = m
        played_groups_path.write_text(json.dumps(played_groups, indent=2, ensure_ascii=False), encoding="utf-8")
        updated["new_group_matches"] = len(new_grp)
        annex_c = load_annex_c(DATA_DIR)
        played_path = data_dir / "played.json"
        played = json.loads(played_path.read_text(encoding="utf-8")) if played_path.exists() else {}
        known_winners = {mid: d["winner"] for mid, d in played.items() if d.get("winner")}
        slot_teams = resolve_knockout_slot_teams(
            groups, teams, played_groups, bracket_raw, annex_c, known_winners
        )
        resolved_bracket = [
            {"match_id": mid, "team_a": st["team_a"], "team_b": st["team_b"]}
            for mid, st in slot_teams.items()
            if st.get("team_a") and st.get("team_b")
        ]
        updated["bracket_resolved"] = len(resolved_bracket)
        played_ids = set(played.keys())
        new_ko = process_matches(raw_matches, teams, resolved_bracket, aliases, played_ids)
        for m in new_ko:
            played[m["match_id"]] = m
        played_path.write_text(json.dumps(played, indent=2, ensure_ascii=False), encoding="utf-8")
        updated["new_ko_matches"] = len(new_ko)
        updated["match_results"] = True
    except Exception as e:
        errors.append(f"match_fetch: {repr(e)}")
        updated["match_results"] = False
    try:
        from competitions.worldcup.src.predictors.catboost import fetch_and_cache_catboost as fetch_cb
        cb_result = fetch_cb(BSD_API_KEY, aliases, groups, bracket_raw)
        updated["catboost"] = True
    except Exception as e:
        errors.append(f"catboost: {repr(e)}")
        updated["catboost"] = False
    elapsed = time.time() - t0
    status = "ok" if not errors else ("partial" if updated.get("match_results") else "error")
    refresh_record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "elapsed": round(elapsed, 2),
        "updated": updated,
        "errors": errors if errors else None,
    }
    (Path(__file__).parent / "last_refresh.json").write_text(json.dumps(refresh_record, indent=2), encoding="utf-8")
    cache_file = Path(__file__).parent / "cache.json"
    if cache_file.exists():
        cache_file.unlink()
        updated["cache_invalidated"] = True
    return {
        "status": status,
        "elapsed": round(elapsed, 2),
        "updated": updated,
        "errors": errors if errors else None,
    }


@asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    global cache
    cache = compute_or_load()
    yield


wc_app = fastapi.FastAPI(lifespan=lifespan)


@wc_app.get("/api/data")
def api_data():
    return JSONResponse({
        "teams": cache.get("teams", []),
        "n_teams": cache.get("n_teams", 0),
        "total_iterations": cache.get("total_iterations", 0),
        "n_played": cache.get("n_played", 0),
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


def _run_refresh_task(task_id: str):
    """Background refresh with progress reporting."""
    try:
        with sim_lock:
            active_simulations[task_id] = {"status": "running", "progress": 0, "stage": "Loading data files..."}

        result = refresh_from_api()
        if result["status"] == "error":
            with sim_lock:
                active_simulations[task_id]["status"] = "error"
                active_simulations[task_id]["error"] = result.get("message", "refresh failed")
            return

        with sim_lock:
            active_simulations[task_id]["progress"] = 60
            active_simulations[task_id]["stage"] = "Recomputing predictions..."

        global cache
        cache = compute_all()

        with sim_lock:
            active_simulations[task_id]["progress"] = 100
            active_simulations[task_id]["status"] = "complete"
            active_simulations[task_id]["result"] = result
    except Exception as e:
        with sim_lock:
            active_simulations[task_id]["status"] = "error"
            active_simulations[task_id]["error"] = str(e)


@wc_app.post("/api/refresh")
def api_refresh():
    task_id = str(uuid.uuid4())
    t = threading.Thread(target=_run_refresh_task, args=(task_id,), daemon=True)
    t.start()
    return JSONResponse({"task_id": task_id, "status": "started"})


@wc_app.get("/api/refresh/progress/{task_id}")
def api_refresh_progress(task_id: str):
    with sim_lock:
        task = active_simulations.get(task_id)
    if not task:
        return JSONResponse({"error": "task not found"})
    resp = {
        "status": task["status"],
        "progress": task.get("progress", 0),
        "stage": task.get("stage", ""),
    }
    if task["status"] == "complete" and task.get("result"):
        resp["result"] = task["result"]
        with sim_lock:
            del active_simulations[task_id]
    if task["status"] == "error":
        resp["error"] = task.get("error")
        with sim_lock:
            del active_simulations[task_id]
    return JSONResponse(resp)


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
