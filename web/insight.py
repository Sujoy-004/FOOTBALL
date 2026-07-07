import json, math
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "competitions" / "worldcup" / "data"


def load_ledger():
    p = DATA_DIR / "predictions_ledger.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def load_played():
    p = DATA_DIR / "played.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def load_played_groups():
    p = DATA_DIR / "played_groups.json"
    raw = p.read_text(encoding="utf-8") if p.exists() else ""
    return json.loads(raw) if raw.strip() else {}


def load_teams():
    p = DATA_DIR / "teams.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def unwrap_teams_for_ledger(ledger, played_groups):
    """Build a mapping of ledger match_id -> (team_a, team_b) using played_groups."""
    mapping = {}
    for mid in ledger:
        if mid in played_groups:
            m = played_groups[mid]
            mapping[mid] = (m.get("team_a", ""), m.get("team_b", ""))
        else:
            mapping[mid] = ("", "")
    return mapping


def compute_team_signal_strengths(ledger, played_groups):
    """Build per-team rating for each signal type.

    Returns:
        strengths: {signal_name: {team_name: rating_float}}
        rating_type: {signal_name: "rating"|"prob"}
    """
    teams_map = unwrap_teams_for_ledger(ledger, played_groups)

    accum = {}

    def _ensure(sig):
        if sig not in accum:
            accum[sig] = {}

    for mid, signals in ledger.items():
        ta, tb = teams_map.get(mid, ("", ""))
        if not ta or not tb:
            continue

        for sk, sv in signals.items():
            if not sv.get("available"):
                continue
            _ensure(sk)

            if sk == "defensive_quality":
                ra = sv.get("defensive_rating_a")
                rb = sv.get("defensive_rating_b")
                if ra is not None:
                    accum[sk].setdefault(ta, []).append(ra)
                if rb is not None:
                    accum[sk].setdefault(tb, []).append(rb)

            elif sk == "manager_effect":
                ra = sv.get("manager_rating_a")
                rb = sv.get("manager_rating_b")
                if ra is not None:
                    accum[sk].setdefault(ta, []).append(ra)
                if rb is not None:
                    accum[sk].setdefault(tb, []).append(rb)

            else:
                prob = sv.get("probability")
                if prob is not None:
                    accum[sk].setdefault(ta, []).append(prob)
                    accum[sk].setdefault(tb, []).append(1.0 - prob)

    result = {}
    rating_sigs = {"defensive_quality", "manager_effect"}
    for sk, team_vals in accum.items():
        result[sk] = {}
        for team, vals in team_vals.items():
            result[sk][team] = sum(vals) / len(vals) if vals else 0.5

    return result


def compute_ko_signal_probs(ta, tb, team_strengths, elo_ratings):
    """Compute per-signal win probability for a KO match (ta vs tb).

    Returns: {signal_name: probability}, elo_prob
    """
    ALL_SIGNALS = ["form", "lineup_strength", "defensive_quality", "manager_effect", "market_odds", "catboost"]

    elo_a = elo_ratings.get(ta, 1500)
    elo_b = elo_ratings.get(tb, 1500)
    elo_prob = 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))
    elo_prob = round(max(0.01, min(0.99, elo_prob)), 4)

    sigs = {}
    for sk in ALL_SIGNALS:
        strengths = team_strengths.get(sk, {})
        sa = strengths.get(ta)
        sb = strengths.get(tb)
        if sa is not None and sb is not None and (sa + sb) > 0.001:
            prob = sa / (sa + sb)
            prob = max(0.01, min(0.99, round(prob, 4)))
            sigs[sk] = prob
        else:
            sigs[sk] = elo_prob

    return sigs, elo_prob


def compute_form_trend(team_name, played, played_groups):
    """Return last 5 results for a team across all competitions.

    Returns: list of {result: "W"|"D"|"L", gf, ga, opponent, match_id}
    """
    results = []

    for mid, m in played.items():
        ta, tb = m.get("team_a", ""), m.get("team_b", "")
        if ta == team_name:
            gf = m.get("home_score", 0)
            ga = m.get("away_score", 0)
            winner = m.get("winner")
            if winner == ta:
                r = "W"
            elif winner == tb:
                r = "L"
            else:
                r = "D"
            results.append({"result": r, "gf": gf, "ga": ga, "opponent": tb, "match_id": mid})
        elif tb == team_name:
            gf = m.get("away_score", 0)
            ga = m.get("home_score", 0)
            winner = m.get("winner")
            if winner == tb:
                r = "W"
            elif winner == ta:
                r = "L"
            else:
                r = "D"
            results.append({"result": r, "gf": gf, "ga": ga, "opponent": ta, "match_id": mid})

    for mid, m in played_groups.items():
        ta, tb = m.get("team_a", ""), m.get("team_b", "")
        if ta == team_name:
            gf = m.get("home_score", 0)
            ga = m.get("away_score", 0)
            winner = m.get("winner")
            if winner == ta:
                r = "W"
            elif winner == tb:
                r = "L"
            else:
                r = "D"
            results.append({"result": r, "gf": gf, "ga": ga, "opponent": tb, "match_id": mid})
        elif tb == team_name:
            gf = m.get("away_score", 0)
            ga = m.get("home_score", 0)
            winner = m.get("winner")
            if winner == tb:
                r = "W"
            elif winner == ta:
                r = "L"
            else:
                r = "D"
            results.append({"result": r, "gf": gf, "ga": ga, "opponent": ta, "match_id": mid})

    return results[-5:]


def compute_head_to_head(ta, tb, played, played_groups):
    """Return H2H history between two teams."""
    a_wins = 0
    b_wins = 0
    draws = 0
    matches = []

    for mid, m in played.items():
        mt_a, mt_b = m.get("team_a", ""), m.get("team_b", "")
        if (mt_a == ta and mt_b == tb) or (mt_a == tb and mt_b == ta):
            is_swapped = (mt_a == tb)
            winner = m.get("winner")
            hs = m.get("home_score", 0)
            as_ = m.get("away_score", 0)
            if is_swapped:
                a_score, b_score = as_, hs
            else:
                a_score, b_score = hs, as_
            if winner == ta:
                a_wins += 1
            elif winner == tb:
                b_wins += 1
            else:
                draws += 1
            matches.append({"match_id": mid, "team_a": ta, "score": str(a_score) + "-" + str(b_score), "team_b": tb})

    for mid, m in played_groups.items():
        mt_a, mt_b = m.get("team_a", ""), m.get("team_b", "")
        if (mt_a == ta and mt_b == tb) or (mt_a == tb and mt_b == ta):
            is_swapped = (mt_a == tb)
            winner = m.get("winner")
            hs = m.get("home_score", 0)
            as_ = m.get("away_score", 0)
            if is_swapped:
                a_score, b_score = as_, hs
            else:
                a_score, b_score = hs, as_
            if winner == ta:
                a_wins += 1
            elif winner == tb:
                b_wins += 1
            else:
                draws += 1
            matches.append({"match_id": mid, "team_a": ta, "score": str(a_score) + "-" + str(b_score), "team_b": tb})

    return {"matches": matches, "a_wins": a_wins, "b_wins": b_wins, "draws": draws, "total": a_wins + b_wins + draws}


def compute_match_outcome(blended_prob, ta, tb, elo_ratings):
    """Estimate outcome distribution (a_win, draw, b_win) from blend probability."""
    elo_a = elo_ratings.get(ta, 1500)
    elo_b = elo_ratings.get(tb, 1500)
    elo_diff = abs(elo_a - elo_b)

    if elo_diff < 50:
        draw_est = 0.26
    elif elo_diff < 150:
        draw_est = 0.20
    elif elo_diff < 300:
        draw_est = 0.14
    else:
        draw_est = 0.09

    a_win = round(blended_prob * (1 - draw_est), 4)
    draw = round(draw_est, 4)
    b_win = round((1 - blended_prob) * (1 - draw_est), 4)

    total = a_win + draw + b_win
    if abs(total - 1.0) > 0.001:
        a_win = round(a_win / total, 4)
        draw = round(draw / total, 4)
        b_win = round(b_win / total, 4)

    return {"a_win": a_win, "draw": draw, "b_win": b_win}


def generate_insight_text(ta, tb, signals, form_trends, h2h, outcome, eval_data):
    lines = []

    winner_sig = max(signals.items(), key=lambda x: x[1].get("weight", 0) * x[1].get("probability", 0))[0] if signals else None
    if signals and winner_sig:
        sp = signals[winner_sig]
        lines.append(f"{ta} is led by {winner_sig} (P={sp.get('probability', 0.5)*100:.0f}%).")

    if form_trends.get(ta):
        ft = form_trends[ta]
        streak = "".join(r["result"] for r in ft)
        lines.append(f"{ta} form: {streak} in last {len(ft)} matches.")
    if form_trends.get(tb):
        ft = form_trends[tb]
        streak = "".join(r["result"] for r in ft)
        lines.append(f"{tb} form: {streak} in last {len(ft)} matches.")

    if h2h and h2h["total"] > 0:
        lines.append(f"H2H: {ta} {h2h['a_wins']}-{h2h['draws']}-{h2h['b_wins']} {tb} ({h2h['total']} meetings).")

    if outcome:
        lines.append(f"Predicted: {ta} {outcome['a_win']*100:.0f}% / Draw {outcome['draw']*100:.0f}% / {tb} {outcome['b_win']*100:.0f}%.")

    best_sig = None
    best_acc = 0
    if eval_data:
        for sk, se in eval_data.items():
            acc = se.get("accuracy", 0)
            if acc > best_acc and se.get("n_matches", 0) > 5:
                best_acc = acc
                best_sig = sk
    if best_sig:
        lines.append(f"Most reliable signal: {best_sig} ({best_acc*100:.0f}% accuracy).")

    worst_sig = None
    worst_brier = 0
    if eval_data:
        for sk, se in eval_data.items():
            b = se.get("brier", 0.5)
            if b > worst_brier and se.get("n_matches", 0) > 5:
                worst_brier = b
                worst_sig = sk
    if worst_sig and worst_brier >= 0.25:
        lines.append(f"Warning: {worst_sig} signal is unreliable (Brier {worst_brier:.2f}).")

    return " >> ".join(lines) if lines else f"{ta} vs {tb}: no insight data available."


def compute_match_insight(match_id, fb_data, eval_data, blend_weights):
    """Aggregate all insight data for a single match."""
    played = load_played()
    played_groups = load_played_groups()
    teams = load_teams()
    ledger = load_ledger()
    elo_ratings = {n: d["elo"] for n, d in teams.items()}

    # Find match in full bracket
    match_data = None
    for r, ms in fb_data.get("rounds", {}).items():
        for m in ms:
            if m["match_id"] == match_id:
                match_data = m
                break
        if match_data:
            break

    if not match_data:
        return {"error": "match not found"}

    ta = match_data.get("team_a", "")
    tb = match_data.get("team_b", "")
    blended_prob = match_data.get("prob_a", 0.5)

    # Get per-signal probabilities for this match
    team_strengths = compute_team_signal_strengths(ledger, played_groups)
    signals, elo_prob = compute_ko_signal_probs(ta, tb, team_strengths, elo_ratings)

    signals_with_weights = {}
    for sk, prob in signals.items():
        w = (blend_weights or {}).get(sk, 0)
        signals_with_weights[sk] = {
            "probability": prob,
            "weight": round(w, 4),
            "label": sk.replace("_", " ").title()
        }

    # Form trends
    form_trends = {
        ta: compute_form_trend(ta, played, played_groups),
        tb: compute_form_trend(tb, played, played_groups),
    }

    # H2H
    h2h = compute_head_to_head(ta, tb, played, played_groups)

    # Outcome distribution
    outcome = compute_match_outcome(blended_prob, ta, tb, elo_ratings)

    # Natural language insight
    insight = generate_insight_text(ta, tb, signals_with_weights, form_trends, h2h, outcome, eval_data)

    # Match stats from played data
    match_stats = None
    if match_id in played:
        m = played[match_id]
        match_stats = {
            "score": {"home": m.get("home_score"), "away": m.get("away_score")},
            "winner": m.get("winner"),
            "is_draw": m.get("is_draw", False),
            "completed_at": m.get("completed_at", ""),
            "stats": m.get("stats", {}),
            "context": m.get("context", {}),
        }
    elif match_id in played_groups:
        m = played_groups[match_id]
        match_stats = {
            "score": {"home": m.get("home_score"), "away": m.get("away_score")},
            "winner": m.get("winner"),
            "is_draw": m.get("is_draw", False),
            "completed_at": m.get("completed_at", ""),
            "stats": m.get("stats", {}),
            "context": m.get("context", {}),
        }

    return {
        "match_id": match_id,
        "round": match_data.get("round"),
        "teams": {"a": ta, "b": tb},
        "played": match_data.get("played", False),
        "score": match_data.get("score"),
        "winner": match_data.get("winner"),
        "match_stats": match_stats,
        "signals": signals_with_weights,
        "blended_prob": blended_prob,
        "elo_prob": elo_prob,
        "form_trends": {ta: form_trends[ta], tb: form_trends[tb]},
        "head_to_head": h2h,
        "outcome_distribution": outcome,
        "insight": insight,
    }
