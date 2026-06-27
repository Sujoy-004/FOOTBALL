"""Generic Elo synchronization pipeline: fetch, parse, validate, correct, persist."""

import csv
import io
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from football_core import constants

logger = logging.getLogger(__name__)


def fetch_eloratings_tsv(url: str = "") -> str | None:
    if not url:
        url = constants.ELORATINGS_TSV_URL
    backoff = list(constants.ELO_SYNC_RETRY_BACKOFFS)

    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=constants.ELO_SYNC_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.Timeout:
            logger.warning("eloratings.net timeout (attempt %d/3)", attempt + 1)
            if attempt < 2:
                time.sleep(backoff[attempt])
                continue
            return None
        except requests.exceptions.ConnectionError:
            logger.warning("eloratings.net connection error (attempt %d/3)", attempt + 1)
            if attempt < 2:
                time.sleep(backoff[attempt])
                continue
            return None
        except requests.exceptions.HTTPError:
            logger.warning("eloratings.net HTTP error (attempt %d/3)", attempt + 1)
            if attempt < 2:
                time.sleep(backoff[attempt])
                continue
            return None
        except requests.exceptions.RequestException:
            logger.warning("eloratings.net request failed (attempt %d/3)", attempt + 1)
            if attempt < 2:
                time.sleep(backoff[attempt])
                continue
            return None
    return None


def parse_eloratings_tsv(tsv_raw: str) -> list[tuple[str, float]]:
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
    messages: list[str] = []
    valid = True
    if len(parsed) < 48:
        valid = False
        messages.append(f"Expected >= 48 teams, got {len(parsed)}")
    for code, rating in parsed:
        if rating is None or (isinstance(rating, float) and rating != rating):
            valid = False
            messages.append(f"Invalid rating (NaN/None) for {code}")
        elif rating < 1000 or rating > 2500:
            valid = False
            messages.append(f"Rating {rating} for {code} out of range [1000, 2500]")
    return valid, messages


def apply_graduated_correction(
    teams: dict[str, dict],
    eloratings_values: dict[str, float],
) -> list[dict]:
    corrections: list[dict] = []
    for canonical_name, elo_rating in eloratings_values.items():
        if canonical_name not in teams:
            continue
        current_elo = teams[canonical_name]["elo"]
        drift = elo_rating - current_elo
        abs_drift = abs(drift)
        if abs_drift < constants.ELO_DRIFT_TOLERANCE:
            continue
        if abs_drift <= constants.ELO_BLEND_THRESHOLD:
            new_elo = round(current_elo + drift * constants.ELO_BLEND_FACTOR, 1)
            reason = "blended_50pct"
        else:
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


def get_staleness_level(hours_since_sync: float) -> tuple[int, str]:
    thresholds: tuple[int, ...] = constants.ELO_STALENESS_WARN_HOURS
    for level, threshold in enumerate(thresholds):
        if hours_since_sync <= threshold:
            labels = ("green", "info", "yellow", "red")
            return level, labels[level]
    return len(thresholds), "critical"
