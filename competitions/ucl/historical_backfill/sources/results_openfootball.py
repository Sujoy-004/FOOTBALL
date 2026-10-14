"""Openfootball cl.txt adapter for the historical UCL backfill.

Downloads the per-season football.db text fixtures from the openfootball
champions-league repository, parses them, and returns canonical-keyed
match dicts matching the build.py contract.

The adapter is *window-generic*: the season list comes from
``contract.SEASONS`` and the parser understands every format era the source
actually publishes in-window — the classic group stage (``Group A``..``H``,
2011/12-2022/23), the group stage with explicit matchdays (``Group, Matchday
N``, 2023/24), and the 36-team league phase (``League, Matchday N`` +
``Playoffs, Matchday N``, 2024/25+). A season the source does not serve, or a
section whose format the parser cannot represent, is returned as an explicit
exclusion (named with a reason) — never silently dropped and never mis-labelled
to fit a single era.

Source: https://raw.githubusercontent.com/openfootball/champions-league/
"""

from __future__ import annotations

import os
import re
import tempfile

import requests

from competitions.ucl.historical_backfill.contract import (
    ROUND_MATCHDAY,
    ROUND_MATCHDAY_LEAGUE,
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


class SourceUnavailableError(Exception):
    """The upstream archive does not serve this season's file."""


class UnsupportedFormatError(Exception):
    """The season uses a competition format the parser cannot represent.

    Raised instead of guessing a round label; the build excludes the season
    and reports it by name with this reason.
    """

    def __init__(self, season: str, section: str) -> None:
        super().__init__(
            f"{season}: unrecognised competition format section {section!r} "
            "— refusing to guess a round label"
        )
        self.season = season
        self.section = section


# Seasons whose post-lockdown knockout rounds (quarter-final onward) were
# played on neutral ground; the date is the COVID resumption boundary.
_NEUTRAL_KO: dict[str, str] = {"2019_20": "2020-08-01"}


def _normalise_section(section_lower: str) -> str:
    """Normalise a knockout section header to a ko-map key (or leave as-is)."""
    norm = section_lower
    if norm.startswith("finals, "):
        norm = norm[len("finals, "):]
    norm = norm.replace("quarterfinals", "quarter-finals")
    norm = norm.replace("semifinals", "semi-finals")
    return norm.strip()


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


def fetch_openfootball_matches() -> tuple[dict[str, list[dict]], dict[str, str]]:
    """Fetch and parse openfootball cl.txt for every contract season.

    The season -> file map is derived from ``contract.SEASONS`` (matching the
    ``{season}/cl.txt`` URL recorded in ``build._provenance_sources``) instead
    of a fixed literal, so widening the contract widens the acquisition.

    Returns
    -------
    (results, exclusions)
        ``results``: dict[season_key, list[match dict]] for every contract
            season whose source file is available and parsable.  Each match
            dict has keys match_id, team_a, team_b, home_score, away_score,
            event_date, round_label, home_ground.
        ``exclusions``: dict[season_key, reason] for every contract season the
            source does not cover (HTTP error) or whose format the parser
            refuses.  These are named loudly, never skipped silently and never
            fabricated.
    """
    results: dict[str, list[dict]] = {}
    exclusions: dict[str, str] = {}

    for season_key in SEASONS:
        season_name = season_key.replace("_", "-")
        dest = os.path.join(_CACHE_DIR, f"{season_name}.txt")
        try:
            if not os.path.isfile(dest):
                _download(_URL_TPL.format(season=season_name), dest)
            results[season_key] = _parse_file(dest, season_key)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            exclusions[season_key] = (
                f"openfootball/champions-league has no {season_name}/cl.txt "
                f"(HTTP {status}); no keyless results source covers this season"
            )
        except UnsupportedFormatError as exc:
            exclusions[season_key] = str(exc)

    return results, exclusions


def _parse_file(path: str, season_key: str) -> list[dict]:
    """Parse a single cl.txt file into a list of normalised match dicts.

    Era-aware: the section scan decides whether the season used the classic
    group-stage knockout numbering (``ROUND_MATCHDAY``) or the 36-team league
    phase (``ROUND_MATCHDAY_LEAGUE``). A section the parser cannot represent
    raises :class:`UnsupportedFormatError` rather than guessing.
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    # Pre-pass: the section markers decide the format era, which selects the
    # knockout matchday map. League/Playoffs sections only exist from 2024/25.
    sections = [
        m.group(1).strip().lower()
        for m in (_SECTION_RE.match(line.rstrip("\n")) for line in lines)
        if m is not None
    ]
    league_era = any(s.startswith(("league", "playoff")) for s in sections)
    ko_map = ROUND_MATCHDAY_LEAGUE if league_era else ROUND_MATCHDAY

    fixtures: list[dict] = []
    current_round: str | None = None
    current_kind: str | None = None       # "group" | "playoff" | "ko"
    current_ko_key: str | None = None
    current_date: str = ""        # YYYY-MM-DD
    current_time: str = "21:00"   # KO time carried forward within a date
    current_year: int = 0
    current_group: str = ""
    group_explicit_md: int | None = None   # "Group, Matchday N" -> N
    group_fix_seq: dict[str, int] = {}     # counted group -> fixtures seen
    playoff_md: int = 0

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

        # Section marker: group / league phase / play-off / knockout round
        sm = _SECTION_RE.match(stripped)
        if sm:
            section_name = sm.group(1).strip()
            section_lower = section_name.lower()

            if section_lower.startswith(("group", "gruppe", "league")):
                # Group stage and league phase both behave as "pools": the
                # matchday comes from an explicit "Matchday N" when present,
                # else from the fixture position within the pool (2 fixtures
                # per matchday).
                current_round = section_name
                current_kind = "group"
                current_group = section_name
                md_m = _MD_IN_SECTION_RE.search(section_name)
                if md_m:
                    group_explicit_md = int(md_m.group(1))
                else:
                    group_explicit_md = None
                    group_fix_seq.setdefault(current_group, 0)
            elif section_lower.startswith("playoff"):
                current_round = section_name
                current_kind = "playoff"
                current_group = ""
                md_m = _MD_IN_SECTION_RE.search(section_name)
                playoff_n = int(md_m.group(1)) if md_m else 1
                playoff_md = ko_map["playoff"] + (playoff_n - 1)
            else:
                current_group = ""
                norm = _normalise_section(section_lower)
                if norm not in ko_map:
                    raise UnsupportedFormatError(season_key, section_name)
                current_round = section_name
                current_kind = "ko"
                current_ko_key = norm
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
        if current_kind == "group":
            if group_explicit_md is not None:
                md_num = group_explicit_md
            else:
                # A pool has exactly 2 fixtures per matchday, so number
                # the matchday from the fixture position within the pool
                # (robust to rounds split across two date lines, e.g. the
                # Rangers-Napoli postponement in 2022/23).
                seq = group_fix_seq[current_group]
                group_fix_seq[current_group] = seq + 1
                md_num = seq // 2 + 1
        elif current_kind == "playoff":
            md_num = playoff_md
        else:
            md_num = ko_map[current_ko_key]

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
    #   Group/league matchdays: sort all fixtures in a matchday by
    #     (date, group_label, home_key) then index 1..N
    #   Play-off / knockout matchdays: index in file order 1..N
    season_matches: list[dict] = []

    group_by_md: dict[int, list[dict]] = {}
    ko_by_md: dict[int, list[dict]] = {}
    for fx in fixtures:
        if fx["group"]:
            group_by_md.setdefault(fx["matchday_num"], []).append(fx)
        else:
            ko_by_md.setdefault(fx["matchday_num"], []).append(fx)

    # Process group/league matchdays (sorted by date, group, home)
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

    # Process play-off / knockout matchdays (index in file order)
    neutral_from = _NEUTRAL_KO.get(season_key)
    qf_md = ko_map["quarter-finals"]
    for md_num in sorted(ko_by_md):
        fxs = ko_by_md[md_num]
        for idx, fx in enumerate(fxs, start=1):
            mid = md_match_id(md_num, idx)
            event_date = f"{fx['date']}T{fx['time']}:00Z"

            # Neutral ground for post-lockdown matches (>= the season's
            # resumption date) from the quarter-finals onward.
            neutral = (
                neutral_from is not None
                and fx["date"] >= neutral_from
                and fx["matchday_num"] >= qf_md
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
