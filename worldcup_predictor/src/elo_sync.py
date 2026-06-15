"""Elo synchronization from eloratings.net.

Provides functions to fetch, parse, validate, and correct Elo ratings against
the canonical eloratings.net data source (World.tsv). Uses direct TSV download
(not HTML parsing) since eloratings.net is a JS-rendered SPA.

The graduated correction approach (D-10 through D-13) handles systematic
differences between our dynamic Elo formula and eloratings.net's formula
without creating audit noise.
"""

import csv
import io
import logging
import time
from datetime import datetime, timezone

import requests

from src import state
from src.constants import (
    ELORATINGS_TSV_URL,
    ELO_BLEND_FACTOR,
    ELO_BLEND_THRESHOLD,
    ELO_DRIFT_TOLERANCE,
    ELO_SYNC_RETRY_BACKOFFS,
    ELO_SYNC_TIMEOUT,
    ELO_STALENESS_WARN_HOURS,
    ELORATINGS_TEAM_CODES,
)

logger = logging.getLogger(__name__)


def fetch_eloratings_tsv(url: str = "") -> str | None:
    """Fetch raw TSV data from eloratings.net.

    Retries up to 3 times with exponential backoff (1s, 2s, 4s) on transient
    network errors. Returns None only after all retries are exhausted.

    Args:
        url: URL for the eloratings.net World Cup TSV. Defaults to
            constants.ELORATINGS_TSV_URL.

    Returns:
        Raw TSV text string on success, or None if all retries failed.
    """
    if not url:
        url = ELORATINGS_TSV_URL
    backoff = list(ELO_SYNC_RETRY_BACKOFFS)

    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=ELO_SYNC_TIMEOUT)
            resp.raise_for_status()
            return resp.text

        except requests.exceptions.Timeout:
            logger.warning(
                "eloratings.net timeout (attempt %d/3)", attempt + 1
            )
            if attempt < 2:
                time.sleep(backoff[attempt])
                continue
            return None

        except requests.exceptions.ConnectionError:
            logger.warning(
                "eloratings.net connection error (attempt %d/3)", attempt + 1
            )
            if attempt < 2:
                time.sleep(backoff[attempt])
                continue
            return None

        except requests.exceptions.HTTPError:
            logger.warning(
                "eloratings.net HTTP error (attempt %d/3)", attempt + 1
            )
            if attempt < 2:
                time.sleep(backoff[attempt])
                continue
            return None

        except requests.exceptions.RequestException:
            logger.warning(
                "eloratings.net request failed (attempt %d/3)", attempt + 1
            )
            if attempt < 2:
                time.sleep(backoff[attempt])
                continue
            return None

    return None


def parse_eloratings_tsv(tsv_raw: str) -> list[tuple[str, float]]:
    """Parse eloratings.net TSV data into (team_code, rating) pairs.

    Extracts column index 2 (team code) and column index 3 (Elo rating) from
    each row. Skips empty rows and rows where the rating is not a valid float.

    Args:
        tsv_raw: Raw TSV text from eloratings.net.

    Returns:
        List of (team_code, elo_rating) tuples parsed from the TSV data.
    """
    result: list[tuple[str, float]] = []
    reader = csv.reader(io.StringIO(tsv_raw), delimiter="\t")

    for row in reader:
        if not row:
            continue
        if len(row) < 4:
            continue
        team_code = row[2].strip()
        if not team_code:
            continue
        try:
            rating = float(row[3])
        except (ValueError, TypeError):
            continue
        result.append((team_code, rating))

    return result


def validate_eloratings_data(
    parsed: list[tuple[str, float]],
) -> tuple[bool, list[str]]:
    """Validate parsed eloratings data for schema compliance per D-08.

    Checks:
    1. At least 48 entries are present.
    2. All ratings are in the range [1000, 2500].
    3. No NaN or None values.

    Does NOT raise — returns a validity flag and list of messages.

    Args:
        parsed: List of (team_code, elo_rating) tuples from
            parse_eloratings_tsv().

    Returns:
        Tuple of (valid: bool, messages: list[str]).
    """
    messages: list[str] = []
    valid = True

    # Check 1: At least 48 entries
    if len(parsed) < 48:
        valid = False
        messages.append(
            f"Expected >= 48 teams, got {len(parsed)}"
        )

    # Check 2 & 3: Ratings in range, no NaN/None
    for code, rating in parsed:
        if rating is None or (isinstance(rating, float) and rating != rating):
            valid = False
            messages.append(
                f"Invalid rating (NaN/None) for {code}"
            )
        elif rating < 1000 or rating > 2500:
            valid = False
            messages.append(
                f"Rating {rating} for {code} out of range [1000, 2500]"
            )

    return valid, messages


def resolve_team_names(
    parsed: list[tuple[str, float]],
    teams: dict[str, dict],
) -> dict[str, float]:
    """Map eloratings.net team codes to canonical project team names.

    Uses constants.ELORATINGS_TEAM_CODES to resolve 2-letter codes to
    canonical names. Only includes teams that exist in the teams dict.
    Logs WARNING for unmapped codes and for code map entries not found
    in the teams dict (indicative of a coverage gap).

    Args:
        parsed: List of (team_code, elo_rating) tuples.
        teams: Dict mapping canonical team name to team data.

    Returns:
        Dict of {canonical_name: elo_rating} for successfully resolved teams.
    """
    mapped: dict[str, float] = {}
    unresolved_codes: int = 0
    unmapped_codes: list[str] = []

    for code, rating in parsed:
        canonical = ELORATINGS_TEAM_CODES.get(code)
        if canonical is None:
            unmapped_codes.append(code)
            unresolved_codes += 1
            continue
        if canonical in teams:
            mapped[canonical] = rating
        else:
            logger.warning(
                "Code map resolved %s -> %s but team not in teams dict",
                code, canonical,
            )

    if unresolved_codes > 0:
        logger.warning(
            "Unmapped eloratings codes (%d): %s",
            unresolved_codes, ", ".join(unmapped_codes),
        )

    return mapped


def apply_graduated_correction(
    teams: dict[str, dict],
    eloratings_values: dict[str, float],
) -> list[dict]:
    """Apply graduated correction thresholds to team Elo ratings per D-11.

    For each team in eloratings_values:
    - |drift| < ELO_DRIFT_TOLERANCE (10): skip — expected noise
    - |drift| <= ELO_BLEND_THRESHOLD (30): blend 50%% toward eloratings value
    - |drift| > ELO_BLEND_THRESHOLD (30): overwrite and flag

    Mutates teams dict in-place. Every correction is logged to the returned
    list per D-12.

    Args:
        teams: Dict of canonical team name -> team data (mutated in-place).
        eloratings_values: Dict of canonical team name -> eloratings.net rating.

    Returns:
        List of correction log entry dicts with keys: timestamp, team,
        old_value, new_value, source, reason, drift_magnitude.
    """
    corrections: list[dict] = []

    for canonical_name, elo_rating in eloratings_values.items():
        if canonical_name not in teams:
            continue

        current_elo = teams[canonical_name]["elo"]
        drift = elo_rating - current_elo
        abs_drift = abs(drift)

        if abs_drift < ELO_DRIFT_TOLERANCE:
            continue  # D-11: Ignore < 10pt drift

        if abs_drift <= ELO_BLEND_THRESHOLD:
            # D-11: Blend 50% toward eloratings value
            new_elo = round(current_elo + drift * ELO_BLEND_FACTOR, 1)
            reason = "blended_50pct"
        else:
            # D-11: Overwrite and flag for investigation
            new_elo = round(elo_rating, 1)
            reason = "overwrite_drift_gt_30"

        corrections.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "team": canonical_name,
            "old_value": current_elo,
            "new_value": new_elo,
            "source": "eloratings.net",
            "reason": reason,
            "drift_magnitude": round(drift, 1),
        })
        teams[canonical_name]["elo"] = new_elo

    return corrections


def sync_elo_from_eloratings(
    teams: dict[str, dict],
) -> list[dict] | None:
    """Full Elo sync pipeline: fetch -> parse -> validate -> resolve -> correct -> persist.

    Orchestrates the complete sync flow:
    1. Fetch raw TSV from eloratings.net
    2. Parse TSV into (code, rating) pairs
    3. Validate parsed data
    4. Resolve team codes to canonical names
    5. Apply graduated corrections
    6. Persist audit trail and cache

    Args:
        teams: Dict mapping canonical team name to team data.
               Mutated in-place by apply_graduated_correction().

    Returns:
        List of correction log entries if drift was found, empty list [] if
        no drift detected, or None if the fetch failed (caller handles cache
        fallback per D-15/D-19/D-20).
    """
    tsv_raw = fetch_eloratings_tsv()
    if tsv_raw is None:
        logger.warning("eloratings.net fetch failed — skipped")
        return None

    parsed = parse_eloratings_tsv(tsv_raw)

    valid, messages = validate_eloratings_data(parsed)
    if not valid:
        for msg in messages:
            logger.warning("Validation: %s", msg)
        # Continue with partial data per D-21

    eloratings_values = resolve_team_names(parsed, teams)

    corrections = apply_graduated_correction(teams, eloratings_values)

    # Persist audit trail (D-12)
    log = state.load_elo_update_log()
    log.extend(corrections)
    state.save_elo_update_log(log)

    # Persist cache (D-14)
    state.save_eloratings_cache({
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "values": eloratings_values,
    })

    # Persist updated Elo values if corrections were applied
    if corrections:
        state.save_teams(teams)

    logger.info("Sync complete: %d corrections applied", len(corrections))

    # Log count of unresolved codes
    unresolved = len(parsed) - len(eloratings_values)
    if unresolved > 0:
        logger.warning(
            "Sync: %d team codes unresolved (not in 48-team mapping)",
            unresolved,
        )

    return corrections


def get_staleness_level(hours_since_sync: float) -> tuple[int, str]:
    """Determine staleness warning level based on hours since last sync per D-16.

    Staleness thresholds from constants.ELO_STALENESS_WARN_HOURS:
    - Level 0: hours < 24  -> "green"
    - Level 1: hours < 48  -> "info"
    - Level 2: hours < 72  -> "yellow"
    - Level 3: hours < 168 -> "red"
    - Level 4: hours >= 168 -> "critical"

    Args:
        hours_since_sync: Hours elapsed since the last successful sync.

    Returns:
        Tuple of (level_index: int, label: str).
    """
    thresholds: tuple[int, ...] = ELO_STALENESS_WARN_HOURS

    for level, threshold in enumerate(thresholds):
        if hours_since_sync <= threshold:
            labels = ("green", "info", "yellow", "red")
            return level, labels[level]

    return len(thresholds), "critical"
