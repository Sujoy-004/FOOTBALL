"""UCL display functions — formatted output for simulation results.

D-17 (relaxed for Phase 8): Primarily imports from competitions.ucl.result
and stdlib. Signal types imported from football_core.signal for breakdown
and value-play display. No imports from competitions.ucl.src.

Exports:
    - print_summary(result: SimulationResult) -> None
    - print_league_table(result: SimulationResult) -> None
    - print_playoff_rounds(result: SimulationResult) -> None
    - print_knockout_bracket(result: SimulationResult) -> None
    - print_odds(result: SimulationResult) -> None
    - print_validation_summary(validation_result: dict) -> None
    - show_breakdown(blended_predictions, mode) -> None
    - print_value_plays(blended_predictions) -> None
    - _supports_color() -> bool
    - _ansi(code: str) -> callable
"""

from __future__ import annotations

import sys

from competitions.ucl.result import SimulationResult
from football_core.signal import BlendedPrediction

# ── Module-level constants ──────────────────────────────────────────────

NO_COLOR: bool = False  # Set by main.py when stdout is not a TTY
_SECTION_SEP: str = "=" * 60

# ANSI color codes (D-10: green=top_8, yellow=playoff, red=eliminated)
_GREEN: str = "32"
_YELLOW: str = "33"
_RED: str = "31"
_BOLD: str = "1"


# ── ANSI helpers ────────────────────────────────────────────────────────


def _supports_color() -> bool:
    """Return True if stdout is a TTY and NO_COLOR is not set (D-11)."""
    return sys.stdout.isatty() and not NO_COLOR


def _ansi(code: str):
    """Return a wrapper function that adds ANSI escape codes around text.

    If color is not supported, returns text unchanged.
    """
    def wrapper(text: str) -> str:
        if _supports_color():
            return f"\033[{code}m{text}\033[0m"
        return text
    return wrapper


_green = _ansi(_GREEN)      # top-8 zone
_yellow = _ansi(_YELLOW)    # playoff zone
_red = _ansi(_RED)          # eliminated zone
_bold = _ansi(_BOLD)        # section headings and column headers


def _zone_color(zone: str):
    """Return the ANSI color wrapper for a given qualification zone.

    Args:
        zone: One of "top_8", "playoff", "eliminated".

    Returns:
        A callable that wraps text in the zone's ANSI color,
        or the identity function for unknown zones.
    """
    if zone == "top_8":
        return _green
    elif zone == "playoff":
        return _yellow
    elif zone == "eliminated":
        return _red
    return lambda x: x  # identity for unknown zones


# ── Display functions (D-06: summary first, league table second) ────────


def _require(val, name: str, msg: str = ""):
    """Guard helper: raise TypeError if val is None."""
    if val is None:
        raise TypeError(f"{name} is None. {msg}".strip())
    return val


def print_summary(
    result: SimulationResult | None,
    calibration_info: dict | None = None,
) -> None:
    """Print simulation summary metadata (D-06 position 1).

    Includes iteration count, random seed, snapshot date,
    and optional calibration status.

    Args:
        result: SimulationResult to summarise.
        calibration_info: Optional dict with calibration metadata.
            Expected keys: T, n_matches, log_loss_delta, ece.
    """
    _require(result, "result", "Cannot print summary without a SimulationResult.")
    print()
    print(f"==== Simulation Summary ====")
    print()
    print(f"  Iterations: {getattr(result, 'n_iterations', 'N/A')}")
    print(f"  Seed: {getattr(result, 'seed', 'N/A')}")
    print(f"  Snapshot: {getattr(result, 'snapshot_date', 'N/A')}")

    # ── Calibration status (Phase 10, Plan 03) ───────────────────────
    if calibration_info:
        T = calibration_info.get("T")
        log_loss_before = calibration_info.get("log_loss_before")
        log_loss_after = calibration_info.get("log_loss")
        ece = calibration_info.get("ece")
        n_matches = calibration_info.get("n_samples", 0)

        if T is not None:
            print(f"  Calibration: T={T:.4f} active")
        if n_matches:
            print(f"  Fitted on:   {n_matches} matches")
        if log_loss_before is not None and log_loss_after is not None:
            delta = log_loss_after - log_loss_before
            print(f"  Log-loss Δ:  {delta:+.4f} (calibrated: {log_loss_after:.4f}, "
                  f"raw: {log_loss_before:.4f})")
        if ece is not None:
            print(f"  ECE:         {ece:.4f} (calibrated)")

    print()


# ── Calibration summary display (Phase 10, Plan 03) ────────────────────────


def print_calibration_summary(calibration_info: dict | None) -> None:
    """Display calibration metrics summary in a formatted block.

    Args:
        calibration_info: Dict with calibration metadata, or None to skip.
            Expected keys: T, alpha, n_samples, log_loss, log_loss_before, ece.
    """
    if not calibration_info:
        return

    T = calibration_info.get("T")
    alpha = calibration_info.get("alpha")
    n_samples = calibration_info.get("n_samples", 0)
    log_loss_after = calibration_info.get("log_loss")
    log_loss_before = calibration_info.get("log_loss_before")
    ece = calibration_info.get("ece")

    if T is None and alpha is None:
        return

    print()
    print("── Calibration ──────────────────────────")
    if T is not None:
        print(f"  Temperature:   T = {T:.4f}")
    if n_samples:
        print(f"  Fitted on:     {n_samples} matches")
    if log_loss_before is not None and log_loss_after is not None:
        delta = log_loss_after - log_loss_before
        print(f"  Log-loss Δ:    {delta:+.4f} (calibrated: {log_loss_after:.4f}, "
              f"raw: {log_loss_before:.4f})")
    if ece is not None:
        print(f"  ECE:           {ece:.4f} (calibrated)")
    print("────────────────────────────────────────")


def print_league_table(result: SimulationResult | None) -> None:
    """Print formatted 36-row league table with ANSI zone coloring (D-06 position 2).

    Columns: Pos, Team, Pts, GD, GS, Zone (D-07).
    Zone color: green for top_8, yellow for playoff, red for eliminated (D-10).
    Auto-detects terminal color support (D-11).
    """
    _require(result, "result", "Cannot print league table without a SimulationResult.")
    standings = getattr(result, "standings", None) or []
    if not standings:
        print()
        print("==== League Table ====")
        print()
        print("  (no standings data)")
        print()
        return

    print()
    print(f"==== League Table ====")
    print()

    # ── Header row (bold) ──
    print(
        f"  {_bold('Pos')}  "
        f"{_bold('Team'):<28} "
        f"{_bold('Pts')} "
        f"{_bold('GD')} "
        f"{_bold('GS')} "
        f"{_bold('Zone')}"
    )

    # ── Separator ──
    print("-" * 48)

    # ── Data rows (sorted by position ascending) ──
    for entry in standings:
        zone = entry.get("zone", "eliminated")
        zone_label = zone.upper()
        color_fn = _zone_color(zone)

        pos_str = f"{entry.get('position', '?'):>2}."
        team_str = f"{entry.get('team', '?'):<24}"
        pts_str = f"{entry.get('pts', 0):>3}"
        gd_str = f"{entry.get('gd', 0):>+4}"
        gs_str = f"{entry.get('gs', 0):>3}"
        zone_str = color_fn(f"{zone_label:<10}")

        print(f"{pos_str}  {team_str} {pts_str} {gd_str} {gs_str} {zone_str}")

    print()


# ── Playoff display (D-06 position 3) ──────────────────────────────────


def print_playoff_rounds(result: SimulationResult | None) -> None:
    """Print 8 playoff ties with aggregate scores and advancing winners (D-06 position 3).

    ET/Pens shown only when triggered (D-08).
    """
    _require(result, "result", "Cannot print playoff results without a SimulationResult.")
    playoff_ties = getattr(result, "playoff_ties", None) or {}
    playoff_winners = getattr(result, "playoff_winners", None) or {}
    if not playoff_ties:
        print()
        print("==== Playoff Results ====")
        print()
        print("  (no playoff data)")
        print()
        return

    print()
    print("==== Playoff Results ====")
    print()

    for tie_num in sorted(playoff_ties):
        tie = playoff_ties[tie_num]
        if not isinstance(tie, dict):
            continue
        winner = playoff_winners.get(tie_num, "?")
        team_a = tie.get("winner", "?")
        team_b = tie.get("loser", "?")
        agg_a = tie.get("aggregate_a", 0)
        agg_b = tie.get("aggregate_b", 0)

        # Build aggregate display with optional ET/Pens suffix
        agg_display = f"{agg_a}-{agg_b} agg"
        if tie.get("et_played"):
            agg_display = f"{agg_a}-{agg_b} agg ({tie.get('et_a', 0)}-{tie.get('et_b', 0)} ET)"
        if tie.get("penalties_played"):
            if tie.get("et_played"):
                agg_display = f"{agg_a}-{agg_b} agg ({tie.get('et_a', 0)}-{tie.get('et_b', 0)} ET, {tie.get('penalty_a', 0)}-{tie.get('penalty_b', 0)} pens)"
            else:
                agg_display = f"{agg_a}-{agg_b} agg ({tie.get('penalty_a', 0)}-{tie.get('penalty_b', 0)} pens)"

        print(f"  Tie {tie_num}: {team_a} {agg_display}  {team_b} -> {winner} advances")

    print()


# ── Bracket display (D-06 position 4, D-08 format) ─────────────────────


def print_knockout_bracket(result: SimulationResult | None) -> None:
    """Print round-by-round match list (NOT ASCII tree — D-08).

    Rounds in order: R16 -> QF -> SF -> FINAL.
    Two-legged ties show aggregate scores; FINAL shows single score.
    """
    _require(result, "result", "Cannot print bracket without a SimulationResult.")
    bracket_rounds = getattr(result, "bracket_rounds", None) or {}
    if not bracket_rounds:
        print()
        print("==== Knockout Bracket ====")
        print()
        print("  (no bracket data)")
        print()
        return

    print()
    print("==== Knockout Bracket ====")
    print()

    round_order = ["R16", "QF", "SF", "FINAL"]
    for round_name in round_order:
        print(f"  {_bold(f'--- {round_name} ---')}")

        matches = bracket_rounds.get(round_name, [])
        if not matches:
            print("    (no matches)")
            continue

        for m in matches:
            if not isinstance(m, dict):
                continue
            team_a = m.get("team_a", "?")
            team_b = m.get("team_b", "?")
            r = m.get("result", {})
            if not isinstance(r, dict):
                print(f"    {team_a} vs {team_b}")
                continue

            if r.get("is_final"):
                # Single-match final
                score_line = f"{r.get('score_a', 0)}-{r.get('score_b', 0)}"
                suffix = ""
                if r.get("et_played"):
                    suffix = f" ({r.get('et_a', 0)}-{r.get('et_b', 0)} ET"
                    if r.get("penalties_played"):
                        suffix += f", {r.get('penalty_a', 0)}-{r.get('penalty_b', 0)} pens)"
                    else:
                        suffix += ")"
                elif r.get("penalties_played"):
                    suffix = f" ({r.get('penalty_a', 0)}-{r.get('penalty_b', 0)} pens)"
                print(f"    {team_a} {score_line}{suffix} {team_b}")
            else:
                # Two-legged tie with aggregate scores
                agg_a = r.get("aggregate_a", 0)
                agg_b = r.get("aggregate_b", 0)
                score_line = f"{agg_a}-{agg_b} agg"
                suffix = ""
                if r.get("et_played"):
                    suffix = f" ({r.get('et_a', 0)}-{r.get('et_b', 0)} ET"
                    if r.get("penalties_played"):
                        suffix += f", {r.get('penalty_a', 0)}-{r.get('penalty_b', 0)} pens)"
                    else:
                        suffix += ")"
                elif r.get("penalties_played"):
                    suffix = f" ({r.get('penalty_a', 0)}-{r.get('penalty_b', 0)} pens)"
                print(f"    {team_a} {score_line}{suffix}  {team_b}")

    print()


# ── Signal breakdown display (Phase 8, D-07) ──────────────────────────


def show_breakdown(
    blended_predictions: list[BlendedPrediction] | None = None,
    mode: str = "summary",
) -> None:
    """Display signal breakdown information per D-07.

    Two modes:
    - "summary": Display average weights across all predictions, signal utilization stats
    - "match": Display per-match signal probabilities and weight contributions

    Args:
        blended_predictions: List of BlendedPrediction from EnsembleEngine.
            If None or empty, shows a placeholder message.
        mode: "summary" or "match". Default "summary".
    """
    print()
    print(f"==== Signal Breakdown ({mode}) ====")
    print()

    if not blended_predictions:
        print("  No blended predictions available. Run with signal blending enabled.")
        print()
        return

    if mode == "summary":
        # Compute average weights and utilization across all predictions
        all_weights: dict[str, list[float]] = {}
        for bp in blended_predictions:
            for sig, weight in bp.weights_applied.items():
                if sig not in all_weights:
                    all_weights[sig] = []
                all_weights[sig].append(weight)

        print(f"  {'Signal':<20} {'Avg Weight':>10} {'In Blend':>9}")
        print("  " + "-" * 41)
        for sig in sorted(all_weights.keys()):
            avg_w = sum(all_weights[sig]) / len(all_weights[sig])
            in_blend = len(all_weights[sig])
            print(f"  {sig:<20} {avg_w:>10.4f} {in_blend:>9}")
        print()

    elif mode == "match":
        # Per-match display
        for i, bp in enumerate(blended_predictions):
            print(f"  --- Match {i + 1} ---")
            print(f"  Blended: home={bp.home_prob:.4f}  draw={bp.draw_prob:.4f}  "
                  f"away={bp.away_prob:.4f}")
            print(f"  {'Signal':<20} {'Home':>6} {'Draw':>6} {'Away':>6} {'Weight':>7}")
            print("  " + "-" * 47)
            for sig in sorted(bp.signal_breakdown.keys()):
                sd = bp.signal_breakdown[sig]
                print(f"  {sig:<20} {sd['home']:>6.3f} {sd['draw']:>6.3f} "
                      f"{sd['away']:>6.3f} {sd['weight']:>7.4f}")
            print()


def print_value_plays(
    blended_predictions: list[BlendedPrediction] | None = None,
) -> None:
    """Display value detection — model_prob minus market_implied_prob.

    Per D-04 Tier 3: Value detection display shows where the ensemble's
    prediction differs significantly from market odds (indicating potential
    value).

    Requires that 'market_odds' exists in the signal_breakdown and that
    the blended prediction probabilities differ meaningfully from market.

    Args:
        blended_predictions: List of BlendedPrediction from EnsembleEngine.
            If None or empty, shows a placeholder.
    """
    print()
    print("==== Value Plays (model - market) ====")
    print()

    if not blended_predictions:
        print("  No predictions available for value analysis.")
        print()
        return

    found_value = False
    for i, bp in enumerate(blended_predictions):
        if "market_odds" not in bp.signal_breakdown:
            continue

        md = bp.signal_breakdown["market_odds"]
        market_home = md["home"]
        market_draw = md["draw"]
        market_away = md["away"]

        # Value delta for each outcome
        delta_home = bp.home_prob - market_home
        delta_draw = bp.draw_prob - market_draw
        delta_away = bp.away_prob - market_away

        # Only show significant deltas (|delta| > 5%)
        sig_deltas = []
        for outcome, delta, market_prob, model_p in [
            ("HOME", delta_home, market_home, bp.home_prob),
            ("DRAW", delta_draw, market_draw, bp.draw_prob),
            ("AWAY", delta_away, market_away, bp.away_prob),
        ]:
            if abs(delta) > 0.05:
                sig_deltas.append((outcome, delta, market_prob, model_p))

        if sig_deltas:
            found_value = True
            print(f"  Match {i + 1}:")
            for outcome, delta, mkt, model_p in sig_deltas:
                direction = "OVER" if delta > 0 else "UNDER"
                print(f"    {outcome}: model={model_p:.3f} "
                      f"market={mkt:.3f} "
                      f"delta={delta:+.3f} ({direction}VALUE)")
    if not found_value:
        print("  No significant value plays detected (|delta| <= 5%).")

    print()


# ── Validation display (Phase 4, D-02) ────────────────────────────────


def print_validation_summary(validation_result: dict | None) -> None:
    """Print validation accuracy summary table to stdout (Phase 4, D-02).

    Shows games played, Brier score, Log Loss, accuracy, and calibration ECE.
    Also shows market odds metrics if available.
    """
    _require(validation_result, "validation_result",
             "Cannot print validation summary without data.")
    pm = validation_result.get("prediction_metrics")
    if not isinstance(pm, dict):
        print()
        print("==== Validation Results ====")
        print()
        print("  (no prediction metrics)")
        print()
        return

    print()
    print(f"==== Validation Results ====")
    print()

    print(f"  Games matched: {pm.get('n', 'N/A')}")
    print(f"  Brier Score:   {pm.get('brier', 0.0):.4f}")
    print(f"  Log Loss:      {pm.get('log_loss', 0.0):.4f}")
    print(f"  Accuracy:      {pm.get('accuracy', 0.0):.2%}")
    cal = validation_result.get("calibration") or {}
    print(f"  Calibration ECE: {cal.get('ece', 0.0):.4f}")

    om = validation_result.get("market_odds_metrics")
    if isinstance(om, dict):
        print()
        print(f"  Market Odds Comparison:")
        print(f"    Brier Score:   {om.get('brier', 0.0):.4f}")
        print(f"    Log Loss:      {om.get('log_loss', 0.0):.4f}")
        print(f"    Games with odds: {om.get('n', 0)}")

    print()

    print()


# ── Odds display (D-06 position 5, D-09 format) ────────────────────────


def print_signal_breakdown(
    contributions: dict[str, float] | None,
    champion_team: str | None,
    champion_prob: float,
) -> None:
    """Display per-signal contribution breakdown for champion prediction.

    Shows which signals drive the champion probability and by how much.
    Positive contributions (pushing probability up) shown in green,
    negative contributions (pulling probability down) shown in red.

    Contributions are normalized to sum to champion_prob. If contributions
    dict is empty, prints a placeholder message.

    Args:
        contributions: {signal_name: raw_contribution} from compute_signal_contributions().
        champion_team: Name of the champion team.
        champion_prob: Champion probability as percentage (0-100).
    """
    _require(contributions, "contributions",
             "Cannot print breakdown without contribution data.")
    team_label = champion_team if champion_team else "N/A"
    print()
    print("==== Prediction Breakdown ====")
    print()
    print(f"  Champion: {_bold(team_label)} ({champion_prob:.1f}%)")
    print()

    if not contributions:
        print("  No signal contribution data available.")
        print()
        return

    # Normalize contributions so they sum to champion_prob
    total_raw = sum(contributions.values())
    if abs(total_raw) < 1e-9:
        print("  All signal contributions are near zero.")
        print()
        return

    normalized = {
        sig: round(val / total_raw * champion_prob, 1)
        for sig, val in contributions.items()
    }

    # Sort by absolute contribution descending
    sorted_signals = sorted(
        normalized.items(),
        key=lambda x: -abs(x[1]),
    )

    print(f"  Signal contribution for champion prediction:")
    print()
    for sig_name, contrib in sorted_signals:
        sign = "+" if contrib >= 0 else ""
        formatted = f"{sign}{contrib:.1f}%"
        if contrib >= 0:
            formatted = _green(formatted)
        else:
            formatted = _red(formatted)
        print(f"    {sig_name:<20} {formatted}")

    # Separator line (ASCII only per Windows compatibility)
    print(f"    {'-' * 33}")
    total_formatted = f"{champion_prob:.1f}%"
    print(f"    {'Total:':<20} {_bold(total_formatted)}")
    print()


def print_counterfactual_comparison(
    baseline_result: SimulationResult | None,
    counterfactual_result: SimulationResult | None,
    change_descriptions: list[str] | None,
    n_top: int = 5,
) -> None:
    """Display side-by-side comparison of baseline vs counterfactual results.

    Shows changes applied, top-N champion probabilities with deltas,
    and champion stage probability comparison.

    Args:
        baseline_result: Original SimulationResult (unchanged).
        counterfactual_result: SimulationResult after parameter changes.
        change_descriptions: Human-readable list of what changed.
        n_top: Number of top teams to show in comparison (default 5).
    """
    _require(baseline_result, "baseline_result")
    _require(counterfactual_result, "counterfactual_result")
    change_descriptions = change_descriptions or []

    print()
    print("==== Counterfactual Comparison ====")
    print()

    # Show changes made
    for desc in change_descriptions:
        print(f"  Change: {desc}")
    print()

    # Sort teams by baseline champion probability descending
    sorted_teams = sorted(
        baseline_result.teams.items(),
        key=lambda x: -x[1].get("champion_prob", 0.0),
    )

    # Top-N champion probabilities side-by-side
    print(f"  Top-{n_top} Champion Probabilities:")
    print(f"  {'Team':<24} {'Baseline':>9} {'Counterfactual':>14} {'Delta':>7}")
    print(f"  {'-' * 56}")

    for rank, (team_name, team_data) in enumerate(sorted_teams[:n_top], start=1):
        base_champ = team_data.get("champion_prob", 0.0) * 100
        cf_data = counterfactual_result.teams.get(team_name, {})
        cf_champ = cf_data.get("champion_prob", 0.0) * 100
        delta = cf_champ - base_champ

        print(
            f"  {team_name:<24} "
            f"{base_champ:>8.1f}% "
            f"{cf_champ:>13.1f}% "
            f"{delta:>+7.1f}%"
        )
    print()

    # Stage probabilities for champion team (baseline champion)
    champion_team = baseline_result.bracket_champion
    if champion_team and champion_team in baseline_result.teams:
        print(f"  {champion_team} Stage Probabilities:")
        print(f"  {'Stage':<15} {'Baseline':>9} {'Counterfactual':>14} {'Delta':>7}")
        print(f"  {'-' * 47}")

        stage_keys = [
            ("Champion", "champion_prob"),
            ("Final", "stage_final_prob"),
            ("Semifinal", "stage_sf_prob"),
            ("Quarterfinal", "stage_qf_prob"),
        ]

        base_team_data = baseline_result.teams[champion_team]
        cf_team_data = counterfactual_result.teams.get(champion_team, {})

        for stage_label, prob_key in stage_keys:
            base_val = base_team_data.get(prob_key, 0.0) * 100
            cf_val = cf_team_data.get(prob_key, 0.0) * 100
            delta = cf_val - base_val

            print(
                f"  {stage_label:<15} "
                f"{base_val:>8.1f}% "
                f"{cf_val:>13.1f}% "
                f"{delta:>+7.1f}%"
            )
        print()


def print_calibration_comparison(
    baseline: dict | None,
    calibrated_report: dict | None,
) -> None:
    """Display before/after calibration comparison table.

    Shows three metrics (Log Loss, ECE, TRPS) with Before, After, and Δ
    columns in a formatted table.

    Args:
        baseline: Baseline validation report dict with match_level and
            tournament_level keys.  May be None (placeholder values used).
        calibrated_report: Calibrated validation report dict with same
            structure as baseline.  May be None.
    """
    # ── Extract metric values ──────────────────────────────────────────
    def _extract_metrics(report: dict | None) -> dict:
        if report is None:
            return {"log_loss": None, "ece": None, "trps": None}
        ml = report.get("match_level") or {}
        tl = report.get("tournament_level") or {}
        return {
            "log_loss": ml.get("log_loss"),
            "ece": ml.get("ece", report.get("calibration", {}).get("ece")),
            "trps": tl.get("trps"),
        }

    before = _extract_metrics(baseline)
    after = _extract_metrics(calibrated_report)

    metrics_order = ["Log Loss", "ECE", "TRPS"]
    metric_keys = {"Log Loss": "log_loss", "ECE": "ece", "TRPS": "trps"}

    # ── Print comparison table ─────────────────────────────────────────
    print()
    print("── Calibration Impact ──────────────────")
    print(f"  {'Metric':<15} {'Before':>8} {'After':>8} {'Δ':>8}")
    print(f"  {'-' * 42}")

    for metric_name in metrics_order:
        key = metric_keys[metric_name]
        b_val = before.get(key)
        a_val = after.get(key)

        if b_val is not None and a_val is not None:
            delta = a_val - b_val
            print(f"  {metric_name:<15} {b_val:>8.3f} {a_val:>8.3f} {delta:>+8.3f}")
        elif b_val is not None and a_val is None:
            print(f"  {metric_name:<15} {b_val:>8.3f} {'N/A':>8} {'N/A':>8}")
        elif b_val is None and a_val is not None:
            print(f"  {metric_name:<15} {'N/A':>8} {a_val:>8.3f} {'N/A':>8}")
        else:
            print(f"  {metric_name:<15} {'N/A':>8} {'N/A':>8} {'N/A':>8}")

    print("────────────────────────────────────────")
    print()


def print_odds(
    result: SimulationResult | None,
    show_ci: bool = False,
) -> None:
    """Print champion/qualification odds for all 36 teams (D-06 position 5).

    Columns per D-09: Rank, Team, Champion %, Final %, SF %, QF %.
    Sorted by champion probability descending, with alphabetical tie-break.

    When *show_ci* is True and team data contains ``champion_ci_lower`` /
    ``champion_ci_upper`` fields, the champion column displays
    ``P% ± W%`` format (e.g., ``45.2% ± 3.1%``).

    Args:
        result: SimulationResult with teams data.
        show_ci: If True, show confidence intervals on champion probability.
    """
    _require(result, "result", "Cannot print odds without a SimulationResult.")
    teams_data = getattr(result, "teams", None) or {}
    if not teams_data:
        print()
        print("==== Champion / Qualification Odds ====")
        print()
        print("  (no odds data)")
        print()
        return

    # Sort teams by champion_prob descending, then alphabetically
    sorted_teams = sorted(
        teams_data.items(),
        key=lambda x: (-x[1].get("champion_prob", 0.0), x[0]),
    )

    print()
    print("==== Champion / Qualification Odds ====")
    print()

    # Detect whether CI data is available
    has_ci = show_ci and "champion_ci_lower" in next(iter(teams_data.values()), {})

    # Header row (bold)
    champion_header = f"{_bold('Champion')}" if not has_ci else f"{_bold('Champion ± CI'):>13}"
    print(
        f"  {_bold('Rank'):>4}  "
        f"{_bold('Team'):<24} "
        f"{champion_header} "
        f"{_bold('Final'):>8} "
        f"{_bold('SF'):>8} "
        f"{_bold('QF'):>8}"
    )

    # Separator
    sep_len = 68 if has_ci else 64
    print("  " + "-" * sep_len)

    # Data rows
    for rank, (team_name, team_data) in enumerate(sorted_teams, start=1):
        if not isinstance(team_data, dict):
            continue
        champ = team_data.get("champion_prob", 0.0)
        final = team_data.get("stage_final_prob", 0.0)
        sf = team_data.get("stage_sf_prob", 0.0)
        qf = team_data.get("stage_qf_prob", 0.0)

        if has_ci:
            ci_lo = team_data.get("champion_ci_lower", 0.0)
            ci_hi = team_data.get("champion_ci_upper", 0.0)
            ci_width = (ci_hi - ci_lo) * 100
            champ_str = f"{champ:>6.1%} ± {ci_width:>4.1f}%"
        else:
            champ_str = f"{champ:>7.1%}"

        print(
            f"  {rank:>4}  "
            f"{team_name:<24} "
            f"{champ_str} "
            f"{final:>7.1%} "
            f"{sf:>7.1%} "
            f"{qf:>7.1%}"
        )

    print()
