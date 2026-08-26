"""Fetch and process live match results from BSD API — generic pipeline."""

import logging
from dataclasses import dataclass, field

from football_core.data_providers.bsd_provider import BSDDataProvider

logger = logging.getLogger(__name__)


def new_ingestion_stats() -> dict:
    """Create a zeroed result-ingestion stats dict (truth-ingestion contract).

    Invariant: finished_received == normalized + skipped_unmatchable + skipped_no_target
    (ingested ⊆ normalized). Any finished match that is not ingested must appear
    in exactly one skipped_* bucket and be logged at WARNING level.
    """
    return {
        "finished_received": 0,
        "normalized": 0,
        "ingested": 0,
        "skipped_unmatchable": 0,
        "skipped_no_target": 0,
    }


def count_finished(stats: dict) -> None:
    stats["finished_received"] += 1


def note_unmatchable(stats: dict, log: logging.Logger,
                     home_name: str, away_name: str, score=None) -> None:
    """A FINISHED result could not be matched to known teams — surface loudly."""
    stats["skipped_unmatchable"] += 1
    score_str = f" {score}" if score else ""
    log.warning(
        "RESULT INGESTION SKIP (unmatchable team names): %r vs %r%s "
        "— this finished match will be simulated unless re-ingested",
        home_name, away_name, score_str,
    )


def note_no_target(stats: dict, log: logging.Logger,
                   home_norm: str, away_norm: str) -> None:
    stats["skipped_no_target"] += 1
    log.warning(
        "RESULT INGESTION SKIP (no matching fixture/slot): %r vs %r",
        home_norm, away_norm,
    )


def summarize_ingestion(stats: dict, log: logging.Logger, context: str) -> None:
    """Log the ingestion invariant summary; WARN when finished results were lost."""
    lost = stats["skipped_unmatchable"] + stats["skipped_no_target"]
    log.log(
        logging.WARNING if lost else logging.INFO,
        "Ingestion summary [%s]: finished=%d normalized=%d ingested=%d "
        "skipped_unmatchable=%d skipped_no_target=%d",
        context, stats["finished_received"], stats["normalized"],
        stats["ingested"], stats["skipped_unmatchable"], stats["skipped_no_target"],
    )


def fetch_raw_matches(api_key: str, api_url: str, league_id: int, timeout: int = 10) -> list[dict]:
    """Thin wrapper — delegates to :class:`BSDDataProvider.fetch_matches`."""
    provider = BSDDataProvider(api_key, league_id=league_id)
    return provider.fetch_matches(url=api_url, league_id=league_id, timeout=timeout)



def _build_alias_lookup(aliases: dict[str, list[str]], bracket: list[dict]) -> dict[str, str]:
    lookup: dict[str, str] = {}

    for match in bracket:
        if match.get("team_a"):
            lookup[match["team_a"].strip().lower()] = match["team_a"]
        if match.get("team_b"):
            lookup[match["team_b"].strip().lower()] = match["team_b"]

    for canonical, variants in aliases.items():
        lookup[canonical.strip().lower()] = canonical
        for variant in variants:
            lookup[variant.strip().lower()] = canonical

    return lookup


def normalize_team(api_name: str, alias_lookup: dict[str, str]) -> str | None:
    key = api_name.strip().lower()
    result = alias_lookup.get(key)
    if result is not None:
        return result
    if "&" in key:
        alt = key.replace("&", "and").replace("  ", " ")
        return alias_lookup.get(alt)
    return None


def find_bracket_match(home_norm: str, away_norm: str, bracket: list[dict]) -> str | None:
    for match in bracket:
        if match.get("team_a") is None or match.get("team_b") is None:
            continue
        if {match["team_a"], match["team_b"]} == {home_norm, away_norm}:
            return match["match_id"]
    return None


def _extract_group_letter(group_name: str) -> str | None:
    if not group_name or not group_name.startswith("Group "):
        return None
    if len(group_name) != 7:
        return None
    letter = group_name[6:7]
    if not letter or not letter.isalpha() or not letter.isupper():
        return None
    return letter


def find_group_match(
    home_norm: str,
    away_norm: str,
    group_letter: str,
    round_number: int,
    groups: dict,
) -> str | None:
    groups_data = groups.get("groups", groups)
    if group_letter not in groups_data:
        return None
    for match in groups_data[group_letter]["matches"]:
        if {match["team_a"], match["team_b"]} == {home_norm, away_norm}:
            return match["match_id"]
    return None


# ── IngestReport — competition-agnostic ingestion outcome ───────────────────


def _zero_finished_counters() -> dict:
    return {
        "received": 0,
        "normalized": 0,
        "ingested": 0,
        "skipped_unmatchable": 0,
        "skipped_no_target": 0,
    }


@dataclass
class IngestReport:
    """Structured outcome of one ingestion run (truth-ingestion contract).

    Competition-agnostic by design: no sport- or competition-specific
    vocabulary appears here. Invariant for ``finished`` counters:
    ``received == normalized == ingested + skipped_unmatchable +
    skipped_no_target`` (``ingested`` ⊆ ``normalized``).

    ``stages`` entries are plain dicts shaped ``{key, label, state, count,
    detail}`` with ``state`` limited to ``ok | pending | error |
    unavailable``.
    """

    provider: str
    attempted: bool
    success: bool
    error: str | None
    stale: bool = False
    last_success_at: str | None = None
    finished: dict = field(default_factory=_zero_finished_counters)
    stages: list = field(default_factory=list)
    written_files: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON-safe plain-dict form of the report."""
        return {
            "provider": self.provider,
            "attempted": self.attempted,
            "success": self.success,
            "error": self.error,
            "stale": self.stale,
            "last_success_at": self.last_success_at,
            "finished": dict(self.finished),
            "stages": [dict(stage) for stage in self.stages],
            "written_files": list(self.written_files),
        }

