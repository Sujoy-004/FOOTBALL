"""Elo synchronization — extends football_core with WC team code mapping."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from football_core.elo_sync import (
    fetch_eloratings_tsv,
    parse_eloratings_tsv,
    validate_eloratings_data,
    apply_graduated_correction,
    get_staleness_level,
)

from src import state
from src.constants import ELORATINGS_TEAM_CODES, ELORATINGS_TSV_URL

logger = logging.getLogger(__name__)


def resolve_team_names(
    parsed: list[tuple[str, float]],
    teams: dict[str, dict],
) -> dict[str, float]:
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


def sync_elo_from_eloratings(
    teams: dict[str, dict],
    data_dir: Path | str | None = None,
    url: str = "",
) -> list[dict] | None:
    tsv_raw = fetch_eloratings_tsv(url=url)
    if tsv_raw is None:
        logger.warning("eloratings.net fetch failed — skipped")
        return None

    parsed = parse_eloratings_tsv(tsv_raw)

    valid, messages = validate_eloratings_data(parsed)
    if not valid:
        for msg in messages:
            logger.warning("Validation: %s", msg)

    eloratings_values = resolve_team_names(parsed, teams)

    corrections = apply_graduated_correction(teams, eloratings_values)

    log = state.load_elo_update_log(data_dir)
    log.extend(corrections)
    state.save_elo_update_log(log, data_dir)

    state.save_eloratings_cache({
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "values": eloratings_values,
    }, data_dir)

    if corrections:
        state.save_teams(teams, data_dir)

    logger.info("Sync complete: %d corrections applied", len(corrections))

    unresolved = len(parsed) - len(eloratings_values)
    if unresolved > 0:
        logger.warning(
            "Sync: %d team codes unresolved (not in %d-team mapping)",
            unresolved, len(ELORATINGS_TEAM_CODES),
        )

    return corrections
