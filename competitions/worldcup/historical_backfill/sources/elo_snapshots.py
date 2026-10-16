"""National-team Elo snapshots for the historical World Cup backfill.

A4 (verified 2026-10-15): no date-indexed historical national-team Elo feed
exists. eloratings.net serves ONLY the current ratings TSV
(``football_core.constants.ELORATINGS_TSV_URL``); date-indexed URL patterns
return HTTP 404. Using the current TSV as a per-tournament snapshot would leak
up to 24 years of subsequent results into every 2002-2022 match prediction —
a synthetic rating, forbidden by D-03/D-04.

Honest design: every tournament snapshot is returned EMPTY and the coverage
gap is recorded in PROVENANCE.json. The build does not block on Elo;
``available_signals`` reports ``refined_elo`` as
``insufficient_data:no_elo_ratings`` and the WC evaluation proceeds without
the Elo signal (the 4-signal surrogate, D-17a).
"""

from __future__ import annotations

import requests

from football_core.elo_sync import parse_eloratings_tsv

from competitions.worldcup.historical_backfill.contract import SEASONS

ELORATINGS_DATE_URL_TPL = "https://www.eloratings.net/{date}.tsv"


def probe_date_indexed_feed(date: str = "2002-06-01") -> bool:
    """Probe eloratings.net for a date-indexed TSV (expected: unavailable)."""
    try:
        resp = requests.get(
            ELORATINGS_DATE_URL_TPL.format(date=date), timeout=10
        )
        return resp.status_code == 200 and len(resp.text) > 0
    except requests.RequestException:
        return False


def fetch_elo_snapshots() -> dict[str, dict[str, float]]:
    """Per-tournament national-team Elo snapshots (empty: no historical feed).

    Attempts a date-indexed feed; on the verified-absent path returns one
    empty snapshot per tournament so the coverage gap is recorded, never
    fabricated.
    """
    if probe_date_indexed_feed():
        # Feed exists (not reachable today): fetch per-tournament snapshots.
        # Kept as the sanctioned acquisition path if a feed appears.
        snapshots: dict[str, dict[str, float]] = {}
        for season in SEASONS:
            year = int(season)
            url = ELORATINGS_DATE_URL_TPL.format(date=f"{year}-06-01")
            try:
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                parsed = parse_eloratings_tsv(resp.text)
                # Map eloratings codes to canonical team names via the WC
                # team-code mapping (call-time import: layer-safe).
                from competitions.worldcup.src.constants import ELORATINGS_TEAM_CODES
                snapshots[season] = {
                    ELORATINGS_TEAM_CODES[code]: float(rating)
                    for code, rating in parsed
                    if code in ELORATINGS_TEAM_CODES
                }
            except (requests.RequestException, KeyError):
                snapshots[season] = {}
        return snapshots
    # Verified 2026-10-15: eloratings.net serves only the current TSV.
    # Return empty snapshots per tournament; the gap is recorded in
    # PROVENANCE.json and reported in COVERAGE.md.
    return {season: {} for season in SEASONS}


if __name__ == "__main__":
    data = fetch_elo_snapshots()
    for season, snapshot in data.items():
        print(f"{season}: {len(snapshot)} teams")
