"""Shared markdown renderer for evaluation reports.

Produces the full ``EVALUATION.md`` for each competition from the harness
result dict (``football_core.historical_backfill.run_evaluation``). One
renderer for all competitions so the D-17 disclosures cannot drift between
them — one copy of the text, one copy of the numerics.

This module is stdlib-only: it never imports ``competitions/*`` or
``candidate_gate``. It is a pure function from ``results: dict -> str`` with
no side effects.

Wording rule: the output is a CI with MDE, never a p-value and never any
claim of a p-value-level effect (D-14/D-16). The unit tests assert that the
rendered report and the module source carry none of the forbidden wording
forms — the module itself must not spell them out, so this docstring
describes the rule without naming them.
"""

from __future__ import annotations

# ══════════════════════════════ D-17 disclosures ══════════════════════════════
# Locked disclosure lines — defined ONCE here, rendered identically in every
# competition's EVALUATION.md. Do not duplicate in drivers.

DISCLOSURES: list[str] = [
    "1. **4-signal surrogate.** The backtest measures a 4-signal ensemble "
    "(`market_odds`, `refined_elo`, `rolling_form`, `rest_days`). "
    "`squad_value` has no historical data source and is renormalized away, "
    "so this is not the live 5-signal engine.",

    "2. **Odds non-transfer.** The backtest population has ~100% closing-odds "
    "coverage while live LaLiga has a handful of fixtures, "
    "`book_selection: \"none\"` and effectively no odds. The result does not transfer "
    "to a live population with sparse odds.",

    "3. **Small-n ECE.** Classwise ECE bins with fewer than 20 observations "
    "are withheld (D-11); the withheld classes are listed rather than "
    "reporting a biased score.",

    "4. **Brier ÷3.** `multi_class_brier` divides by 3, so the scale is "
    "`[0, 2/3]` while sklearn's Brier is `[0, 2]`. The ordered-score "
    "conversion is `ordered_brier = rps/2` for K=3 (EVAL-07).",

    "5. **MDE context (direction-only).** At n≈144 (UCL) the MDE is ≈0.058 "
    "log-loss; at n≈104 (WC) ≈0.069. These confirm direction only — they "
    "are **not** effect claims. This report carries a CI, not a "
    "p-value.",
]


def render_disclosures(extra: list[str] | None = None) -> str:
    """Render the disclosure section, including any competition-specific extras.

    Args:
        extra: Additional competition-specific declarations (e.g. the UCL
            knockout mapping). Rendered after the locked D-17 block.

    Returns:
        The markdown disclosure section as a string.
    """
    lines: list[str] = ["## Disclosures", ""]
    lines.extend(DISCLOSURES)
    if extra:
        lines.append("")
        lines.append("**Competition-specific declarations:**")
        lines.append("")
        for decl in extra:
            lines.append(f"- {decl}")
    lines.append("")
    return "\n".join(lines)


def _fmt(value: dict | None, key: str, decimals: int = 4) -> str:
    """Format a metric value from a metrics dict, or ``—`` if absent/empty."""
    if not value:
        return "—"
    v = value.get(key)
    if v is None:
        return "—"
    return f"{v:.{decimals}f}"


def _ci_str(ci: dict, key: str) -> str:
    """Format a CI string from a CI dict, or ``—`` if absent."""
    if not ci:
        return "—"
    lo = ci.get("2.5")
    hi = ci.get("97.5")
    if lo is None or hi is None:
        return "—"
    return f"[{lo:.4f}, {hi:.4f}]"


def _render_holdout_comparisons(holdout: dict, add) -> None:
    """Render the holdout comparison block (CI + MDE + n per comparison)."""
    comparisons = holdout.get("comparisons", {})
    if not comparisons:
        add("Holdout comparisons: not available.")
        return

    add("| Comparison | ΔLL | 95% CI | MDE | n |")
    add("|---|---|---|---|---|")
    labels = {
        "ensemble_vs_uniform": "ensemble − uniform",
        "ensemble_vs_freq": "ensemble − freq",
        "ensemble_vs_elo_only": "ensemble − elo_only",
        "ensemble_vs_market_only": "ensemble − market_only",
    }
    for key, label in labels.items():
        c = comparisons.get(key)
        if c is None:
            add(f"| {label} | — | — | — | — |")
            continue
        delta = c.get("delta", 0.0)
        lo = c.get("2.5", 0.0)
        hi = c.get("97.5", 0.0)
        mde = c.get("mde", 0.0)
        n = c.get("n", 0)
        add(f"| {label} | {delta:+.4f} | [{lo:.4f}, {hi:.4f}] | {mde:.4f} | {n} |")
    add("")

    # Print the market-only loss explicitly when the ensemble loses
    mkt = comparisons.get("ensemble_vs_market_only")
    if mkt and mkt.get("delta", 0) > 0:
        add(f"**Market-only loss:** ensemble loses to market-only by "
            f"{mkt['delta']:.4f} LL (CI [{mkt['2.5']:.4f}, {mkt['97.5']:.4f}]).")
        add("")


def _render_ordered_score(holdout: dict, add) -> None:
    """Render the match-level ordered score block (RPS + ordered Brier)."""
    ordered = holdout.get("ordered")
    if not ordered:
        add("### Match-level ordered score")
        add("")
        add("Not available.")
        add("")
        return

    rps = ordered.get("rps")
    ob = ordered.get("ordered_brier")
    order = ordered.get("order", ["home", "draw", "away"])
    note = ordered.get("note", "secondary, not a gate")

    add("### Match-level ordered score (RPS)")
    add("")
    add(f"- RPS: {rps:.6f}" if rps is not None else "- RPS: —")
    add(f"- ordered_brier = rps/2: {ob:.6f}" if ob is not None else "- ordered_brier = rps/2: —")
    add(f"- Order: {' → '.join(order)}")
    add(f"- Note: {note}")
    add("")


def _render_tournament_trps(holdout: dict, add) -> None:
    """Render the tournament-level TRPS block (roadmap criterion 1)."""
    ttrps = holdout.get("tournament_trps")
    if not ttrps:
        add("### Tournament-level TRPS (roadmap criterion 1)")
        add("")
        add("Not available.")
        add("")
        return

    # Check for the honest fallback
    if ttrps.get("available") is False:
        reason = ttrps.get("reason", "not available")
        add("### Tournament-level TRPS (roadmap criterion 1)")
        add("")
        add(f"Not available: {reason}")
        add("")
        return

    trps = ttrps.get("trps")
    n_tourn = ttrps.get("n_tournaments")
    per_tourn = ttrps.get("per_tournament", [])
    construction = ttrps.get("construction", "")
    order = ttrps.get("order", "")
    note = ttrps.get("note", "tournament-level TRPS block (roadmap criterion 1); secondary, not a gate")

    add("### Tournament-level TRPS (roadmap criterion 1)")
    add("")
    add(f"- TRPS (mean over tournaments): {trps:.6f}" if trps is not None else "- TRPS: —")
    add(f"- n_tournaments: {n_tourn}")
    if construction:
        add(f"- Construction: {construction}")
    if order:
        add(f"- Order: {order}")
    add(f"- Note: {note}")

    if per_tourn:
        add("")
        add("| Season | TRPS |")
        add("|---|---|")
        for t in per_tourn:
            add(f"| {t.get('season', '?')} | {t.get('trps', 0):.6f} |")
    add("")


def _render_calibration(holdout: dict, add) -> None:
    """Render the calibration block.

    Reads ``holdout["classwise_ece"]`` (LaLiga/UCL) or ``holdout["calibration"]``
    (World Cup confidence variant). Renders ``—`` when neither is present.
    """
    add("### Calibration")
    add("")

    classwise = holdout.get("classwise_ece")
    calibration = holdout.get("calibration")

    if classwise:
        # LaLiga/UCL classwise ECE
        home = classwise.get("home")
        draw = classwise.get("draw")
        away = classwise.get("away")
        macro = classwise.get("macro")
        withheld = classwise.get("withheld", [])

        add(f"- Home ECE: {home:.4f}" if home is not None else "- Home ECE: withheld")
        add(f"- Draw ECE: {draw:.4f}" if draw is not None else "- Draw ECE: withheld")
        add(f"- Away ECE: {away:.4f}" if away is not None else "- Away ECE: withheld")
        add(f"- Macro ECE: {macro:.4f}" if macro is not None else "- Macro ECE: —")
        if withheld:
            add(f"- Withheld classes (small-n): {', '.join(withheld)}")

    elif calibration and isinstance(calibration, dict) and "kind" in calibration:
        # World Cup confidence-based variant
        kind = calibration.get("kind", "")
        add(f"- Variant: {kind}")
        ece = calibration.get("ece")
        if ece is not None:
            add(f"- ECE: {ece:.4f}")
        slope = calibration.get("slope")
        intercept = calibration.get("intercept")
        if slope is not None and intercept is not None:
            add(f"- Slope: {slope:.4f}")
            add(f"- Intercept: {intercept:.4f}")
    else:
        add("—")

    add("")


def _render_verdict(holdout: dict, add) -> None:
    """Render the verdict line (D-16)."""
    verdict = holdout.get("verdict")
    if not verdict:
        add("### Verdict")
        add("")
        add("Not available.")
        add("")
        return

    v = verdict.get("verdict", "not declared")
    won_by = verdict.get("won_by")
    mde = verdict.get("mde")
    n = verdict.get("n")

    add("### Verdict")
    add("")
    add(f"**{v}**")
    if won_by:
        add(f"- Won by: {won_by}")
    if mde is not None:
        add(f"- MDE: {mde:.4f}")
    if n is not None:
        add(f"- n: {n}")
    add("")


def render_evaluation_markdown(
    results: dict,
    *,
    competition: str,
    title: str | None = None,
    extra_declarations: list[str] | None = None,
) -> str:
    """Render the full evaluation report as markdown.

    A pure function from the harness result dict to the report text. Every
    section renders defensively: a missing sub-block renders as ``—`` or
    ``withheld``, never a crash.

    Args:
        results: The dict returned by ``run_evaluation`` (or a subset).
        competition: Competition name (e.g. "LaLiga", "UCL").
        title: Optional override for the report title.
        extra_declarations: Competition-specific declarations rendered near
            the top (e.g. the UCL knockout mapping).

    Returns:
        The full markdown report as a string.
    """
    out: list[str] = []
    add = out.append

    meta = results.get("meta", {}) or {}
    holdout = results.get("holdout", {}) or {}
    bootstrap = holdout.get("bootstrap", {}) or {}
    # The recorded bootstrap seed: the flat holdout key the report contract
    # names, else the harness's ``holdout["bootstrap"]["seed"]``, else meta.
    seed = holdout.get("seed", bootstrap.get("seed", meta.get("seed")))

    # ── Header ──
    if title:
        add(f"# {title}")
    else:
        dataset = meta.get("dataset", "unknown")
        add(f"# {competition} Out-of-Sample Model Evaluation — {dataset}")
    add("")
    add(f"**Competition:** {competition}  ")
    add(f"**Dataset:** `{meta.get('dataset', '—')}`  ")
    add(f"**Generated:** `{meta.get('generated_at', '—')}`  ")
    add(f"**Method:** {meta.get('method', '—')}  ")
    if seed is not None:
        add(f"**Seed:** {seed}  ")
    add("")

    # ── Extra declarations (e.g. UCL KO mapping) ──
    if extra_declarations:
        add("## Declarations")
        add("")
        for decl in extra_declarations:
            add(f"- {decl}")
        add("")

    # ── Population counts ──
    add("## Population counts")
    add("")
    per_season = results.get("per_season", {})
    if per_season:
        add("| Season | n usable | odds n | elo-covered n |")
        add("|---|---|---|---|")
        for s, info in per_season.items():
            add(f"| {s} | {info.get('n', 0)} | {info.get('odds_n', 0)} | "
                f"{info.get('elo_covered_n', 0)} |")
        add("")
    else:
        add("—")
        add("")

    # ── Cross-season results ──
    add("## Cross-season results")
    add("")
    if per_season:
        add("| Season | Ens LL | Br | ECE | Unif LL | Elo LL | Mkt LL | Freq LL |")
        add("|---|---|---|---|---|---|---|---|")
        for s, info in per_season.items():
            all_m = info.get("all", {})
            ens = all_m.get("ensemble", {})
            unif = all_m.get("uniform", {})
            elo = all_m.get("elo_only", {})
            odds_m = info.get("odds") or {}
            mkt = odds_m.get("market_odds_only", {})
            win = info.get("window", {})
            freq = win.get("freq", {})
            add(f"| {s} | {_fmt(ens, 'log_loss')} | {_fmt(ens, 'brier')} | "
                f"{_fmt(ens, 'ece')} | {_fmt(unif, 'uniform_log_loss')} | "
                f"{_fmt(elo, 'log_loss')} | {_fmt(mkt, 'log_loss')} | "
                f"{_fmt(freq, 'log_loss')} |")
        add("")
    else:
        add("—")
        add("")

    # ── Holdout block ──
    add("## Holdout (fixed chronological split)")
    add("")
    if holdout:
        add(f"- Split: {holdout.get('split', '—')}")
        add(f"- Cutoff: {holdout.get('cutoff', '—')}")
        add(f"- n_train: {holdout.get('n_train', '—')}")
        add(f"- n_test: {holdout.get('n_test', '—')}")
        add("")
        _render_holdout_comparisons(holdout, add)
    else:
        add("—")
        add("")

    # ── Match-level ordered score ──
    _render_ordered_score(holdout, add)

    # ── Tournament-level TRPS ──
    _render_tournament_trps(holdout, add)

    # ── Calibration ──
    _render_calibration(holdout, add)

    # ── Ablation ──
    add("## Leave-one-signal-out ablation")
    add("")
    ablation = results.get("ablation", {})
    overall_abl = ablation.get("overall", {})
    if overall_abl:
        add("| Config | n | LL | Brier | ECE |")
        add("|---|---|---|---|---|")
        for cfg, metrics in overall_abl.items():
            if cfg == "n":
                continue
            add(f"| {cfg} | {metrics.get('n', 0)} | "
                f"{_fmt(metrics, 'log_loss')} | {_fmt(metrics, 'brier')} | "
                f"{_fmt(metrics, 'ece')} |")
        add("")
    else:
        add("—")
        add("")

    # ── Learned weights ──
    # The harness nests the per-window fits under ``weights_learned["per_season"]``
    # (``weights_learned["stability"]`` is a sibling summary, not a window row),
    # and each window entry carries ``train_pool_n`` + ``weights`` + ``evaluation``.
    add("## Learned weights by training window")
    add("")
    learned = results.get("weights_learned", {})
    per_window = learned.get("per_season", {}) if isinstance(learned, dict) else {}
    if per_window:
        add("| Train → Eval | train n | odds | elo | form | rest | OOS LL |")
        add("|---|---|---|---|---|---|---|")
        for window, info in per_window.items():
            w = info.get("weights", {}) or {}
            ev = info.get("evaluation", {}) or {}
            add(f"| {window} | {info.get('train_pool_n', 0)} | "
                f"{w.get('market_odds', 0):.4f} | "
                f"{w.get('refined_elo', 0):.4f} | "
                f"{w.get('rolling_form', 0):.4f} | "
                f"{w.get('rest_days', 0):.4f} | "
                f"{_fmt(ev, 'log_loss')} |")
        add("")
    else:
        add("—")
        add("")

    # ── Verdict ──
    _render_verdict(holdout, add)

    # ── Disclosures ──
    # The locked D-17 block only; competition-specific declarations were
    # already rendered once under "## Declarations" near the top.
    add(render_disclosures())

    return "\n".join(out)
