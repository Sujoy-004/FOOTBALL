"""Prebuilt market-odds adapter for the historical UEFA Champions League backfill.

Reads closing 1X2 odds from the CC-BY-4.0 v-eatpizzanot/soccer-dataset
(HuggingFace) parquet files and attaches them to UCL fixtures keyed by
(ISO date, canonical home, canonical away) per season.

``attach_odds()`` returns:
    dict[season_label, dict[(date, home, away), odds_dict]]
where season_label is one of "2019_20" .. "2023_24" and odds_dict has
keys: odds_home, odds_draw, odds_away (floats), bookmaker (str),
known_at (str|None).
"""

from __future__ import annotations

import os
import sys
from typing import Any

import pandas as pd

from competitions.ucl.historical_backfill.contract import SEASONS
from competitions.ucl.historical_backfill.team_map import canonical

TEMP_DIR = r"C:\Users\KIIT0001\AppData\Local\Temp\opencode"
PARQUET_FILES = ["fixtures.parquet", "odds.parquet", "leagues.parquet", "teams.parquet"]
HF_BASE = "https://huggingface.co/datasets/eatpizzanot/soccer-dataset/resolve/main"

BOOKMAKER_PREF = ["Pinnacle", "Bet365", "888sport", "Unibet", "Betfair", "William Hill"]

UCL_LEAGUE_ID = 89


def _ensure_parquet(name: str) -> str:
    """Return path to parquet file, downloading it if missing."""
    path = os.path.join(TEMP_DIR, name)
    if not os.path.exists(path):
        import urllib.request
        url = f"{HF_BASE}/{name}"
        print(f"Downloading {name} ...")
        urllib.request.urlretrieve(url, path)
    return path


def _load_parquet(name: str) -> pd.DataFrame:
    return pd.read_parquet(_ensure_parquet(name))


def _season_label(start_year: int) -> str | None:
    """Map a kickoff year to our season label. Only 2019-2023 inclusive."""
    mapping = {2019: "2019_20", 2020: "2020_21", 2021: "2021_22", 2022: "2022_23", 2023: "2023_24"}
    return mapping.get(start_year)


def _fixture_season(start_year: int, month: int) -> str | None:
    """Determine season label from kickoff date components.

    If month > 6, season starts in *start_year* (e.g. Sep 2020 -> 2020_21).
    If month <= 6, season started the previous year (e.g. Mar 2020 -> 2019_20).
    """
    if month > 6:
        return _season_label(start_year)
    else:
        return _season_label(start_year - 1)


def attach_odds() -> dict[str, dict[tuple[str, str, str], dict[str, Any]]]:
    """Attach closing 1X2 odds to UCL fixtures for seasons 2019/20-2023/24.

    Returns:
        dict keyed by season label ("2019_20".."2023_24"), each value a dict
        keyed by (event_date_iso, canonical_home, canonical_away) mapping to
        an odds dict with floats and bookmaker metadata.
    """
    fixtures_df = _load_parquet("fixtures.parquet")
    odds_df = _load_parquet("odds.parquet")
    teams_df = _load_parquet("teams.parquet")

    # Build team_id -> name mapping
    team_id_to_name: dict[int, str] = {}
    for _, row in teams_df.iterrows():
        team_id_to_name[int(row["id"])] = str(row["name"])

    # Filter fixtures to UCL and played matches
    ucl = fixtures_df[
        (fixtures_df["league_id"] == UCL_LEAGUE_ID) & (fixtures_df["is_played"] == True)
    ].copy()

    # Build season buckets
    fixture_map: dict[str, list[dict[str, Any]]] = {s: [] for s in SEASONS}
    for _, fix in ucl.iterrows():
        date_str = str(fix["date_utc"])
        # Parse date
        from datetime import datetime as _dt
        dt = _dt.fromisoformat(date_str.replace("Z", "+00:00"))
        season = _fixture_season(dt.year, dt.month)
        if season is None:
            continue
        fixture_map[season].append({
            "id": int(fix["id"]),
            "date": date_str[:10],
            "home_team_id": int(fix["home_team_id"]),
            "away_team_id": int(fix["away_team_id"]),
        })

    # Build odds index: fixture_id -> list of odds rows
    odds_by_fixture: dict[int, list[dict[str, Any]]] = {}
    for _, od in odds_df.iterrows():
        fid = int(od["fixture_id"])
        home_win = od["home_win"]
        draw = od["draw"]
        away_win = od["away_win"]
        # Filter invalid: must all be finite floats > 1.0
        try:
            hw = float(home_win)
            dr = float(draw)
            aw = float(away_win)
        except (TypeError, ValueError):
            continue
        if not (hw > 1.0 and dr > 1.0 and aw > 1.0):
            continue
        if not (sys.float_info.min < hw < sys.float_info.max and
                sys.float_info.min < dr < sys.float_info.max and
                sys.float_info.min < aw < sys.float_info.max):
            continue
        odds_by_fixture.setdefault(fid, []).append({
            "home_win": hw,
            "draw": dr,
            "away_win": aw,
            "bookmaker": str(od.get("bookmaker", "")),
            "known_at": str(od.get("known_at")) if pd.notna(od.get("known_at")) else None,
        })

    # For each fixture, pick best odds row by bookmaker preference
    def _pick_best(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not rows:
            return None
        # Sort by bookmaker preference (lower index = higher priority)
        def bm_priority(row: dict[str, Any]) -> int:
            bm = row["bookmaker"]
            try:
                return BOOKMAKER_PREF.index(bm)
            except ValueError:
                return len(BOOKMAKER_PREF)
        rows_sorted = sorted(rows, key=bm_priority)
        return rows_sorted[0]

    # Canonicalization failures tracker
    recon_failures: list[tuple[str, str, str]] = []  # (team_source, fixture_id, season)

    result: dict[str, dict[tuple[str, str, str], dict[str, Any]]] = {s: {} for s in SEASONS}
    per_season_stats: dict[str, dict[str, int]] = {}

    all_bookmakers_found: set[str] = set()

    for season, fixtures in fixture_map.items():
        played = len(fixtures)
        with_odds = 0
        failures = 0

        for fix in fixtures:
            fid = fix["id"]
            home_name = team_id_to_name.get(fix["home_team_id"])
            away_name = team_id_to_name.get(fix["away_team_id"])

            if home_name is None or away_name is None:
                failures += 1
                recon_failures.append((str(fix.get("home_team_id", "?")), str(fid), season))
                continue

            try:
                c_home = canonical(home_name)
            except KeyError:
                failures += 1
                recon_failures.append((home_name, str(fid), season))
                continue

            try:
                c_away = canonical(away_name)
            except KeyError:
                failures += 1
                recon_failures.append((away_name, str(fid), season))
                continue

            odds_rows = odds_by_fixture.get(fid, [])
            best = _pick_best(odds_rows)
            if best is None:
                continue

            with_odds += 1
            all_bookmakers_found.add(best["bookmaker"])
            key = (fix["date"], c_home, c_away)
            result[season][key] = {
                "odds_home": best["home_win"],
                "odds_draw": best["draw"],
                "odds_away": best["away_win"],
                "bookmaker": best["bookmaker"],
                "known_at": best["known_at"],
            }

        per_season_stats[season] = {
            "fixtures_played": played,
            "fixtures_with_odds": with_odds,
            "unmatched_canonical_failures": failures,
        }

    # Print per-season report
    print("\n=== UCL Odds Adapter Report ===")
    for season in SEASONS:
        stats = per_season_stats[season]
        print(
            f"  {season}: fixtures_played={stats['fixtures_played']}, "
            f"fixtures_with_odds={stats['fixtures_with_odds']}, "
            f"unmatched_canonical_failures={stats['unmatched_canonical_failures']}"
        )

    extra_bookmakers = all_bookmakers_found - set(BOOKMAKER_PREF)
    if extra_bookmakers:
        print(f"\nBookmakers found beyond preference list: {sorted(extra_bookmakers)}")
    else:
        print("\nAll bookmakers within preference list.")

    if recon_failures:
        print(f"\nCanonical failures ({len(recon_failures)}):")
        for team, fid, sea in recon_failures[:10]:
            print(f"  team={team!r}, fixture_id={fid}, season={sea}")

    return result


if __name__ == "__main__":
    d = attach_odds()
    print("\nPer-season fixture-with-odds counts:")
    for k, v in d.items():
        print(f"  {k}: {len(v)}")

    # Print 3 sample odds triples
    print("\nSample odds triples:")
    count = 0
    for season, entries in d.items():
        for key, odds in entries.items():
            if count >= 3:
                break
            date, home, away = key
            print(
                f"  [{season}] {date} {home} vs {away} | "
                f"bookmaker={odds['bookmaker']} | "
                f"home={odds['odds_home']:.2f} draw={odds['odds_draw']:.2f} away={odds['odds_away']:.2f}"
            )
            count += 1
        if count >= 3:
            break
