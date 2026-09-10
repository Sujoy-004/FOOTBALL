"""ClubElo snapshot adapter for the historical UCL backfill.

Downloads the MIT-licensed ClubElo archive mirror
(https://github.com/xgabora/Club-Football-Match-Data) and the openfootball
per-season fixture files, then computes for every backfill season a
``canonical team key -> elo`` snapshot taken on the latest date STRICTLY
before that season's first match (guarantees pre-match, leakage-free ratings
for every match of the season).

Entry point matches the build.py contract::

    elo: dict[str, dict[str, float]] = fetch_elo_snapshots()
        # season keyed "2019_20".."2023_24"; each mapping is
        # canonical team key -> ClubElo strength before the season's first
        # match.

Source notes:
- ClubElo is live at api.clubelo.com (unreachable from this environment);
  this adapter uses the xgabora mirror of the ClubElo archive (MIT license),
  which mirrors the historical daily ratings 1:1.
- The first match date is taken from the ``# Date`` header of each
  openfootball ``cl.txt`` (its range start is the first actual kickoff; the
  first standalone date line inside the file can be a day later, which would
  leak ratings from the earlier day's matches).
- Clubs that do not resolve to a canonical key are logged, not raised: the
  archive contains thousands of non-CL clubs worldwide. Only teams that are
  actually used by the fixtures are trimmed/validated by build.py.
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import date
from typing import Dict

import pandas as pd
import requests

from competitions.ucl.historical_backfill.contract import SEASONS
from competitions.ucl.historical_backfill.team_map import canonical

TMP_DIR = os.path.join(tempfile.gettempdir(), "opencode")
ELO_CSV = os.path.join(TMP_DIR, "EloRatings.csv")
ELO_URL = (
    "https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data/"
    "master/data/EloRatings.csv"
)
CL_URL = (
    "https://raw.githubusercontent.com/openfootball/champions-league/"
    "master/{season}/cl.txt"
)

_MONTHS: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# "Tue Sep 17 2019 - Sun Aug 23 2020 (341d)"  ->  range start.
_HEADER_DATE_RE = re.compile(
    r"#\s*Date\s+([A-Za-z]{3})\s+([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})"
)
# Standalone fixture date lines: "  Wed Sep 18 2019".
_LINE_DATE_RE = re.compile(
    r"^\s*([A-Za-z]{3})\s+([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})\s*$",
    re.MULTILINE,
)

# Module-level log filled by the last fetch_elo_snapshots() call.
unresolved_clubs: list[str] = []


def _download(url: str, path: str) -> str:
    """Download *url* to *path* if not already present (streamed, atomic)."""
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with requests.get(url, timeout=600, stream=True) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
    os.replace(tmp, path)
    return path


def _to_date(m: re.Match) -> date:
    _, mon, day, yr = m.groups()
    return date(int(yr), _MONTHS[mon.lower()], int(day))


def _first_match_date(season: str) -> date:
    """First actual match date for a season, from its cl.txt header/date lines."""
    url = CL_URL.format(season=season.replace("_", "-"))
    text = requests.get(url, timeout=300).text

    match = _HEADER_DATE_RE.search(text)
    if match is not None:
        return _to_date(match)

    match = _LINE_DATE_RE.search(text)
    if match is not None:
        return _to_date(match)

    raise RuntimeError(f"no first-match date found in {url}")


def _load_elo_frame(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"club": str}, parse_dates=["date"])
    df["date"] = df["date"].dt.normalize()
    df = df.dropna(subset=["club", "elo"])
    df["club"] = df["club"].astype(str).str.strip()
    df["elo"] = df["elo"].astype(float)
    return df


def fetch_elo_snapshots() -> Dict[str, Dict[str, float]]:
    global unresolved_clubs
    csv_path = _download(ELO_URL, ELO_CSV)
    frame = _load_elo_frame(csv_path)
    all_dates = frame["date"].unique()
    unresolved_clubs = []

    print(
        "season     first_match  snapshot      n_clubs  n_mapped  n_unresolved"
    )
    def _resolve(club: str) -> str | None:
        try:
            return canonical(club)
        except KeyError:
            return None

    snapshots: Dict[str, Dict[str, float]] = {}
    for season in SEASONS:
        first_match = _first_match_date(season)
        first_ts = pd.Timestamp(first_match)
        prior = all_dates[all_dates < first_ts]
        if prior.size == 0:
            raise RuntimeError(
                f"{season}: no ClubElo date strictly before {first_match}"
            )
        snapshot_ts = pd.Timestamp(prior.max())
        snapshot_date = snapshot_ts.date()

        rows = frame[frame["date"] == snapshot_ts]
        per_club = rows[["club", "elo"]].drop_duplicates(subset="club")
        per_club["key"] = per_club["club"].map(_resolve)

        unresolved = set(per_club.loc[per_club["key"].isna(), "club"])
        resolved = per_club.dropna(subset=["key"])
        mapped = dict(
            resolved.drop_duplicates(subset="key", keep="first")[["key", "elo"]].to_numpy()
        )

        n_clubs = int(per_club["club"].nunique())
        n_unresolved = len(unresolved)
        n_mapped = n_clubs - n_unresolved
        unresolved_clubs.extend(sorted(unresolved))
        snapshots[season] = {k: float(v) for k, v in mapped.items()}

        print(
            f"{season:<10} {first_match.isoformat()}  {snapshot_date.isoformat()}  "
            f"{n_clubs:>7d}  {n_mapped:>7d}  {n_unresolved:>11d}"
        )
        print(f"    -> {len(mapped)} canonical teams in snapshot")

    unresolved_clubs = sorted(set(unresolved_clubs))
    return snapshots


if __name__ == "__main__":
    data = fetch_elo_snapshots()
    print()
    print("unresolved clubs:", ", ".join(unresolved_clubs))