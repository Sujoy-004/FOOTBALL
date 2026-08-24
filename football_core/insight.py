"""Shared match-level football intelligence — consumed by every competition.

Operates on canonical plain-dict inputs only:

- result rows: ``{"match_id": str?, "team_a": str, "team_b": str,
  "home_score": int, "away_score": int, "winner": str | None?}``
  (``winner`` optional; derived from scores when absent — a level score with
  an explicit winner is a shootout decider, mirroring MatchStatus.PLAYED_PENS)
- per-signal entries: ``{"probability": float, "weight": float, ...}``
- evaluation stats: ``{"accuracy": float, "brier": float, "n_matches": int, ...}``

No imports from competitions/* or web/*; stdlib only.
"""

from __future__ import annotations

from typing import Iterable, Optional

# Refinement-signal roster used when a caller does not restrict the list.
# These are the project-wide canonical signal names (see EnsembleEngine).
DEFAULT_KO_SIGNALS = ("market_odds", "rolling_form", "squad_value", "rest_days")


def _row_goals(row: dict, side_home: bool) -> tuple[int, int]:
    """Return (goals_for, goals_against) from the queried team's perspective."""
    hs = row.get("home_score")
    aw = row.get("away_score")
    gf, ga = (hs, aw) if side_home else (aw, hs)
    return int(gf or 0), int(ga or 0)


def _row_result_letter(row: dict, team: str) -> str:
    """W/D/L for *team* in one normalized row.

    Winner-field override mirrors the canonical match model: an explicit
    winner on a level score is a shootout decision, not a draw.
    """
    ta = row.get("team_a", "")
    tb = row.get("team_b", "")
    is_home = ta == team
    if not is_home and tb != team:
        return ""
    opponent = tb if is_home else ta
    winner = row.get("winner")
    if winner is None or str(winner).strip() in ("", "-"):
        winner = None
    if winner is not None:
        return "W" if winner == team else ("L" if winner == opponent else "D")
    gf, ga = _row_goals(row, is_home)
    if gf > ga:
        return "W"
    if ga > gf:
        return "L"
    return "D"


def form_trend(results: list[dict], team: str, limit: int = 5) -> list[dict]:
    """Last *limit* results for *team* across the provided result rows.

    Returns entries ``{"result": "W"|"D"|"L", "gf", "ga", "opponent",
    "match_id"}`` in input order (callers own chronology).
    """
    entries: list[dict] = []
    for row in results:
        ta = row.get("team_a", "")
        tb = row.get("team_b", "")
        letter = _row_result_letter(row, team)
        if not letter:
            continue
        is_home = ta == team
        gf, ga = _row_goals(row, is_home)
        entries.append({
            "result": letter,
            "gf": gf,
            "ga": ga,
            "opponent": tb if is_home else ta,
            "match_id": row.get("match_id", ""),
        })
    if limit is not None and limit >= 0:
        entries = entries[-limit:] if limit else []
    return entries


def head_to_head(results: list[dict], team_a: str, team_b: str) -> dict:
    """Head-to-head summary between two teams from result rows."""
    a_wins = b_wins = draws = 0
    matches: list[dict] = []
    for row in results:
        mt_a = row.get("team_a", "")
        mt_b = row.get("team_b", "")
        if not ((mt_a == team_a and mt_b == team_b)
                or (mt_a == team_b and mt_b == team_a)):
            continue
        swapped = mt_a == team_b
        hs = int(row.get("home_score") or 0)
        aw = int(row.get("away_score") or 0)
        a_score, b_score = (aw, hs) if swapped else (hs, aw)
        letter = _row_result_letter(row, team_a)
        if letter == "W":
            a_wins += 1
        elif letter == "L":
            b_wins += 1
        else:
            draws += 1
        matches.append({
            "match_id": row.get("match_id", ""),
            "team_a": team_a,
            "score": f"{a_score}-{b_score}",
            "team_b": team_b,
        })
    return {
        "matches": matches,
        "a_wins": a_wins,
        "b_wins": b_wins,
        "draws": draws,
        "total": a_wins + b_wins + draws,
    }


def draw_estimate(elo_diff: float) -> float:
    """Documented Elo-band draw prior used by outcome_distribution."""
    elo_diff = abs(elo_diff)
    if elo_diff < 50:
        return 0.26
    if elo_diff < 150:
        return 0.20
    if elo_diff < 300:
        return 0.14
    return 0.09


def outcome_distribution(
    home_prob: float,
    elo_a: float,
    elo_b: Optional[float] = None,
) -> dict:
    """H/D/A distribution from a home-win probability plus Elo context.

    Accepts ``(home_prob, elo_diff)`` or ``(home_prob, elo_a, elo_b)``;
    both forms produce identical output.
    """
    diff = abs(float(elo_a)) if elo_b is None else abs(float(elo_a) - float(elo_b))
    d = draw_estimate(diff)
    p = min(max(float(home_prob), 0.0), 1.0)
    a_win = round(p * (1 - d), 4)
    draw = round(d, 4)
    b_win = round((1 - p) * (1 - d), 4)

    total = a_win + draw + b_win
    if abs(total - 1.0) > 0.001:
        a_win = round(a_win / total, 4)
        draw = round(draw / total, 4)
        b_win = round(b_win / total, 4)
    return {"a_win": a_win, "draw": draw, "b_win": b_win}


def ko_signal_probs(
    ta: str,
    tb: str,
    team_strengths: dict[str, dict[str, float]],
    elo_ratings: dict[str, float],
    signals: Optional[Iterable[str]] = None,
) -> tuple[dict, float]:
    """Per-signal win probability for a knockout pairing via ratio blending.

    Missing strengths fall back to the pairwise Elo expectation; results are
    clamped to [0.01, 0.99]. Returns ({signal_name: probability}, elo_prob).
    """
    roster = tuple(signals) if signals is not None else DEFAULT_KO_SIGNALS
    elo_a = elo_ratings.get(ta, 1500)
    elo_b = elo_ratings.get(tb, 1500)
    elo_prob = 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))
    elo_prob = round(max(0.01, min(0.99, elo_prob)), 4)

    sigs: dict[str, float] = {}
    for sk in roster:
        strengths = team_strengths.get(sk, {})
        sa = strengths.get(ta)
        sb = strengths.get(tb)
        if sa is not None and sb is not None and (sa + sb) > 0.001:
            prob = sa / (sa + sb)
            sigs[sk] = max(0.01, min(0.99, round(prob, 4)))
        else:
            sigs[sk] = elo_prob
    return sigs, elo_prob


def insight_text(
    ta: str,
    tb: str,
    signals: dict,
    form_trends: dict,
    h2h: dict,
    outcome: dict,
    eval_data: dict,
) -> str:
    """Natural-language match summary from prediction/context parts.

    Sentence templates are part of the shared contract; tests pin them so
    every competition renders identical semantics for identical inputs.
    """
    lines: list[str] = []

    winner_sig = max(
        signals.items(),
        key=lambda x: x[1].get("weight", 0) * x[1].get("probability", 0.5),
    )[0] if signals else None
    if signals and winner_sig:
        sp = signals[winner_sig]
        label = winner_sig.replace("_", " ").title()
        lines.append(f"{ta} is led by {label} (P={sp.get('probability', 0.5)*100:.0f}%).")

    for team in (ta, tb):
        ft = form_trends.get(team) or []
        if ft:
            streak = "".join(r["result"] for r in ft)
            lines.append(f"{team} form: {streak} in last {len(ft)}.")

    if h2h and h2h.get("total", 0) > 0:
        lines.append(
            f"H2H: {ta} {h2h['a_wins']}-{h2h['draws']}-{h2h['b_wins']} {tb} "
            f"({h2h['total']} meetings)."
        )

    if outcome:
        lines.append(
            f"Predicted: {ta} {outcome['a_win']*100:.0f}% / "
            f"Draw {outcome['draw']*100:.0f}% / {tb} {outcome['b_win']*100:.0f}%."
        )

    valid = {k: v for k, v in (eval_data or {}).items() if v.get("n_matches", 0) > 5}
    if valid:
        best_key, best = max(valid.items(), key=lambda kv: kv[1].get("accuracy", 0))
        lines.append(
            f"Most reliable: {best_key.replace('_', ' ').title()} "
            f"({best['accuracy']*100:.0f}% accuracy)."
        )
        worst_key, worst = max(valid.items(), key=lambda kv: kv[1].get("brier", 0))
        if worst.get("brier", 0) >= 0.25:
            lines.append(
                f"Warning: {worst_key.replace('_', ' ').title()} signal unreliable "
                f"(Brier {worst['brier']:.2f})."
            )

    return " >> ".join(lines) if lines else f"{ta} vs {tb}: no insight data available."
