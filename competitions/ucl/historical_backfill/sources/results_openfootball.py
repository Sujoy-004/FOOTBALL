"""Openfootball cl.txt adapter for the historical UCL backfill.

Downloads the per-season football.db text fixtures from the openfootball
champions-league repository, parses them, and returns canonical-keyed
match dicts matching the build.py contract.

Source: https://raw.githubusercontent.com/openfootball/champions-league/
"""

from __future__ import annotations

import os
import re
import tempfile

from competitions.ucl.historical_backfill.contract import (
    ROUND_MATCHDAY,
    SEASONS,
    md_match_id,
)
from competitions.ucl.historical_backfill.team_map import canonical

_CACHE_DIR = os.path.join(tempfile.gettempdir(), "opencode")
_URL_TPL = (
    "https://raw.githubusercontent.com/openfootball/champions-league/"
    "master/{season}/cl.txt"
)

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Local alias layer for openfootball spellings that team_map does not cover
# yet (team_map is out of scope for this adapter; these are reported gaps).
_SOURCE_ALIASES: dict[str, str] = {
    "FK Crvena Zvezda": "Red Star Belgrade",
    "Racing Club de Lens": "Lens",
    "Royal Antwerp FC": "Antwerp",
}

_SECTION_RE = re.compile(r"^▪ (.+)$")
_MD_IN_SECTION_RE = re.compile(r"matchday\s+(\d+)", re.IGNORECASE)
_DATE_RE = re.compile(
    r"^\s+([A-Za-z]{3})\s+([A-Za-z]{3})\s+(\d{1,2})(?:\s+(\d{4}))?\s*$"
)
_COUNTRY_RE = re.compile(r"\(([A-Z]{3})\)\s*$")
_HA_RE = re.compile(r"(\d+)-(\d+)")
_TIME_RE = re.compile(r"^\s*(\d{1,2}:\d{2})\s+")


def _download(url: str, dest: str) -> str:
    """Download *url* to *dest* if not already present."""
    if os.path.isfile(dest):
        return dest
    import requests as _requests
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with _requests.get(url, timeout=60, allow_redirects=True) as resp:
        resp.raise_for_status()
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            f.write(resp.content)
        os.replace(tmp, dest)
    return dest


def _parse_side(raw: str) -> tuple[str, str]:
    """Extract (canonical_key, raw_name) from a team side string."""
    m = _COUNTRY_RE.search(raw)
    if m:
        tag = m.group(1)
        name = raw[: m.start()].strip()
        return canonical(_SOURCE_ALIASES.get(name, name)), tag
    name = raw.strip()
    return canonical(_SOURCE_ALIASES.get(name, name)), ""


def fetch_openfootball_matches() -> dict[str, list[dict]]:
    """Fetch and parse openfootball cl.txt for each backfill season.

    Returns
    -------
    dict[str, list[dict]]
        Keys: "2019_20" .. "2023_24".
        Values: list of match dicts with keys match_id, team_a, team_b,
        home_score, away_score, event_date, round_label, home_ground.
    """
    season_file_map = {
        "2019_20": "2019-20.txt",
        "2020_21": "2020-21.txt",
        "2021_22": "2021-22.txt",
        "2022_23": "2022-23.txt",
        "2023_24": "2023-24.txt",
    }

    # Download / cache each season's file
    for season_key, fname in season_file_map.items():
        season_dir_name = season_key.replace("_", "-")
        dest = os.path.join(_CACHE_DIR, fname)
        if not os.path.isfile(dest):
            url = _URL_TPL.format(season=season_dir_name)
            _download(url, dest)

    results: dict[str, list[dict]] = {}
    for season_key in SEASONS:
        fpath = os.path.join(_CACHE_DIR, season_file_map[season_key])
        results[season_key] = _parse_file(fpath, season_key)
    return results


def _parse_file(path: str, season_key: str) -> list[dict]:
    """Parse a single cl.txt file into a list of normalised match dicts."""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    fixtures: list[dict] = []
    current_round: str | None = None
    current_round_lower: str | None = None
    current_date: str = ""        # YYYY-MM-DD
    current_time: str = "21:00"   # KO time carried forward within a date
    current_year: int = 0
    in_group: bool = False
    current_group: str = ""
    group_explicit_md: int | None = None   # "Group, Matchday N" -> N
    group_fix_seq: dict[str, int] = {}     # counted group -> fixtures seen

    # Extract expected match count from header
    expected = 0
    for line in lines:
        if line.startswith("# Matches"):
            parts = line.split()
            if len(parts) >= 3:
                expected = int(parts[2])
            break

    for line in lines:
        stripped = line.rstrip("\n")

        # Section marker: group or knockout round
        sm = _SECTION_RE.match(stripped)
        if sm:
            section_name = sm.group(1).strip()
            section_lower = section_name.lower()

            if section_lower.startswith(("group", "gruppe")):
                current_round = section_name
                current_round_lower = "group"
                current_group = section_name
                in_group = True
                md_m = _MD_IN_SECTION_RE.search(section_name)
                if md_m:
                    group_explicit_md = int(md_m.group(1))
                else:
                    group_explicit_md = None
                    group_fix_seq.setdefault(current_group, 0)
            else:
                in_group = False
                current_group = ""
                # Normalise round name for ROUND_MATCHDAY lookup
                # Handle "Finals, Round of 16" -> "Round of 16", etc.
                # Handle "Quarterfinals" -> "Quarter-finals", etc.
                norm = section_lower
                if norm.startswith("finals, "):
                    norm = norm[len("finals, "):]
                norm = norm.replace("quarterfinals", "quarter-finals")
                norm = norm.replace("semifinals", "semi-finals")
                norm = norm.strip()
                if norm in ROUND_MATCHDAY:
                    current_round = section_name
                    current_round_lower = norm
                else:
                    current_round = section_name
                    current_round_lower = norm
            continue

        # Date line
        dm = _DATE_RE.match(stripped)
        if dm:
            day_str, mon_str, day_num_str, year_str = dm.groups()
            if year_str:
                current_year = int(year_str)
            mon_num = _MONTHS[mon_str.lower()]
            current_date = f"{current_year}-{mon_num:02d}-{int(day_num_str):02d}"
            continue

        # Fixture line: must contain a score pattern H-A
        score_m = _HA_RE.search(stripped)
        if score_m is None:
            continue

        if not current_date or not current_round:
            continue

        home_score, away_score = int(score_m.group(1)), int(score_m.group(2))

        # Team portion = everything before the full-time score
        team_part = stripped[: score_m.start()]

        # Split on " v " to separate home and away sides
        parts = team_part.split(" v ", 1)
        if len(parts) != 2:
            continue
        time_m = _TIME_RE.match(parts[0])
        if time_m:
            hh, mm = time_m.group(1).split(":")
            current_time = f"{int(hh):02d}:{int(mm):02d}"
        home_raw = _TIME_RE.sub("", parts[0]).strip()
        away_raw = parts[1].strip()

        home_key, _ = _parse_side(home_raw)
        away_key, _ = _parse_side(away_raw)

        md_num: int
        if in_group and current_group:
            if group_explicit_md is not None:
                md_num = group_explicit_md
            else:
                # A group has exactly 2 fixtures per matchday, so number
                # the matchday from the fixture position within the group
                # (robust to rounds split across two date lines, e.g. the
                # Rangers-Napoli postponement in 2022/23).
                seq = group_fix_seq[current_group]
                group_fix_seq[current_group] = seq + 1
                md_num = seq // 2 + 1
        elif current_round_lower in ROUND_MATCHDAY:
            md_num = ROUND_MATCHDAY[current_round_lower]
        else:
            md_num = 1  # fallback

        fixtures.append({
            "date": current_date,
            "time": current_time,
            "home_key": home_key,
            "away_key": away_key,
            "home_score": home_score,
            "away_score": away_score,
            "matchday_num": md_num,
            "round_label": current_round,
            "group": current_group,
        })

    # Validate expected count
    if expected and len(fixtures) != expected:
        print(
            f"WARNING {season_key}: parsed {len(fixtures)} fixtures "
            f"but header says {expected}"
        )

    # Assign match_ids:
    #   Group matchdays: sort all 16 fixtures in a matchday by
    #     (date, group_label, home_key) then index 1..16
    #   Knockout matchdays: index in file order 1..N
    season_matches: list[dict] = []

    group_by_md: dict[int, list[dict]] = {}
    ko_by_md: dict[int, list[dict]] = {}
    for fx in fixtures:
        if fx["group"]:
            group_by_md.setdefault(fx["matchday_num"], []).append(fx)
        else:
            ko_by_md.setdefault(fx["matchday_num"], []).append(fx)

    # Process group matchdays (sorted by date, group, home)
    for md_num in sorted(group_by_md):
        fxs = group_by_md[md_num]
        fxs.sort(key=lambda f: (f["date"], f["group"], f["home_key"]))
        for idx, fx in enumerate(fxs, start=1):
            mid = md_match_id(md_num, idx)
            event_date = f"{fx['date']}T{fx['time']}:00Z"
            season_matches.append({
                "match_id": mid,
                "team_a": fx["home_key"],
                "team_b": fx["away_key"],
                "home_score": fx["home_score"],
                "away_score": fx["away_score"],
                "event_date": event_date,
                "round_label": fx["round_label"],
                "home_ground": "home",
            })

    # Process knockout matchdays (index in file order)
    for md_num in sorted(ko_by_md):
        fxs = ko_by_md[md_num]
        for idx, fx in enumerate(fxs, start=1):
            mid = md_match_id(md_num, idx)
            event_date = f"{fx['date']}T{fx['time']}:00Z"

            # Neutral ground for 2019/20 post-lockdown matches (>= 2020-08-01)
            # and knockout rounds (quarter-finals and later)
            neutral = (
                season_key == "2019_20"
                and fx["date"] >= "2020-08-01"
                and fx["matchday_num"] >= ROUND_MATCHDAY.get("quarter-finals", 8)
            )

            season_matches.append({
                "match_id": mid,
                "team_a": fx["home_key"],
                "team_b": fx["away_key"],
                "home_score": fx["home_score"],
                "away_score": fx["away_score"],
                "event_date": event_date,
                "round_label": fx["round_label"],
                "home_ground": "neutral" if neutral else "home",
            })

    return season_matches
