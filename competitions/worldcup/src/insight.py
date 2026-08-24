import json, math
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


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

            prob = sv.get("probability")
            if prob is not None:
                accum[sk].setdefault(ta, []).append(prob)
                accum[sk].setdefault(tb, []).append(1.0 - prob)

    result = {}
    for sk, team_vals in accum.items():
        result[sk] = {}
        for team, vals in team_vals.items():
            result[sk][team] = sum(vals) / len(vals) if vals else 0.5

    return result


def _normalized_rows(played: dict, played_groups: dict) -> list[dict]:
    """Flatten the two WC result stores into shared-kernel result rows.

    Order mirrors the historical iteration (knockout store first, then
    groups), keeping form/H2H windows byte-compatible.
    """
    rows: list[dict] = []
    for mid, m in played.items():
        rows.append({**m, "match_id": mid})
    for mid, m in played_groups.items():
        rows.append({**m, "match_id": mid})
    return rows


def compute_ko_signal_probs(ta, tb, team_strengths, elo_ratings):
    """Compute per-signal win probability for a KO match (ta vs tb).

    Delegates to the shared kernel in football_core.insight.

    Returns: {signal_name: probability}, elo_prob
    """
    from football_core.insight import ko_signal_probs as _core_ko_signal_probs
    return _core_ko_signal_probs(ta, tb, team_strengths, elo_ratings)


def compute_form_trend(team_name, played, played_groups):
    """Return last 5 results for a team across all competitions.

    Delegates to the shared kernel in football_core.insight.

    Returns: list of {result: "W"|"D"|"L", gf, ga, opponent, match_id}
    """
    from football_core.insight import form_trend as _core_form_trend
    return _core_form_trend(_normalized_rows(played, played_groups), team_name, limit=5)


def compute_head_to_head(ta, tb, played, played_groups):
    """Return H2H history between two teams.

    Delegates to the shared kernel in football_core.insight.
    """
    from football_core.insight import head_to_head as _core_head_to_head
    return _core_head_to_head(_normalized_rows(played, played_groups), ta, tb)


def compute_match_outcome(blended_prob, ta, tb, elo_ratings):
    """Estimate outcome distribution (a_win, draw, b_win) from blend probability.

    Delegates to the shared kernel in football_core.insight.
    """
    from football_core.insight import outcome_distribution as _core_outcome_dist
    return _core_outcome_dist(
        blended_prob,
        elo_ratings.get(ta, 1500),
        elo_ratings.get(tb, 1500),
    )


def generate_insight_text(ta, tb, signals, form_trends, h2h, outcome, eval_data):
    """Generate natural-language insight text.

    Delegates to the shared kernel in football_core.insight (shared sentence
    templates; signal labels are Title-Cased).
    """
    from football_core.insight import insight_text as _core_insight_text
    return _core_insight_text(ta, tb, signals, form_trends, h2h, outcome, eval_data)


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
    blended_prob = match_data.get("prob_a")
    prob_available = bool(ta) and bool(tb) and blended_prob is not None
    if not prob_available:
        prob_reason = "slot_unresolved" if not (ta and tb) else "no_probability"
        blended_prob = None
        outcome = {}
    else:
        prob_reason = None

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
    if blended_prob is not None:
        outcome = compute_match_outcome(blended_prob, ta, tb, elo_ratings)
    else:
        outcome = {}

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
        "match_status": "played" if match_data.get("played") else "scheduled",
        "provenance": "official",
        "prob_available": prob_available,
        "prob_reason": prob_reason,
        "match_stats": match_stats,
        "signals": signals_with_weights,
        "blended_prob": blended_prob,
        "elo_prob": elo_prob,
        "form_trends": {ta: form_trends[ta], tb: form_trends[tb]},
        "head_to_head": h2h,
        "outcome_distribution": outcome,
        "insight": insight,
    }
