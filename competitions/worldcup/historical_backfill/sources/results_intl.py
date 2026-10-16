"""Openfootball world-cup adapter for the historical World Cup backfill.

Downloads the per-tournament football.db text fixtures from the openfootball
world-cup repository (one ``cup.txt`` group-stage file + one
``cup_finals.txt`` knockout file per tournament), parses them, and returns
canonical-keyed match dicts matching the build.py contract.

The adapter is *window-generic*: the tournament list comes from
``contract.SEASONS`` / ``contract.TOURNEY_DIRS`` and the parser understands
every format era the source actually publishes in-window:

- 2002: inline ``<day> <month>`` date, no time (``31 May   France  0-1  Senegal  @ ...``)
- 2006: inline ``<weekday> <mon> <day>`` date, no time (``Sat Jun 24  Germany  2-0 (2-0)  Sweden  @ ...``);
  a leading shootout score can precede the level score (``Switzerland  0-3 pen. 0-0 a.e.t. (0-0)  Ukraine``)
- 2010: inline date + local kickoff time without a UTC offset
- 2014: standalone date line + ``<time> UTC<off>  Home v Away  H-A (HT)  @ venue`` (the ``v`` separator era)
- 2018: standalone date line + ``<time> UTC<off>  Home  H-A (HT)  @ venue``
- 2022: standalone date line + local kickoff time without a UTC offset
- 2026: standalone date line + ``(<matchno>) <time> UTC<off>  Home  H-A (HT)  @ venue  ## bracket comment``;
  48-team format (12 groups, round of 32)

A tournament the source does not serve returns ``None`` (excluded-and-reported
by the build, never fabricated). A tournament that is present but whose
format the parser cannot represent raises :class:`TournamentFormatError`
naming the tournament and the offending line — the build never guesses.

Kickoff times: eras that publish a UTC offset (2014, 2018, 2026) are
converted to UTC; eras that publish no time (2002, 2006) or a local time
without an offset (2010, 2022) use the documented ``21:00:00Z`` default —
the day-level chronology (the only thing the D-02 splitter and the
rolling-form/rest-days signals consume) is unaffected. Recorded in
``PROVENANCE.json``.

Source: https://github.com/openfootball/world-cup (CC0-1.0, public domain).
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import tempfile

import requests

from football_core.historical_backfill import TeamKeys

from competitions.worldcup.historical_backfill.contract import (
    SEASONS,
    TOURNEY_DIRS,
)

_BASE_URL = "https://raw.githubusercontent.com/openfootball/world-cup/master"
_CACHE_DIR = os.path.join(tempfile.gettempdir(), "opencode")

_DEFAULT_KICKOFF = "21:00"  # documented default for eras without a published time


class TournamentFormatError(Exception):
    """The tournament file exists but its format cannot be parsed honestly."""

    def __init__(self, season: str, line: str, reason: str) -> None:
        super().__init__(
            f"World Cup {season}: cannot parse line ({reason}): {line!r}"
        )
        self.season = season
        self.line = line
        self.reason = reason


_MONTHS: dict[str, int] = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_RE = "|".join(
    sorted(_MONTHS, key=len, reverse=True)
)  # longest first: "June" before "Jun"
_WEEKDAY_RE = r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)"

# Leading prefix: optional 2026 match number, optional weekday, the date
# (day-first or month-first — absent when a standalone date line precedes the
# fixture), optional kickoff time, optional UTC offset.
# IGNORECASE: sources capitalise month names ("31 May", "Thu Jun 12").
_PREFIX_RE = re.compile(
    rf"^(?:\(\d+\)\s*)?"
    rf"(?:{_WEEKDAY_RE}\s+)?"
    rf"(?:(?P<d>\d{{1,2}})\s+(?P<m>{_MONTH_RE})"
    rf"|(?P<m2>{_MONTH_RE})\s+(?P<d2>\d{{1,2}}))?"
    rf"\s*"
    rf"(?:(?P<time>\d{{1,2}}:\d{{2}})\s*)?"
    rf"(?:(?P<off>UTC[+-]\d{{1,2}})\s*)?",
    re.IGNORECASE,
)

# Standalone date line: "Thu Jun 12" / "Thu June 11" / "Sun Nov 20".
_DATE_LINE_RE = re.compile(
    rf"^{_WEEKDAY_RE}\s+(?P<m>{_MONTH_RE})\s+(?P<d>\d{{1,2}})$",
    re.IGNORECASE,
)

_SECTION_RE = re.compile(r"^▪\s*(?P<text>.+?)\s*$")
_SCORE_RE = re.compile(r"(?P<hs>\d+)-(?P<as>\d+)")
_PEN_PRE_RE = re.compile(
    r"^(?P<home>.+?)\s+(?P<ph>\d+)-(?P<pa>\d+)\s+pen\.\s+(?P<after>.*)$"
)

# Normalized knockout round labels (must stay in sync with the KO_ROUNDS set
# in competitions/worldcup/src/historical.py).
_KO_NORMALIZATION = {
    "round of 16": "round of 16",
    "round of 32": "round of 32",
    "quarter-finals": "quarter-final",
    "semi-finals": "semi-final",
    "final": "final",
    "third place play-off": "third place",
    "match for third place": "third place",
}

# Historical national teams absent from the 2026 production aliases file:
# each becomes its own canonical key (identity).
_HISTORICAL_EXTRA_CANONICAL: tuple[str, ...] = (
    "Angola", "Cameroon", "Chile", "China", "Costa Rica", "Denmark",
    "Greece", "Honduras", "Iceland", "Ireland", "Italy", "Nigeria",
    "North Korea", "Peru", "Poland", "Russia", "Serbia",
    "Serbia and Montenegro", "Slovakia", "Slovenia", "Togo",
    "Trinidad and Tobago", "Ukraine", "Wales",
)

# openfootball spellings that are not aliases but map to an existing
# canonical key (2014 uses the hyphenated form; 2026 uses the ampersand).
_CURATED: dict[str, str] = {
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
}

_ALIASES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "team_aliases.json",
)

TEAM_KEYS = TeamKeys(
    _ALIASES_FILE, _CURATED, added_canonical_keys=_HISTORICAL_EXTRA_CANONICAL
)


def _download(url: str, dest: str) -> str:
    """Download *url* to *dest* if not already present (atomic write)."""
    if os.path.isfile(dest):
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with requests.get(url, timeout=60, allow_redirects=True) as resp:
        resp.raise_for_status()
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            f.write(resp.content)
    os.replace(tmp, dest)
    return dest


def _norm_round(section_text: str) -> str:
    """Normalise a section header to a round label (or 'group')."""
    t = section_text.lower()
    if t.startswith("group"):
        return "group"
    if t in _KO_NORMALIZATION:
        return _KO_NORMALIZATION[t]
    return t


def _event_date(year: int, date_str: str, time_str: str, offset_str: str) -> str:
    """Build an ISO-8601 UTC event_date from the parsed date/time/offset.

    A published UTC offset is converted (including date rollover). No
    offset (or no time) uses the documented 21:00 default on the source
    date — the day-level chronology is unaffected.
    """
    if offset_str:
        sign = 1 if offset_str[3] == "+" else -1
        hours = int(offset_str[4:])
        local = _dt.datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        utc = local - sign * _dt.timedelta(hours=hours)
        return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"{date_str}T{_DEFAULT_KICKOFF}:00Z"


def _parse_match_line(
    line: str, season: str, current_date: str | None, current_round: str | None
) -> dict | None:
    """Parse one fixture line into a normalized match dict (or None)."""
    if not current_round:
        return None
    m = _PREFIX_RE.match(line)
    rest = line[m.end():] if m else line
    # Effective date: the standalone date line when present (2014+), else
    # the inline prefix date (2002/2006 embed it in the fixture line).
    date_str = current_date
    if date_str is None and m:
        if m.group("d") and m.group("m"):
            month = _MONTHS[m.group("m").lower()]
            date_str = f"{int(season)}-{month:02d}-{int(m.group('d')):02d}"
        elif m.group("d2") and m.group("m2"):
            month = _MONTHS[m.group("m2").lower()]
            date_str = f"{int(season)}-{month:02d}-{int(m.group('d2')):02d}"
    if not date_str:
        return None

    # Optional leading shootout score (2006 era): "0-3 pen. 0-0 a.e.t. ..."
    # The pen regex captures the home team, so the score then starts the
    # remaining text.
    pen_pre: tuple[int, int] | None = None
    home: str | None = None
    mp = _PEN_PRE_RE.match(rest)
    if mp and _SCORE_RE.search(mp.group("after")):
        pen_pre = (int(mp.group("ph")), int(mp.group("pa")))
        home = mp.group("home").strip()
        rest = mp.group("after")

    ms = _SCORE_RE.search(rest)
    if ms is None:
        raise TournamentFormatError(season, line, "no H-A score found")
    home_part = rest[: ms.start()].strip()
    post = rest[ms.end():]
    home_score, away_score = int(ms.group("hs")), int(ms.group("as"))

    # 2014 era: "Home v Away  H-A" — the score follows both teams.
    away: str | None = None
    if home is None:
        if " v " in home_part:
            home, away = (p.strip() for p in home_part.rsplit(" v ", 1))
            post = post.strip()
        else:
            home = home_part

    # Strip result annotations from the trailing part: "a.e.t.", the HT
    # score "(1-1)" / "(1-1, 1-1)" and a trailing ", 3-2 pen.".
    post = re.sub(r"^\s*a\.e\.t\.?\s*", "", post)
    post = re.sub(r"^\s*\([^)]*\)\s*", "", post)
    pen_trail: tuple[int, int] | None = None
    mpen = re.match(r"^,\s*(?P<th>\d+)-(?P<ta>\d+)\s*pen\.\s*", post)
    if mpen:
        pen_trail = (int(mpen.group("th")), int(mpen.group("ta")))
        post = post[mpen.end():]
    post = post.strip()

    if away is None:
        # Standard layout: away team is the text before the venue/comment.
        maway = re.match(r"^(?P<away>.*?)(?:\s+@\s+(?P<venue>.*?))?(?:\s+#.*)?$", post)
        away = (maway.group("away") or "").strip() if maway else ""
    if not home or not away:
        raise TournamentFormatError(
            season, line, f"unparsable home/away (home={home!r}, away={away!r})"
        )

    try:
        team_a = TEAM_KEYS.canonical(home)
        team_b = TEAM_KEYS.canonical(away)
    except KeyError as exc:
        raise TournamentFormatError(
            season, line, f"unmapped team name: {exc}"
        ) from exc

    knockout = current_round != "group"
    match: dict = {
        "team_a": team_a,
        "team_b": team_b,
        "home_score": home_score,
        "away_score": away_score,
        "event_date": None,  # filled below
        "round": current_round,
        "winner": None,
        "pk_winner": None,
        "stage": "knockout" if knockout else "group",
    }
    if m and m.group("time"):
        match["event_date"] = _event_date(
            int(season), date_str, m.group("time"), m.group("off")
        )
    else:
        match["event_date"] = _event_date(int(season), date_str, "", None)

    if knockout:
        if home_score > away_score:
            match["winner"] = team_a
        elif away_score > home_score:
            match["winner"] = team_b
        else:
            # Level after extra time: the shootout decides (openfootball
            # lists the shootout home-pens-away-pens; the first-listed team
            # is the shootout winner when the numbers favour it).
            pens = pen_pre or pen_trail
            if pens is not None:
                home_pens, away_pens = pens
                match["pk_winner"] = team_a if home_pens > away_pens else team_b
            # No recorded shootout winner: winner stays None (never a
            # fabricated draw; outcome_index returns None for the label).
    return match


def _parse_file(path: str, season: str) -> list[dict]:
    """Parse one cup.txt / cup_finals.txt into normalized match dicts."""
    year = int(season)
    matches: list[dict] = []
    current_date: str | None = None
    current_round: str | None = None

    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            s = line.strip()
            if not s or s.startswith(("=", "#", "Group", "|", "####")):
                continue
            sec = _SECTION_RE.match(s)
            if sec:
                text = sec.group("text")
                if "|" in text:
                    continue  # metadata overview line (matchday ranges)
                current_round = _norm_round(text)
                continue
            dm = _DATE_LINE_RE.match(s)
            if dm:
                month = _MONTHS[dm.group("m").lower()]
                day = int(dm.group("d"))
                current_date = f"{year}-{month:02d}-{day:02d}"
                continue
            # A fixture line carries a score AND a venue marker; scorer
            # continuation lines and metadata never have both.
            if not (_SCORE_RE.search(s) and "@" in s):
                continue
            match = _parse_match_line(s, season, current_date, current_round)
            if match is not None:
                matches.append(match)
    return matches


def fetch(season: str) -> list[dict] | None:
    """Fetch normalized match dicts for one World Cup tournament.

    Returns ``None`` when the tournament is absent from the source (the
    build excludes-and-reports it). Raises :class:`TournamentFormatError`
    when the tournament is present but a fixture line cannot be parsed.
    """
    if season not in SEASONS:
        raise ValueError(f"unknown season: {season!r}")
    slug = TOURNEY_DIRS[season]
    cup_path = _download(
        f"{_BASE_URL}/{slug}/cup.txt",
        os.path.join(_CACHE_DIR, f"wc_{season}_cup.txt"),
    )
    finals_path = _download(
        f"{_BASE_URL}/{slug}/cup_finals.txt",
        os.path.join(_CACHE_DIR, f"wc_{season}_cup_finals.txt"),
    )

    group_matches = _parse_file(cup_path, season)
    if not group_matches:
        raise TournamentFormatError(
            season, "(cup.txt)", "no group-stage matches parsed"
        )
    ko_matches = _parse_file(finals_path, season)
    if not ko_matches:
        raise TournamentFormatError(
            season, "(cup_finals.txt)", "no knockout matches parsed"
        )
    print(f"{season}: {len(group_matches)} group + {len(ko_matches)} knockout matches")
    return group_matches + ko_matches


if __name__ == "__main__":
    for s in SEASONS:
        result = fetch(s)
        print(f"{s}: {'absent' if result is None else len(result)} matches")
