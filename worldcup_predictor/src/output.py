"""Console output module for the World Cup predictor.

Pure display functions using raw ANSI escape codes. No external dependencies.
"""

import logging
import sys
import time
from typing import Callable

from src.constants import GROUP_COUNT, MATCHES_PER_GROUP, POLL_INTERVAL
from src.elo_sync import get_staleness_level


import math

# Ensure stdout uses UTF-8 for Unicode symbols (▲, ▼, ⚠, →) on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NO_COLOR = False
"""Module-level flag: set to True to disable ANSI color output. Set from main.py after arg parsing (D-05)."""

logger = logging.getLogger(__name__)


def _supports_color() -> bool:
    """Return True if stdout is a TTY and NO_COLOR is not set."""
    return sys.stdout.isatty() and not NO_COLOR


def _ansi(code: str) -> Callable[[str], str]:
    """Factory: return a function that wraps text in ANSI escape code."""
    def wrapper(text: str) -> str:
        if _supports_color():
            return f"\033[{code}m{text}\033[0m"
        return text
    return wrapper


_dim = _ansi("2")
_bold_cyan = _ansi("1;36")
_green = _ansi("32")
_red = _ansi("31")
_bold_green = _ansi("1;32")
_bold_white = _ansi("1;37")
_bold_yellow = _ansi("1;33")
_bold_red = _ansi("1;31")


def _timestamp() -> str:
    """Return dim-gray timestamp string: [YYYY-MM-DD HH:MM:SS]."""
    return _dim(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}]")


def _compute_trend_arrow(current_prob: float, team_name: str, prob_log: list[dict]) -> str:
    """Compute trend arrow for a team based on rolling 5-window mean.

    Args:
        current_prob: Current champion probability for the team.
        team_name: Canonical team name.
        prob_log: List of probability snapshot dicts from probability_log.json.

    Returns:
        "↑" if current > window mean + threshold,
        "↓" if current < window mean - threshold,
        "→" if within threshold,
        " " if insufficient data (< 6 snapshots).
    """
    threshold = 0.005
    if len(prob_log) < 6:
        return " "
    window = prob_log[-6:-1]
    window_probs = [
        s.get("probabilities", {}).get(team_name, {}).get("champion", 0.0)
        for s in window
    ]
    window_mean = sum(window_probs) / len(window_probs)
    if current_prob > window_mean + threshold:
        return "↑"
    elif current_prob < window_mean - threshold:
        return "↓"
    else:
        return "→"


def print_probability_table(probs: dict, prev_probs: dict | None = None, prob_log: list[dict] | None = None) -> None:
    """Print the top-5 probability table with optional delta and trend columns."""
    sorted_names = sorted(probs, key=lambda n: probs[n]["champion"], reverse=True)
    top5 = sorted_names[:5]
    remaining = sorted_names[5:]

    label = "Initial probabilities:" if prev_probs is None else "UPDATED PROBABILITIES:"
    print(f"{_timestamp()} {_bold_cyan(label)}")

    has_delta = prev_probs is not None
    has_trend = prob_log is not None and len(prob_log) >= 6

    header = f"{'':>3} {'Team':<18} {'QF':>6} {'SF':>6} {'FINAL':>8} {'CHAMPION':>8}"
    if has_delta:
        header += f"  {'Delta':>8}"
    if has_trend:
        header += f"  {'Trend':>6}"
    print(_bold_cyan(header))

    sep_len = 51 + (9 if has_delta else 0) + (8 if has_trend else 0)
    print(_bold_cyan("-" * sep_len))

    for rank, name in enumerate(top5, 1):
        p = probs[name]
        row = f"{rank:>2}. {name:<18} {p['qf']:.3f} {p['sf']:.3f} {p['final']:.3f} {p['champion']:.3f}"
        if has_delta and name in prev_probs:
            delta = probs[name]["champion"] - prev_probs[name]["champion"]
            if delta > 0:
                delta_str = _green(f"▲ {delta:+.3f}")
            elif delta < 0:
                delta_str = _red(f"▼ {delta:+.3f}")
            else:
                delta_str = f" {'=':>6} "
            row += f"  {delta_str:>8}"
        elif has_delta:
            row += f"  {'—':>8}"
        if has_trend and name in probs:
            arrow = _compute_trend_arrow(probs[name]["champion"], name, prob_log)
            row += f"  {arrow:>6}"
        print(row)

    if remaining:
        best_name = remaining[0]
        best_val = probs[best_name]["champion"]
        print(f" ─── {len(remaining)} other teams — best: {best_name} ({best_val:.3f})")

    print()


def print_delta_summary(probs: dict, prev_probs: dict | None) -> None:
    """Print Biggest Risers / Biggest Fallers top-3 block."""
    if prev_probs is None:
        return

    deltas = []
    for name in probs:
        if name in prev_probs:
            delta = probs[name]["champion"] - prev_probs[name]["champion"]
            deltas.append((name, delta))

    deltas.sort(key=lambda x: x[1], reverse=True)
    risers = deltas[:3]
    fallers = [d for d in reversed(deltas) if d[1] < 0][:3]

    print(_bold_cyan("Biggest Risers"))
    for name, delta in risers:
        print(f"  {_green(f'▲ {name:<16} {delta:+.1%}')}")

    print()
    print(_bold_cyan("Biggest Fallers"))
    for name, delta in fallers:
        print(f"  {_red(f'▼ {name:<16} {delta:+.1%}')}")

    print()


def print_simulation_duration(elapsed_seconds: float) -> None:
    """Print simulation duration in bold green."""
    print(f"{_timestamp()} {_bold_green(f'Re-simulating (50000 runs)... done in {elapsed_seconds:.1f}s')}")


# ─── Group standings display ──────────────────────────────────────────
# Column widths for box-drawing table (content between │ separators)
_STANDINGS_COLS = {
    "group": 9,   # " Group A "
    "team": 28,   # " Team Name 1" padded
    "pts": 6,     # "     7"
    "gd": 7,      # "    +3"
    "gs": 6,      # "     5"
}


def _standings_top_border() -> str:
    """Build the top border of the group standings table."""
    c = _STANDINGS_COLS
    return "┌" + "┬".join(["─" * c[k] for k in ("group", "team", "pts", "gd", "gs")]) + "┐"


def _standings_mid_border() -> str:
    """Build the separator border between groups."""
    c = _STANDINGS_COLS
    return "├" + "┼".join(["─" * c[k] for k in ("group", "team", "pts", "gd", "gs")]) + "┤"


def _standings_bot_border() -> str:
    """Build the bottom border of the group standings table."""
    c = _STANDINGS_COLS
    return "└" + "┴".join(["─" * c[k] for k in ("group", "team", "pts", "gd", "gs")]) + "┘"


def _standings_row(group_label: str, team_field: str, pts: str, gd: str, gs: str) -> str:
    """Build a single data row for the group standings table."""
    c = _STANDINGS_COLS
    cells = [
        f" {group_label:^{c['group'] - 2}} ",
        f" {team_field:<{c['team'] - 2}} ",
        f"{pts:>{c['pts']}}",
        f"{gd:>{c['gd']}}",
        f"{gs:>{c['gs']}}",
    ]
    return "│" + "│".join(cells) + "│"


def _gd_str(gd: int) -> str:
    """Format goal difference: + prefix for positive, raw for non-positive."""
    return f"+{gd}" if gd > 0 else str(gd)


def print_group_standings(standings: dict, third_place_rankings: list) -> None:
    """Print box-drawing group standings table for all 12 groups.

    Args:
        standings: Dict mapping group letter -> list of team standings dicts
                   (output of compute_standings()). Each entry has keys:
                   team, position, pts, gd, gs.
        third_place_rankings: Ranked list of third-placed teams (unused here,
                              kept for interface consistency).
    """
    # Check for empty/no-data case (D-15: first startup placeholder)
    if not standings or all(len(v) == 0 for v in standings.values()):
        print(f"{_timestamp()} {_bold_cyan('Group Standings:')}")
        print("  (no group matches played yet)")
        print()
        return

    print(f"{_timestamp()} {_bold_cyan(f'GROUP STANDINGS — {GROUP_COUNT} groups, best 8 third-placed advance')}")
    print(_standings_top_border())

    for i, group_letter in enumerate("ABCDEFGHIJKL"):
        if i > 0:
            print(_standings_mid_border())

        group_data = standings.get(group_letter, [])

        if not group_data:
            # Empty group (unlikely but handle gracefully)
            print(_standings_row(f"Group {group_letter}", "(no data)", "", "", ""))
            continue

        for row_idx, team_data in enumerate(group_data):
            group_label = f"Group {group_letter}" if row_idx == 0 else ""
            team_field = f"{team_data['team']} {team_data['position']}"
            pts_str = str(team_data["pts"])
            gd_str = _gd_str(team_data["gd"])
            gs_str = str(team_data["gs"])
            print(_standings_row(group_label, team_field, pts_str, gd_str, gs_str))

    print(_standings_bot_border())
    print()


def print_third_place_bubble(third_place_rankings: list) -> None:
    """Print third-place advancement bubble: 8th vs 9th cutoff (D-14).

    Args:
        third_place_rankings: Ranked list of 12 third-placed team dicts,
                              sorted best-to-worst. Each entry has keys:
                              group, team, pts, gd, gs, conduct_score.
    """
    if not third_place_rankings or len(third_place_rankings) < 9:
        return

    eighth = third_place_rankings[7]  # index 7 = 8th best
    ninth = third_place_rankings[8]   # index 8 = 9th best

    # Determine cutoff margin metric (D-14)
    if eighth["pts"] != ninth["pts"]:
        margin = f"Pts = {eighth['pts'] - ninth['pts']}"
    elif eighth["gd"] != ninth["gd"]:
        margin = f"GD = {eighth['gd'] - ninth['gd']}"
    else:
        margin = f"GS = {eighth['gs'] - ninth['gs']}"

    print(f"{_timestamp()} Third-place bubble:")
    print(f"  8. {eighth['team']}  {eighth['pts']} pts  GD {_gd_str(eighth['gd'])}  {_green('ADVANCES')}")
    print(f"  9. {ninth['team']}  {ninth['pts']} pts  GD {_gd_str(ninth['gd'])}  {_red('OUT')}")
    print(f"  Cutoff margin: {margin}")
    print()


def print_header(
    teams: dict[str, dict],
    bracket: list[dict],
    played: dict[str, dict],
    aliases: dict[str, list[str]],
    groups: dict | None = None,
    annex_c: dict | None = None,
) -> None:
    """Print startup banner with team/bracket/played/alias counts."""
    print()
    print(_bold_cyan("=" * 60))
    print(_bold_cyan("  WORLD CUP DYNAMIC PREDICTOR — v1.1"))
    print(_bold_cyan(f"  Polling API every {POLL_INTERVAL} seconds. Press Ctrl+C to stop."))
    group_count = len(groups.get("groups", groups)) if groups else 0
    annex_count = len([k for k in (annex_c or {}) if k != "_meta"])
    print(_bold_cyan(
        f"  Loaded {len(teams)} teams, {len(bracket)} bracket matches, "
        f"{len(played)} played matches, {len(aliases)} aliases"
        f"{f', {group_count} groups ({group_count * MATCHES_PER_GROUP} group matches), {annex_count} Annex C scenarios' if groups else ''}."
    ))
    print(_bold_cyan("=" * 60))
    print()


def print_match_alert(match: dict) -> None:
    """Print highlighted match result block with bold yellow banner."""
    print()
    print(_bold_yellow("=" * 60))
    print(_bold_yellow("  NEW MATCH DETECTED!"))
    team_a = _bold_white(match["team_a"])
    team_b = _bold_white(match["team_b"])
    print(f"  {team_a} {match['home_score']} - {match['away_score']} {team_b}")
    print(f"  Winner: {match['winner']}")
    print(_bold_yellow("=" * 60))


def print_ai_previews(played: dict, played_groups: dict) -> None:
    """Print AI preview text for all played matches.

    Default console output unchanged. AI preview shown only when --ai-preview
    CLI flag is passed (D-09). Missing ai_preview produces no warnings or errors (D-11).

    Args:
        played: Dict of played knockout matches.
        played_groups: Dict of played group matches.
    """
    has_any = False

    for group_letter in "ABCDEFGHIJKL"[:GROUP_COUNT]:
        group_matches = [
            m for m in played_groups.values()
            if m.get("match_id", "").startswith(f"GS_{group_letter}_")
        ]
        if not group_matches:
            continue
        for match in sorted(group_matches, key=lambda m: m.get("match_id", "")):
            preview = match.get("ai_preview")
            if preview:
                if not has_any:
                    print(_bold_white("\n─── AI Previews ───"))
                    has_any = True
                print(f"\n{_bold_white(match['team_a'])} vs {_bold_white(match['team_b'])}:")
                print(preview)

    if played:
        for mid in sorted(played):
            match = played[mid]
            preview = match.get("ai_preview")
            if preview:
                if not has_any:
                    print(_bold_white("\n─── AI Previews ───"))
                    has_any = True
                print(f"\n{_bold_white(match['team_a'])} vs {_bold_white(match['team_b'])}:")
                print(preview)

    if not has_any:
        print(_dim("No AI previews available."))


def print_elo_changes(updates: dict[str, dict[str, float]]) -> None:
    """Print Elo rating changes after a match.

    Args:
        updates: {team_name: {"old": float, "new": float}}
    """
    print(f"{_timestamp()} Updating Elo:")
    for team_name in updates:
        old = updates[team_name]["old"]
        new_rating = updates[team_name]["new"]
        delta = int(round(new_rating - old))
        delta_str = f"({'+' if delta >= 0 else ''}{delta})"
        colored_delta = _green(delta_str) if delta >= 0 else _red(delta_str)
        arrow = "→"
        print(f"   {team_name:<12} {int(old)} {arrow} {int(new_rating)}  {colored_delta}")


def print_sync_results(corrections: list[dict], elapsed: float) -> None:
    """Print a single-line Elo sync summary with drift flag count.

    Args:
        corrections: List of correction log entries from sync_elo_from_eloratings().
            Empty list = sync succeeded with no drift.
        elapsed: Time in seconds the sync pipeline took.
    """
    if not corrections:
        print(f"{_timestamp()} Elo sync: no corrections needed ({elapsed:.1f}s)")
        return

    flagged = sum(1 for c in corrections if c.get("reason") == "overwrite_drift_gt_30")
    blended = sum(1 for c in corrections if c.get("reason") == "blended_50pct")
    print(
        f"{_timestamp()} Elo sync: corrected {_bold_cyan(str(len(corrections)))} ratings "
        f"({_bold_cyan(str(flagged))} flagged >30pt drift) "
        f"in {elapsed:.1f}s"
    )


def print_staleness_warning(hours_since_sync: float) -> None:
    """Print graduated staleness warning for Elo cache age per D-16.

    Level 0 (< 24h): no output (green/silent).
    Level 1 (< 48h): logger.info() — systemic, not user-visible.
    Level 2 (< 72h): yellow warning to stderr.
    Level 3 (< 168h): red warning to stderr.
    Level 4 (>= 168h): critical red warning to stderr.

    Args:
        hours_since_sync: Hours since the last successful Elo sync.
    """
    level, label = get_staleness_level(hours_since_sync)
    hours_int = int(hours_since_sync)

    if level == 0:
        return  # green — silent

    if level == 1:
        logger.info("Elo cache age: %d hours", hours_int)
        return

    if level == 2:
        print(
            f"{_timestamp()} {_bold_yellow(f'⚠ Elo data age: {hours_int} hours — next refresh overdue')}",
            file=sys.stderr,
        )
        return

    # Level 3+ (red / critical)
    print(
        f"{_timestamp()} {_bold_red(f'🚨 Elo data age: {hours_int} hours — refresh critically overdue')}",
        file=sys.stderr,
    )


def print_drift_flags(flags: list[dict]) -> None:
    """Print drift flag details for corrections > 30 pt overwrite.

    Args:
        flags: List of correction entries with reason='overwrite_drift_gt_30'.
            Each entry has keys: team, old_value, new_value, drift_magnitude.
            Empty list produces no output.
    """
    if not flags:
        return

    flagged = [f for f in flags if f.get("reason") == "overwrite_drift_gt_30"]
    if not flagged:
        return

    print(f"{_timestamp()} {_bold_yellow('Drift flags for investigation:')}")
    for entry in flagged:
        team = _bold_yellow(entry.get("team", "???"))
        old_v = entry.get("old_value", "?")
        new_v = entry.get("new_value", "?")
        drift = entry.get("drift_magnitude", "?")
        print(f"  {team}: {old_v} -> {new_v} (drift: {drift})")


def print_heartbeat() -> None:
    """Print single-line heartbeat for poll cycles with no new matches."""
    print(f"{_timestamp()} Polling... no new matches.")


def print_auto_refresh() -> None:
    """Print one-liner for hourly auto-refresh simulation."""
    print(f"{_timestamp()} Auto-refresh simulation (no new matches in 1h)")


def print_shutdown_banner(probs: dict[str, dict[str, float]]) -> None:
    """Print final championship probabilities with ALL teams (full table)."""
    print()
    print(_bold_green("=" * 60))
    print(_bold_green("  FINAL CHAMPIONSHIP PROBABILITIES"))
    print(_bold_green("=" * 60))

    sorted_teams = sorted(probs, key=lambda n: probs[n]["champion"], reverse=True)
    print(f"{'':>3} {'Team':<18} {'QF':>6} {'SF':>6} {'FINAL':>8} {'CHAMPION':>8}")
    print("-" * 51)

    for rank, name in enumerate(sorted_teams, 1):
        p = probs[name]
        print(f"{rank:>2}. {name:<18} {p['qf']:.3f} {p['sf']:.3f} {p['final']:.3f} {p['champion']:.3f}")

    print()
    print(_bold_green("State saved. Goodbye."))


def print_error(message: str) -> None:
    """Print bold red error with warning prefix and timestamp to stderr."""
    print(f"{_timestamp()} {_bold_red(f'⚠ {message}')}", file=sys.stderr)


# ─── Governance Dashlet (Phase 16-02) ─────────────────────────────────────


def print_governance_dashlet(
    versions: dict,
    status: str,
    n_matches: int,
    per_signal_brier: dict[str, float],
    blend_weights: dict[str, float],
    drift_results: dict | None = None,
    backtest_summary: str | None = None,
) -> None:
    """Print the MODEL GOVERNANCE dashlet block.

    Cold-start mode (< 30 matches): D-17 format with version info,
    match count, explicit cold-start status, PENDING/DISABLED/READY lines.
    Active mode (>= 30 matches): D-18 format with per-signal Brier table
    and drift status column.

    Args:
        versions: Dict with data_version, model_version, run_version keys.
        status: "COLD START" | "HEALTHY" | "DRIFT".
        n_matches: Number of matches seen.
        per_signal_brier: Dict of {signal_key: brier_value}.
        blend_weights: Dict of {signal_key: weight}.
        drift_results: Dict of {signal_key: drift_info} or None.
        backtest_summary: Optional backtest summary string.
    """
    from src.constants import COLD_START_THRESHOLD

    print()
    print(_bold_cyan("MODEL GOVERNANCE"))
    print()

    # Always show version info
    data_v = versions.get("data_version", "D?")
    model_v = versions.get("model_version", "M?")
    run_v = versions.get("run_version", "R?")

    if n_matches < COLD_START_THRESHOLD:
        # Cold-start format (D-17)
        print(f"Data Version : {data_v}")
        print(f"Model Version: {model_v}")
        print(f"Run Version  : {run_v}")
        print()
        print(f"Matches Seen : {n_matches} / {COLD_START_THRESHOLD}")
        print(f"Status       : {_bold_yellow('COLD START')}")
        print()
        print(f"Baseline     : PENDING")
        print(f"Drift Check  : DISABLED")
        print(f"Backtesting  : READY")
    else:
        # Active format (D-18)
        print(f"Data  : {data_v}")
        print(f"Model : {model_v}")
        print(f"Run   : {run_v}")
        print()

        if status == "DRIFT":
            print(f"Status : {_bold_red('DRIFT')}")
        else:
            status_color = _bold_cyan if status == "HEALTHY" else _bold_yellow
            print(f"Status : {status_color(status)}")
        print()

        # Per-signal Brier table
        header = f"{'Signal':<20} {'Brier':>8}  {'Drift':>6}"
        print(header)
        print("-" * len(header))

        for signal_key in sorted(per_signal_brier.keys()):
            brier_val = per_signal_brier[signal_key]
            drift_ok = True
            if drift_results and signal_key in drift_results:
                drift_ok = not drift_results[signal_key].get("drifted", False)
            drift_label = _green("OK") if drift_ok else _red("DRIFT")
            print(f"{signal_key:<20} {brier_val:>8.3f}  {drift_label:>6}")

        print()
        print(f"Baseline Window : {COLD_START_THRESHOLD}")
        print(f"Rolling Window  : 50")

    # Drift alert section (only when drift exists)
    if drift_results:
        for signal_key, drift_info in drift_results.items():
            if drift_info.get("drifted", False):
                print_drift_alert(drift_info)

    # Backtest summary
    if backtest_summary:
        print()
        print(f"Backtest : {backtest_summary}")

    print()


# ─── Coverage Auditor (Phase 20-01) ────────────────────────────────────────

_PREDICTION_FIELDS: list[str] = [
    "odds_home", "odds_draw", "odds_away", "expected_goals",
    "actual_home_xg", "actual_away_xg", "odds_over_25", "odds_under_25",
    "odds_btts_yes", "expected_home_goals", "expected_away_goals",
]

_DISPLAY_FIELDS: list[str] = [
    "home_score", "away_score", "event_date", "venue.name", "referee.name",
    "ai_preview.text", "yellow_cards", "red_cards", "shots_on_target",
    "ball_possession", "venue.city", "home_coach.name", "away_coach.name",
    "round_name", "fouls", "corner_kicks", "shots_off_target",
    "shots_inside_box", "temperature_c", "wind_speed", "weather_code",
    "pitch_condition", "attendance", "funfacts", "home_score_ht", "away_score_ht",
    "event_uuid",
]

_OPERATIONAL_FIELDS: list[str] = [
    "id", "status", "home_team", "away_team", "league.id",
    "group_name", "winner", "period", "current_minute",
]


def coverage_audit() -> dict:
    """Compute coverage metrics against 47-field meaningful denominator.

    Returns:
        dict with keys:
            - meaningful: {covered, total, pct, target, target_met, missing}
            - raw: {covered, total, pct}
            - by_category: {category: {covered, total, pct}}
    """
    extracted_display = {
        "venue.name", "referee.name", "ai_preview.text", "yellow_cards",
        "red_cards", "shots_on_target", "ball_possession", "venue.city",
        "home_coach.name", "away_coach.name", "fouls", "corner_kicks",
        "shots_off_target", "home_score", "away_score", "event_date",
        "round_name",
    }
    extracted_prediction = {
        "odds_home", "odds_draw", "odds_away",
        "expected_home_goals", "expected_away_goals",
    }
    extracted_operational = {
        "id", "status", "home_team", "away_team",
        "league.id", "group_name", "winner",
    }
    total_extracted = extracted_display | extracted_prediction | extracted_operational

    meaningful_all = set(_PREDICTION_FIELDS + _DISPLAY_FIELDS + _OPERATIONAL_FIELDS)
    n_meaningful = len(meaningful_all)
    n_meaningful_covered = len(total_extracted & meaningful_all)
    pct_meaningful = round(n_meaningful_covered / n_meaningful * 100, 1) if n_meaningful else 0.0

    categories = {
        "Prediction": (extracted_prediction, set(_PREDICTION_FIELDS)),
        "Display": (extracted_display, set(_DISPLAY_FIELDS)),
        "Operational": (extracted_operational, set(_OPERATIONAL_FIELDS)),
    }
    by_category = {}
    for name, (extracted_set, total_set) in categories.items():
        covered = len(extracted_set & total_set)
        total = len(total_set)
        by_category[name] = {
            "covered": covered,
            "total": total,
            "pct": round(covered / total * 100, 1) if total else 0.0,
        }

    missing = sorted(meaningful_all - total_extracted)

    return {
        "meaningful": {
            "covered": n_meaningful_covered,
            "total": n_meaningful,
            "pct": pct_meaningful,
            "target": 60.0,
            "target_met": pct_meaningful >= 60.0,
            "missing": missing,
        },
        "raw": {
            "covered": len(total_extracted),
            "total": len(meaningful_all),  # meaningless? meaningless is a subset of raw
            "pct": round(len(total_extracted) / len(meaningful_all) * 100, 1) if meaningful_all else 0.0,
        },
        "by_category": by_category,
    }


def print_coverage_audit() -> None:
    """Print the coverage audit report (D-17 format)."""
    audit = coverage_audit()
    m = audit["meaningful"]
    r = audit["raw"]

    print(f"\n{_bold_white('Coverage Audit')}")
    target_label = f"← target: ≥60%" if not m["target_met"] else f"✓ target ≥60% met"
    target_color = _red if not m["target_met"] else _green
    print(f"  {_dim('Meaningful:')}  {m['covered']}/{m['total']} ({m['pct']}%)  {target_color(target_label)}")
    print(f"  {_dim('Raw:')}         {r['covered']}/{r['total']} ({r['pct']}%)")
    print(f"  {_dim('By value:')}")
    for name, cat in sorted(audit["by_category"].items()):
        print(f"    {name}:  {cat['covered']}/{cat['total']} ({cat['pct']}%)")


def print_drift_alert(drift_info: dict) -> None:
    """Print the expanded drift detection block (D-18, drift variant).

    Args:
        drift_info: Dict with keys: signal, reference_baseline, rolling_mean,
                   threshold, delta.
    """
    print()
    print(_bold_red("DRIFT DETECTED"))
    print()
    print(f"Signal      : {drift_info.get('signal', '?')}")
    print(f"Reference   : {drift_info.get('reference_baseline', 0.0):.3f}")
    print(f"Rolling     : {drift_info.get('rolling_mean', 0.0):.3f}")
    print(f"Threshold   : {drift_info.get('threshold', 0.0):.3f}")
    print(f"Delta       : +{drift_info.get('delta', 0.0):.3f}")
