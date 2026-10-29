"""Fetch and process live match results from BSD API — generic pipeline."""

import logging
import unicodedata
from dataclasses import dataclass, field

from football_core.data_providers.bsd_provider import BSDDataProvider

logger = logging.getLogger(__name__)


#: Bounded transliteration table so accented spellings collapse onto the same
#: folded key as their provider-ASCII equivalents (``ø``/``Ø`` have no NFKD
#: decomposition, so they must be folded explicitly).
_FOLD_TRANSLIT = str.maketrans({"ø": "o", "Ø": "O"})


def fold_team_key(name: str) -> str:
    """Casefolded, accent-folded key that identifies ONE team spelling family.

    Deliberately bounded: NFC/NFKD-decomposes combining marks, applies a small
    explicit transliteration for letters without a decomposition (``ø``), and
    casefolds. It is NOT fuzzy matching — it only collapses known Unicode
    equivalent spellings of the same name (``Atletico Madrid`` vs
    ``Atlético Madrid``, ``Bodo/Glimt`` vs ``Bodø/Glimt``) onto one key.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.translate(_FOLD_TRANSLIT).strip().casefold()


def fold_pair_key(home: str, away: str) -> tuple[str, str]:
    """Identity key for a (home, away) fixture relationship using folded names.

    Home/away order is preserved, so ``A@B`` and ``B@A`` stay distinct —
    exactly like :func:`competitions.ucl.src.ingest._fixture_pair_key`, but
    tolerant of accent/ASCII spelling families.
    """
    return (fold_team_key(home), fold_team_key(away))


def new_ingestion_stats() -> dict:
    """Create a zeroed result-ingestion stats dict (truth-ingestion contract).

    Invariant: received == normalized == ingested +
    skipped_unmatchable + skipped_no_target + skipped_missing_score.
    Any finished match that is not ingested must appear in exactly one
    skipped_* bucket and be logged at WARNING level.

    D-14: ``received`` is the ONE name for the finished-result bucket —
    the historical ``finished_received`` spelling was retired so this dict
    and ``IngestReport.finished`` share a single vocabulary.
    """
    return {
        "received": 0,
        "normalized": 0,
        "ingested": 0,
        "skipped_unmatchable": 0,
        "skipped_no_target": 0,
        "skipped_missing_score": 0,
    }


def count_finished(stats: dict) -> None:
    stats["received"] += 1


def note_unmatchable(stats: dict, log: logging.Logger,
                     home_name: str, away_name: str, score=None,
                     *, season: str | None = None, event_id: str | None = None,
                     status: str = "finished") -> None:
    """A finished result could not be matched to known teams."""
    stats["skipped_unmatchable"] += 1
    score_str = f" {score}" if score else ""
    log.warning(
        "RESULT INGESTION SKIP (unmatchable team names) "
        "reason=unmatchable_team_names season=%s event_id=%s status=%s: "
        "%r vs %r%s — this finished match will be simulated unless re-ingested",
        season or "unknown", event_id or "unknown", status,
        home_name, away_name, score_str,
    )


def note_no_target(stats: dict, log: logging.Logger,
                   home_norm: str, away_norm: str, *, season: str | None = None,
                   event_id: str | None = None, status: str = "finished") -> None:
    stats["skipped_no_target"] += 1
    log.warning(
        "RESULT INGESTION SKIP (no matching fixture/slot) "
        "reason=no_active_season_target season=%s event_id=%s status=%s: %r vs %r",
        season or "unknown", event_id or "unknown", status, home_norm, away_norm,
    )


def note_missing_score(stats: dict, log: logging.Logger,
                       home_name: str, away_name: str, *, season: str | None = None,
                       event_id: str | None = None, status: str = "finished",
                       score=None) -> None:
    """Reject a result without score evidence instead of fabricating 0-0."""
    stats["skipped_missing_score"] += 1
    log.warning(
        "RESULT INGESTION SKIP reason=missing_score season=%s event_id=%s "
        "status=%s: FINISHED EVENT WITHOUT SCORES %r vs %r score=%s",
        season or "unknown", event_id or "unknown", status,
        home_name, away_name, score,
    )


def note_fixture_unmatchable(log: logging.Logger, home_name: str, away_name: str,
                             *, season: str | None = None,
                             event_id: str | None = None,
                             status: str = "scheduled") -> None:
    """Report a scheduled fixture that cannot be normalized as a result."""
    log.info(
        "FIXTURE INGESTION IGNORE reason=optional_metadata_unresolved "
        "detail=unmatchable_team_names season=%s "
        "event_id=%s status=%s: %r vs %r",
        season or "unknown", event_id or "unknown", status,
        home_name, away_name,
    )


def summarize_ingestion(stats: dict, log: logging.Logger, context: str) -> None:
    """Log the ingestion invariant summary; WARN when finished results were lost."""
    lost = stats["skipped_unmatchable"] + stats["skipped_no_target"]
    log.log(
        logging.WARNING if lost else logging.INFO,
        "Ingestion summary [%s]: finished=%d normalized=%d ingested=%d "
        "skipped_unmatchable=%d skipped_no_target=%d skipped_missing_score=%d",
        context, stats["received"], stats["normalized"],
        stats["ingested"], stats["skipped_unmatchable"], stats["skipped_no_target"],
        stats.get("skipped_missing_score", 0),
    )


def derive_success(provider: str | None, attempted: bool,
                   finished: dict) -> tuple[bool, str | None]:
    """D-13: ``success`` is derived from the counters, never declared.

    Args:
        provider: Provider label used only for the counter-inconsistency
            warning, so a broken run is traceable to its source.
        attempted: Whether an acquisition attempt actually happened.
        finished: The report's finished-result counters
            (``received``/``normalized``/``ingested``/``skipped_*``).

    Returns:
        ``(success, reason)`` where reason is one of ``None`` (real,
        consistent work was ingested), ``"deferred"`` (nothing was
        attempted), ``"deferred/provider-empty"`` (attempted but zero
        matches came back) or ``"counter_inconsistent"`` (the invariant
        broke — fails closed, never raises into the request path).
    """
    if not attempted:
        return False, "deferred"
    if not isinstance(finished, dict) or int(finished.get("received") or 0) == 0:
        # Attempted but nothing came back (HTTP 200 with an empty body).
        return False, "deferred/provider-empty"
    skipped = (
        "skipped_unmatchable",
        "skipped_no_target",
        "skipped_missing_score",
    )
    try:
        received = int(finished["received"])
        normalized = int(finished["normalized"])
        ingested = int(finished["ingested"])
        skips = [int(finished[key]) for key in skipped]
        # D-14 re-offer bucket: optional so callers on the legacy 6-key
        # vocabulary stay valid; a PRESENT key still fails closed on bad
        # values (no silent coercion).
        if "skipped_no_change" in finished:
            skips.append(int(finished["skipped_no_change"]))
    except (KeyError, TypeError, ValueError):
        logger.warning(
            "Counter check [%s]: finished counters incomplete — %r; "
            "treating the run as counter_inconsistent",
            provider or "unknown", finished,
        )
        return False, "counter_inconsistent"
    if received != normalized or normalized != ingested + sum(skips):
        logger.warning(
            "Counter check [%s]: invariant broken — received=%d normalized=%d "
            "ingested=%d skipped=%d; report fails closed as counter_inconsistent",
            provider or "unknown", received, normalized, ingested, sum(skips),
        )
        return False, "counter_inconsistent"
    return True, None


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
        "skipped_missing_score": 0,
    }


@dataclass
class IngestReport:
    """Structured outcome of one ingestion run (truth-ingestion contract).

    Competition-agnostic by design: no sport- or competition-specific
    vocabulary appears here. Invariant for ``finished`` counters:
    ``received == normalized == ingested + skipped_unmatchable +
    skipped_no_target + skipped_missing_score`` (``ingested`` ⊆ ``normalized``).

    ``stages`` entries are plain dicts shaped ``{key, label, state, count,
    detail}`` with ``state`` limited to ``ok | pending | error |
    unavailable``.
    """

    provider: str | None
    attempted: bool
    success: bool
    error: str | None
    stale: bool = False
    last_success_at: str | None = None
    finished: dict = field(default_factory=_zero_finished_counters)
    stages: list = field(default_factory=list)
    written_files: list = field(default_factory=list)
    deferred: bool = False
    reason: str | None = None
    #: Phase 5 (D-05/D-06): the brain→web edge is a DATA edge. ``changed``
    #: means the STORE CONTENT changed — not "the file was rewritten".
    #: ``changed_match_ids`` names the ids whose stored content changed.
    changed: bool = False
    changed_match_ids: list = field(default_factory=list)

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
            "deferred": self.deferred,
            "reason": self.reason,
            "changed": bool(self.changed),
            "changed_match_ids": list(self.changed_match_ids),
        }
