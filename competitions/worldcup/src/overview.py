"""World Cup competition-overview computation.

Format rules live here, not in the web layer; ``web/wc_app.py`` re-exports
``compute_overview`` for transport.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from competitions.worldcup.src import constants
from competitions.worldcup.src.bracket import compute_bracket_display, compute_full_bracket
from competitions.worldcup.src.state import load_groups
from football_core.runtime_support import boot_step

DATA_DIR = constants.DATA_DIR


def load_json(data_dir, name: str) -> dict:
    """Read one JSON store as a dict.

    Mirrors ``web.common.load_json`` rather than importing it: that helper is a
    web-layer concern, and the brain must not depend on the web layer.
    """
    with open(data_dir / name, encoding="utf-8") as f:
        return dict(json.load(f))


def compute_real_standings(
    groups_data: dict,
    played_groups: dict,
    teams: dict | None = None,
) -> list[dict]:
    """Compute deterministic real standings from played group matches with FIFA tiebreakers.

    Returns a flat list sorted by group, then position:
    [{group, position, team, pts, gd, gs, ga, played, ...}, ...]
    """
    from football_core.constants import DEFAULT_ELO
    from football_core.groups import _compute_conduct_score, _tiebreak_group

    elo_ratings = {n: d.get("elo", DEFAULT_ELO) for n, d in teams.items()} if teams else {}
    standings = []
    for group_letter in sorted(groups_data.keys()):
        group = groups_data[group_letter]
        team_stats: dict[str, dict] = {}
        for team in group.get("teams", []):
            team_stats[team] = {
                "team": team,
                "group": group_letter,
                "pts": 0,
                "gd": 0,
                "gs": 0,
                "ga": 0,
                "played": 0,
                "yellow_cards": 0,
                "red_cards": 0,
                "conduct_score": 0,
                "elo": elo_ratings.get(team, float(DEFAULT_ELO)),
            }
        group_results: dict[str, dict] = {}
        for match in group.get("matches", []):
            mid = match["match_id"]
            if mid not in played_groups:
                continue
            m = played_groups[mid]
            ta, tb = m["team_a"], m["team_b"]
            hs = m.get("home_score", 0)
            aw = m.get("away_score", 0)
            yca = m.get("yellow_cards_a", 0)
            rca = m.get("red_cards_a", 0)
            ycb = m.get("yellow_cards_b", 0)
            rcb = m.get("red_cards_b", 0)

            if ta not in team_stats:
                team_stats[ta] = {
                    "team": ta,
                    "group": group_letter,
                    "pts": 0,
                    "gd": 0,
                    "gs": 0,
                    "ga": 0,
                    "played": 0,
                    "yellow_cards": 0,
                    "red_cards": 0,
                    "conduct_score": 0,
                    "elo": elo_ratings.get(ta, float(DEFAULT_ELO)),
                }
            if tb not in team_stats:
                team_stats[tb] = {
                    "team": tb,
                    "group": group_letter,
                    "pts": 0,
                    "gd": 0,
                    "gs": 0,
                    "ga": 0,
                    "played": 0,
                    "yellow_cards": 0,
                    "red_cards": 0,
                    "conduct_score": 0,
                    "elo": elo_ratings.get(tb, float(DEFAULT_ELO)),
                }

            ts_a, ts_b = team_stats[ta], team_stats[tb]
            ts_a["played"] += 1
            ts_b["played"] += 1
            ts_a["gs"] += hs
            ts_a["ga"] += aw
            ts_a["gd"] += (hs - aw)
            ts_b["gs"] += aw
            ts_b["ga"] += hs
            ts_b["gd"] += (aw - hs)
            ts_a["yellow_cards"] += yca
            ts_a["red_cards"] += rca
            ts_b["yellow_cards"] += ycb
            ts_b["red_cards"] += rcb
            if hs > aw:
                ts_a["pts"] += 3
            elif aw > hs:
                ts_b["pts"] += 3
            else:
                ts_a["pts"] += 1
                ts_b["pts"] += 1

            group_results[mid] = {
                "team_a": ta,
                "team_b": tb,
                "score_a": hs,
                "score_b": aw,
                "yellow_cards_a": yca,
                "red_cards_a": rca,
                "yellow_cards_b": ycb,
                "red_cards_b": rcb,
            }

        for stats in team_stats.values():
            stats["conduct_score"] = _compute_conduct_score(
                stats["yellow_cards"], stats["red_cards"]
            )

        team_list = list(team_stats.values())
        sorted_teams = _tiebreak_group(team_list, group_results)
        for i, t in enumerate(sorted_teams, 1):
            t["position"] = i
            standings.append(t)
    return standings


def compute_signals_meta() -> dict:
    """Check on-disk signal cache files and return metadata."""
    cache_files: list[tuple[str, str]] = [
        ("odds_cache.json", "market_odds"),
        ("rolling_form_cache.json", "rolling_form"),
        ("squad_value_cache.json", "squad_value"),
        ("rest_days_cache.json", "rest_days"),
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

    The boot log is a PER-CALL local: two request threads can no longer
    interleave a rebind and an append on a shared module global (the log
    was a module-level list before, so concurrent calls could splice one
    call's steps into another's diagnostics).
    """
    boot_log: list[dict] = []
    data = {"boot": []}

    ld = boot_step("Data Loading", lambda: {
        "teams": load_json(DATA_DIR, "teams.json"),
        "groups": load_groups(DATA_DIR, teams=load_json(DATA_DIR, "teams.json")),
        "bracket": json.loads((DATA_DIR / "bracket.json").read_text(encoding="utf-8")),
        "annex_c": json.loads((DATA_DIR / "annex_c.json").read_text(encoding="utf-8")),
        "played": json.loads((DATA_DIR / "played.json").read_text(encoding="utf-8")) if (DATA_DIR / "played.json").exists() else {},
        "played_groups": json.loads((DATA_DIR / "played_groups.json").read_text(encoding="utf-8")) if (DATA_DIR / "played_groups.json").exists() else {},
    }, boot_log)
    if not ld:
        return {"boot": boot_log, "error": "data load failed"}
    teams, groups_data = ld["teams"], ld["groups"]["groups"]
    bracket, annex_c = ld["bracket"], ld["annex_c"]
    played, played_groups = ld["played"], ld["played_groups"]

    total_played = sum(1 for m in played.values() if m.get("winner"))
    total_played += sum(1 for m in played_groups.values() if m.get("winner"))

    gs = boot_step("Group Standings", lambda:
        compute_real_standings(groups_data, played_groups, teams)
    , boot_log) or []

    from competitions.worldcup.src.groups import rank_third_placed
    standings_by_group: dict[str, list[dict]] = {}
    for row in gs:
        standings_by_group.setdefault(row["group"], []).append(row)
    data["third_place"] = rank_third_placed(standings_by_group)

    bracket_display = boot_step("Bracket Resolution", lambda:
        compute_bracket_display(ld["groups"], teams, bracket, annex_c, played, played_groups)
    , boot_log)

    signals_meta = compute_signals_meta()

    team_list = [{"name": name, "elo": round(d["elo"], 1)} for name, d in sorted(teams.items(), key=lambda t: t[1].get("elo", 1500), reverse=True)]

    full_bracket = compute_full_bracket(
        ld["groups"], teams, bracket, annex_c, played, played_groups,
    )

    data["boot"] = boot_log
    data["teams"] = team_list
    data["n_teams"] = len(team_list)
    data["n_played"] = total_played
    data["standings"] = gs
    data["bracket"] = bracket_display
    data["full_bracket"] = full_bracket
    data["signals_meta"] = signals_meta
    # Authoritative competition phase (competition brain owns derivation).
    from competitions.worldcup.src.pipeline import compute_competition_phase
    data["phase"] = boot_step("Competition Phase", lambda: compute_competition_phase(DATA_DIR), boot_log)
    # Season-lifecycle view (same key contract as the UCL discover output),
    # reusing the phase report just computed instead of re-deriving it.
    try:
        from competitions.worldcup.src.pipeline import season_lifecycle
        phase_report = data["phase"] if isinstance(data["phase"], dict) else None
        data["lifecycle"] = season_lifecycle(DATA_DIR, phase=phase_report)
    except Exception:
        data["lifecycle"] = {}
    # Freshness from the persisted refresh report (survives cache rebuilds).
    # The ledger lives in the web layer, so its path is derived by the pipeline;
    # resolving that reader at call time keeps a redirected ledger (tests patch
    # pipeline._last_refresh_report_path) authoritative for this code too.
    try:
        from competitions.worldcup.src.pipeline import _last_refresh_report_path
        lr = json.loads(_last_refresh_report_path().read_text(encoding="utf-8"))
        data["refresh"] = lr.get("worldcup", {})
    except Exception:
        data["refresh"] = {}
    return data
