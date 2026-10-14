"""football-data.co.uk SP1 adapter for the historical LaLiga backfill.

Downloads the public football-data.co.uk archive file for each backfill season
(one SP1.csv per season; a verified 20-team double round-robin = 380 matches),
normalizes team keys via ``backfill.team_map.canonical``, and returns match
dicts with results AND closing 1X2 odds from a single authoritative file.

Bookmaker preference follows the UCL convention: Pinnacle closing line first
(PSH/PSD/PSA), falling back to Bet365 (B365H/D/A), then Max (MaxH/MaxD/MaxA),
then Avg (AvgH/AvgD/AvgA). football-data.co.uk does not publish intraday odds
timestamps: the recorded prices are the CLOSING line, finalized at kickoff.
``odds_known_at`` is therefore set to the match ``event_date`` and recorded as
a documented assumption (closing line knowable at kickoff) — no odds are ever
used to predict a fixture.

Entry point matches the build.py contract::

    matches: dict[str, list[dict]] = fetch_football_data_matches()
        # season keyed "2000_01".."2025_26"; each match dict has
        #   team_a, team_b (canonical keys),
        #   home_score (int), away_score (int),
        #   event_date (ISO-8601 UTC, "YYYY-MM-DDTHH:MM:SSZ"),
        #   odds_home, odds_draw, odds_away (float|None),
        #   odds_bookmaker (str|None), odds_known_at (str|None)

Source notes:
- https://www.football-data.co.uk/ is a long-standing, academically-cited
  archive of European league results and betting odds (MIT-style free
  download, courtesy Joseph Buchdahl / football-data). License: free for
  research — see https://www.football-data.co.uk/terms.php.
- ``Date`` is DD/MM/YYYY and ``Time`` is local European (CET/CEST) timezone;
  both are converted to a UTC ISO timestamp so ISO string ordering is the
  true chronological order for leakage-sensitive context construction. Early
  archive seasons (2000/01-2005/06) have no ``Time`` column; those rows use
  00:00 local.
- Unmapped rows raise :class:`KeyError` (data errors are loud).
"""

from __future__ import annotations

import datetime as _dt
import os
import tempfile
from urllib import request as urllib_request

import pandas as pd

from competitions.laliga.historical_backfill.contract import FD_SEASON_URLS, SEASONS
from competitions.laliga.historical_backfill.team_map import canonical

TMP_DIR = os.path.join(tempfile.gettempdir(), "opencode")

# Bookmaker preference order: (home_col, draw_col, away_col, label).
_ODDS_PREFERENCE: tuple[tuple[str, str, str, str], ...] = (
    ("PSH", "PSD", "PSA", "Pinnacle"),
    ("B365H", "B365D", "B365A", "Bet365"),
    ("MaxH", "MaxD", "MaxA", "Max"),
    ("AvgH", "AvgD", "AvgA", "Avg"),
)


def _download(url: str, path: str) -> str:
    """Download *url* to *path* if not already present (atomic write)."""
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with urllib_request.urlopen(url, timeout=60) as resp:
        data = resp.read()
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return path


def read_sp1(path: str) -> pd.DataFrame:
    """Read a football-data.co.uk SP1 CSV, tolerating its ragged rows.

    The early archive files (2000/01-2004/05 in particular) mix row widths: the
    header names N columns while data rows carry a variable number of trailing
    empty/odds fields (football-data.co.uk appends closing-odds columns over
    the years without rewriting the older rows). The default pandas C parser
    rejects such a file (rows *wider* than the header). Rather than drop or
    pad-with-loss, every data line is split to the header's own column count —
    the excess is trailing and the leading columns (results, team names, odds)
    are always aligned — and short rows are padded. No match is ever dropped.

    Empty fields (whether from a short row or an absent value such as a season
    with no closing odds for a match) are normalized to ``None`` so downstream
    consumers see the same "missing" semantics as pandas' default reader would
    give (``pd.notna`` is ``False``) — never a falsy-but-present ``""`` that
    would break a numeric cast. Python's ``list`` has no NaN, so the padding
    value here is ``None``; ``pd.DataFrame`` preserves it in the object-typed
    columns this file produces.

    Returns a :class:`pandas.DataFrame` named by the file's own header row.
    """
    with open(path, encoding="latin-1") as f:
        lines = [line for line in f.read().splitlines() if line.strip()]
    if not lines:
        raise ValueError(f"{path}: empty SP1 file")
    header = lines[0].split(",")
    width = len(header)
    rows = []
    for line in lines[1:]:
        fields = line.split(",")[:width]
        fields = [None if v == "" else v for v in fields]
        if len(fields) < width:
            fields += [None] * (width - len(fields))
        rows.append(fields)
    return pd.DataFrame(rows, columns=header)


def parse_sp1_date(raw: object) -> _dt.date:
    """Parse a football-data.co.uk ``Date`` cell, accepting 4- or 2-digit years.

    The archive uses ``DD/MM/YYYY`` from 2018/19 onward and ``DD/MM/YY`` for
    every earlier season. ``strptime`` with ``%y`` resolves ``00``-``68`` to
    ``2000``-``2068``, which is exactly right for the D-01 window
    (2000/01-2025/26); no other two-digit window can appear here.
    """
    text = str(raw).strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return _dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised SP1 date: {text!r}")


def _parse_event_date(date_str: str, time_str: str) -> str:
    """Convert football-data local Date+Time to a UTC ISO timestamp.

    football-data dates are DD/MM/YYYY (2018/19+) or DD/MM/YY (older) and times
    are local European (CET/CEST). Seasons before 2019/20 carry no ``Time``
    column, so those rows use local 00:00. DST is resolved by interpreting the
    naive local time in the Europe/Madrid zone and converting to UTC, so ISO
    string ordering is the true chronological order for leakage-sensitive
    context construction.
    """
    d = parse_sp1_date(date_str)
    t_str = str(time_str).strip() if pd.notna(time_str) else "00:00"
    t = _dt.datetime.strptime(t_str, "%H:%M").time()
    local = _dt.datetime.combine(d, t)
    # Europe/Madrid goes on/off DST; zoneinfo resolves it per-date.
    try:
        from zoneinfo import ZoneInfo
        madrid = local.replace(tzinfo=ZoneInfo("Europe/Madrid"))
        utc = madrid.astimezone(_dt.timezone.utc).replace(tzinfo=None)
    except Exception:  # pragma: no cover - zoneinfo rare in odd environments
        utc = local
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_match(row: pd.Series) -> dict:
    team_a = canonical(str(row["HomeTeam"]).strip())
    team_b = canonical(str(row["AwayTeam"]).strip())
    home_score = int(row["FTHG"])
    away_score = int(row["FTAG"])

    odds: tuple[float | None, float | None, float | None, str | None]
    odds = (None, None, None, None)
    for h, d, a, label in _ODDS_PREFERENCE:
        vals = (row.get(h), row.get(d), row.get(a))
        if all(pd.notna(v) and float(v) > 0 for v in vals):
            odds = (float(vals[0]), float(vals[1]), float(vals[2]), label)
            break

    match: dict = {
        "team_a": team_a,
        "team_b": team_b,
        "home_score": home_score,
        "away_score": away_score,
        "event_date": _parse_event_date(row["Date"], row.get("Time")),
    }
    if odds[3] is not None:
        match["odds_home"] = odds[0]
        match["odds_draw"] = odds[1]
        match["odds_away"] = odds[2]
        match["odds_bookmaker"] = odds[3]
        match["odds_known_at"] = match["event_date"]
    return match


def fetch_football_data_matches() -> dict[str, list[dict]]:
    """Fetch normalized match dicts for every backfill season (results + odds)."""
    out: dict[str, list[dict]] = {}
    for season, url in FD_SEASON_URLS.items():
        path = _download(url, os.path.join(TMP_DIR, f"SP1_{season}.csv"))
        df = read_sp1(path)
        missing = {"HomeTeam", "AwayTeam", "FTHG", "FTAG", "Date"}.difference(df.columns)
        if missing:
            raise ValueError(f"{season}: missing columns {sorted(missing)}")
        matches = [_build_match(row) for _, row in df.iterrows()]
        if not matches:
            raise ValueError(
                f"{season}: 0 rows parsed from {url} — refusing to pad a "
                "missing season (silent padding is forbidden)"
            )
        out[season] = matches
        print(f"{season}: {len(matches)} matches, {SEASONS[season]}")
        if len(matches) != 380:
            print(
                f"WARNING {season}: {len(matches)} rows (expected 380 for a "
                "20-team double round-robin) — check the source file"
            )
    return out


if __name__ == "__main__":
    data = fetch_football_data_matches()
    for season, matches in data.items():
        n_odds = sum(1 for m in matches if m.get("odds_bookmaker") is not None)
        print(
            f"{season}: len={len(matches)} odds_covered={n_odds} "
            f"({round(100 * n_odds / len(matches), 1)}%)"
        )