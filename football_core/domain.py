"""Canonical football domain contracts — shared by every competition.

Single source of truth for:

- match-state semantics (played / scheduled / simulated / unknown)
- result provenance semantics (official / manual / replay / simulated)
- data-availability semantics (available / empty / missing / unavailable)

Competition packages and the web layer must consume these enums and helpers
instead of inferring state from empty arrays, falsy dicts, or file existence.
Stdlib only, competition-agnostic: no imports from competitions/* or web/*.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class MatchStatus(str, Enum):
    """Explicit lifecycle state of a single match.

    Replaces ambiguous conventions such as ``score_a: null`` in the
    schedule, absence from a results ledger, or ``winner: ""`` in
    knockout payloads.
    """

    SCHEDULED = "scheduled"      # fixture known, kickoff defined or planned, no outcome
    PLAYED = "played"            # real result decided in regulation/extra time
    PLAYED_PENS = "played_pens"  # level after ET; penalty shootout decided the tie
    UNKNOWN = "unknown"          # source could not establish any state


class ResultProvenance(str, Enum):
    """Where a match record's content came from."""

    OFFICIAL = "official"        # ingested from a live provider
    MANUAL = "manual"            # hand-entered / backfilled (e.g. no timestamp)
    REPLAY = "replay"            # loaded from a historical replay file
    SIMULATED = "simulated"      # produced by the Monte Carlo engine


class DataAvailability(str, Enum):
    """Availability of a whole data store (file, API response, stage payload).

    The distinction matters: a missing knockout_results.json and an empty
    one are different facts, and neither means "the knockout has not
    started".
    """

    AVAILABLE = "available"      # present, readable, contains records
    EMPTY = "empty"              # present, readable, but zero records
    MISSING = "missing"          # source/file does not exist
    UNAVAILABLE = "unavailable"  # exists but cannot be used (unreadable/invalid)


def effective_status(
    status: MatchStatus,
    provenance: ResultProvenance,
) -> MatchStatus:
    """Collapse (status, provenance) into the status a consumer should render.

    A SIMULATED record is never presented as played: its effective status is
    SCHEDULED when it fills a future slot. Callers combine this with the
    record's provenance to label it "simulated".
    """
    if not isinstance(status, MatchStatus):
        status = MatchStatus(status)
    if not isinstance(provenance, ResultProvenance):
        provenance = ResultProvenance(provenance)
    if provenance is ResultProvenance.SIMULATED:
        if status in (MatchStatus.PLAYED, MatchStatus.PLAYED_PENS):
            return MatchStatus.SCHEDULED
    return status


@dataclass(frozen=True)
class StageRef:
    """Opaque reference to a competition stage.

    Competition-specific stage vocabularies stay opaque here; the core never
    interprets them.
    """

    competition: str
    stage: str
    label: Optional[str] = None


def _normalize_winner(value: Any) -> Optional[str]:
    """Normalize winner fields across competitions (None vs "" vs "-")."""
    if value is None:
        return None
    text = str(value).strip()
    if text in ("", "-"):
        return None
    return text


@dataclass
class CanonicalMatch:
    """Canonical representation of one match, whatever its source.

    Legacy loaders keep working unchanged; adapters in this module convert
    their entries into this shape so new code can rely on explicit states.
    """

    match_id: str
    competition: str
    home_team: str
    away_team: str
    status: MatchStatus = MatchStatus.UNKNOWN
    home_goals: Optional[int] = None   # regulation + extra time, excludes penalties
    away_goals: Optional[int] = None
    pens_home: Optional[int] = None    # populated only for PLAYED_PENS when known
    pens_away: Optional[int] = None
    winner: Optional[str] = None       # canonical team name, or None iff draw/scheduled
    kickoff_utc: Optional[str] = None  # ISO string; absent time is None, never ""
    stage: Optional[StageRef] = None
    provenance: ResultProvenance = ResultProvenance.OFFICIAL

    def __post_init__(self) -> None:
        self.winner = _normalize_winner(self.winner)

    def effective_status(self) -> MatchStatus:
        return effective_status(self.status, self.provenance)

    @property
    def is_played_fact(self) -> bool:
        """True iff a REAL result exists (simulated outcomes are not facts)."""
        return (
            self.status in (MatchStatus.PLAYED, MatchStatus.PLAYED_PENS)
            and self.provenance is not ResultProvenance.SIMULATED
        )

    def as_dict(self) -> dict:
        """JSON-safe dict with explicit state semantics."""
        return {
            "match_id": self.match_id,
            "competition": self.competition,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "status": self.status.value,
            "effective_status": self.effective_status().value,
            "home_goals": self.home_goals,
            "away_goals": self.away_goals,
            "pens_home": self.pens_home,
            "pens_away": self.pens_away,
            "winner": self.winner,
            "kickoff_utc": self.kickoff_utc,
            "stage": {
                "competition": self.stage.competition,
                "stage": self.stage.stage,
                "label": self.stage.label,
            } if self.stage else None,
            "provenance": self.provenance.value,
        }


# ── adapters from legacy entry shapes ────────────────────────────────────────


def canonical_from_result_entry(
    entry: dict,
    competition: str,
    *,
    stage: Optional[StageRef] = None,
    default_provenance: ResultProvenance = ResultProvenance.OFFICIAL,
) -> CanonicalMatch:
    """Build a CanonicalMatch from a legacy results-ledger entry.

    Handles both WC shapes (``score_a``/``score_b`` with ``is_draw``) and
    UCL shapes (``home_score``/``away_score``, winner derived on read).
    """
    match_id = str(entry.get("match_id", ""))
    home = entry.get("team_a") or entry.get("home_team") or ""
    away = entry.get("team_b") or entry.get("away_team") or ""
    home_goals = entry.get("home_goals", entry.get("home_score", entry.get("score_a")))
    away_goals = entry.get("away_goals", entry.get("away_score", entry.get("score_b")))
    winner = _normalize_winner(entry.get("winner"))
    kickoff = entry.get("kickoff_utc", entry.get("completed_at")) or None

    if home_goals is None or away_goals is None:
        status = MatchStatus.SCHEDULED if home and away else MatchStatus.UNKNOWN
        resolved_winner = None
    else:
        # Both scores present: the match was played. Level score plus an
        # explicit winner implies a shootout decider; level without one is a
        # draw (UCL ledger entries carry no winner field at all).
        level = int(home_goals) == int(away_goals)
        if level and winner is not None:
            status = MatchStatus.PLAYED_PENS
        else:
            status = MatchStatus.PLAYED
            if not level and winner is None:
                winner = home if int(home_goals) > int(away_goals) else away
        resolved_winner = winner

    provenance = default_provenance
    if kickoff is None and status in (MatchStatus.PLAYED, MatchStatus.PLAYED_PENS):
        provenance = ResultProvenance.MANUAL

    return CanonicalMatch(
        match_id=match_id,
        competition=competition,
        home_team=home,
        away_team=away,
        status=status,
        home_goals=None if home_goals is None else int(home_goals),
        away_goals=None if away_goals is None else int(away_goals),
        winner=resolved_winner,
        kickoff_utc=kickoff,
        stage=stage,
        provenance=provenance,
    )


def canonical_scheduled_match(
    match_id: str,
    competition: str,
    home_team: str,
    away_team: str,
    *,
    stage: Optional[StageRef] = None,
    kickoff_utc: Optional[str] = None,
) -> CanonicalMatch:
    """Build the canonical form of a known fixture without a result.

    Replaces the null-trio sentinel (``winner/score_a/score_b = null``) used
    by WC groups.json.
    """
    return CanonicalMatch(
        match_id=match_id,
        competition=competition,
        home_team=home_team,
        away_team=away_team,
        status=MatchStatus.SCHEDULED,
        kickoff_utc=kickoff_utc,
        stage=stage,
        provenance=ResultProvenance.OFFICIAL,
    )


def canonical_simulated_result(
    match_id: str,
    competition: str,
    home_team: str,
    away_team: str,
    home_goals: int,
    away_goals: int,
    *,
    pens_home: Optional[int] = None,
    pens_away: Optional[int] = None,
    stage: Optional[StageRef] = None,
) -> CanonicalMatch:
    """Build the canonical form of one simulated outcome.

    Simulated records carry SIMULATED provenance so they can never be
    confused with real results downstream.
    """
    level = home_goals == away_goals
    if pens_home is not None and pens_away is not None and pens_home != pens_away:
        status = MatchStatus.PLAYED_PENS
        winner = home_team if pens_home > pens_away else away_team
    else:
        # A sampled level score is a decided draw; a non-level score has a
        # derived winner.
        status = MatchStatus.PLAYED
        winner = None if level else (home_team if home_goals > away_goals else away_team)
    return CanonicalMatch(
        match_id=match_id,
        competition=competition,
        home_team=home_team,
        away_team=away_team,
        status=status,
        home_goals=home_goals,
        away_goals=away_goals,
        pens_home=pens_home,
        pens_away=pens_away,
        winner=winner,
        stage=stage,
        provenance=ResultProvenance.SIMULATED,
    )


# ── store availability ───────────────────────────────────────────────────────


def is_semantically_empty(payload: Any) -> bool:
    """True when a parsed payload carries zero records at any nesting depth.

    ``{"matches": {}}``, ``[]``, ``{"a": []}``, ``None`` and ``""`` are all
    semantically empty; scalars like ``0`` or ``False`` count as content.
    """
    if payload is None or payload == "":
        return True
    if isinstance(payload, dict):
        return all(is_semantically_empty(v) for v in payload.values())
    if isinstance(payload, (list, tuple)):
        return all(is_semantically_empty(v) for v in payload)
    return False


def load_json_store(path: str | Path) -> tuple[Any | None, DataAvailability, Optional[str]]:
    """Load a JSON store and classify its availability explicitly.

    Returns ``(payload, availability, detail)`` where *payload* is the
    parsed JSON (or ``None``) and *detail* carries the failure reason for
    UNAVAILABLE stores. Never raises for missing/unreadable files.
    """
    p = Path(path)
    if not p.exists():
        return None, DataAvailability.MISSING, f"file not found: {p}"
    try:
        with open(p, encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        return None, DataAvailability.UNAVAILABLE, f"{p}: {exc.__class__.__name__}: {exc}"
    if is_semantically_empty(payload):
        return payload, DataAvailability.EMPTY, None
    return payload, DataAvailability.AVAILABLE, None
