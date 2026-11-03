"""Competition-agnostic seed+replay Elo kernel.

Computes runtime Elo ratings from a stored seed snapshot plus a
chronologically replayed ledger of played results strictly after the
seed's as-of date. This replaces the retired ClubElo runtime fetch: every
competition seeds from its own committed snapshot data and replays only
its own local result stores, so ratings stay traceable and fully
offline-capable (zero network requests in every mode).

Layer boundaries (hard rules):

- imports nothing from ``competitions/*`` or ``web/*``;
- performs NO filesystem IO and NO network requests — the competition
  adapters read their own stores and normalize rows into the contract
  below before calling :func:`replay_elo`;
- reuses :func:`football_core.elo.update_ratings` and
  :func:`football_core.elo.compute_k_factor` verbatim — the Elo math has a
  single implementation repo-wide.

Normalized row contract (adapters normalize each competition's store
rows INTO this shape; the kernel itself reads no files):

- ``team_a``: str, ``team_b``: str;
- ``home_score``/``away_score``: numeric;
- ``date``: str — ISO date or ISO timestamp. ``""`` means the row cannot
  be proven to postdate the seed, so it is skipped (fail closed against
  double counting a result the seed may already reflect);
- ``winner`` (optional): when the key IS present its value is passed
  straight to ``update_ratings`` (after consistency checks); when the
  key is ABSENT the kernel derives the winner from the scores
  (``home_score > away_score`` → ``team_a``, lower → ``team_b``, equal
  → ``None`` = draw);
- ``pk_winner`` (optional): pass-through to ``update_ratings`` for the
  0.75/0.25 penalty-shootout weighting.

Honest limitation: replay does not model home advantage —
``update_ratings`` has no home term. Seed values already absorbed the
historical home advantage of the results they were derived from, so
replaying strict successors without a home term keeps the scale
consistent with the seed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from football_core import constants
from football_core.elo import compute_k_factor, update_ratings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReplayOutcome:
    """Immutable result of one seed+replay pass.

    Attributes
    ----------
    ratings
        Post-replay ``{team: Elo}`` map (the caller's seed dict is never
        mutated — replay runs on a private copy).
    as_of
        The date the ratings are current to: lex-max of the seed's as-of
        and the latest replayed row date, "" when neither exists.
    replayed
        Number of rows that actually moved ratings.
    skipped
        Number of rows that could not be replayed (undated, too old,
        missing teams, invalid winner/scores, or an ``update_ratings``
        error). Never swallowed silently — always surfaced here so a
        caller can label its provenance honestly.
    """

    ratings: dict[str, float] = field(default_factory=dict)
    as_of: str = ""
    replayed: int = 0
    skipped: int = 0


def _numeric(value: Any) -> bool:
    """True for int/float values (bools excluded — they are not scores)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def replay_elo(
    seed: Mapping[str, float],
    seed_as_of: str,
    rows: Iterable[Mapping[str, Any]],
    base_k: int = constants.K_FACTOR,
) -> ReplayOutcome:
    """Replay date-carrying played rows over *seed* and return the outcome.

    Parameters
    ----------
    seed
        ``{team: rating}`` starting point. Never mutated: the replay runs
        on a private copy, and non-numeric seed values are dropped
        honestly (no fabricated fills).
    seed_as_of
        Date/timestamp the seed reflects. Every row dated at-or-before it
        is skipped so the seed is never double counted (D-01: strictly
        after). ``""`` disables the filter — every date-carrying row
        qualifies (used when the seed carries no as-of, e.g. teams.json).
    rows
        Iterable of normalized rows (see the module docstring).
    base_k
        Base K factor handed to :func:`compute_k_factor`; the per-row
        goal-difference multiplier scales it.

    Returns
    -------
    ReplayOutcome
        The post-replay ratings, the outcome ``as_of``, and honest
        ``replayed``/``skipped`` counts. Deterministic: identical inputs
        produce an identical outcome with no time-dependent behavior.
    """
    ratings: dict[str, float] = {
        team: float(value)
        for team, value in (seed or {}).items()
        if _numeric(value)
    }

    candidates: list[tuple[str, str, str, Mapping[str, Any]]] = []
    skipped = 0
    for row in rows:
        if not isinstance(row, Mapping):
            skipped += 1
            continue
        team_a = row.get("team_a")
        team_b = row.get("team_b")
        home_score = row.get("home_score")
        away_score = row.get("away_score")
        date = row.get("date")
        if (
            not isinstance(team_a, str) or not isinstance(team_b, str)
            or not team_a or not team_b
            or not _numeric(home_score) or not _numeric(away_score)
            or not isinstance(date, str) or not date
        ):
            skipped += 1
            continue
        if seed_as_of and date <= seed_as_of:
            # The seed already reflects this result — replaying it would
            # double count. Skipped, counted, never replayed.
            skipped += 1
            continue
        candidates.append((date, team_a, team_b, row))

    candidates.sort(key=lambda c: (c[0], c[1], c[2]))

    replayed = 0
    latest_date = ""
    for date, team_a, team_b, row in candidates:
        home_score = float(row["home_score"])
        away_score = float(row["away_score"])
        if team_a not in ratings or team_b not in ratings:
            # Missing-seed rows are skipped, mirroring evaluation.py's
            # existing skip: teams are never fabricated, the seed dict is
            # never extended.
            skipped += 1
            continue
        equal_scores = home_score == away_score
        pk_winner = row.get("pk_winner")
        if "winner" in row:
            winner = row["winner"]
            if winner is not None and winner not in (team_a, team_b):
                # Unknown winner token — fail closed.
                skipped += 1
                continue
            if winner is not None and not equal_scores:
                # The stored winner must match the score direction.
                if (home_score > away_score) != (winner == team_a):
                    skipped += 1
                    continue
            if winner is not None and equal_scores and pk_winner is None:
                # A declared winner on an equal-scores row is a data
                # inconsistency unless a pk_winner (shootout) explains it
                # — fail closed instead of trusting the claim.
                skipped += 1
                continue
        else:
            if home_score > away_score:
                winner = team_a
            elif away_score > home_score:
                winner = team_b
            else:
                winner = None
        if pk_winner is not None and pk_winner not in (team_a, team_b):
            skipped += 1
            continue
        k = int(round(compute_k_factor(int(abs(home_score - away_score)), base_k)))
        try:
            moved = update_ratings(
                team_a, team_b, winner, ratings, K=k, pk_winner=pk_winner
            )
        except Exception:
            # One bad row never aborts the run — skip it and count it.
            logger.exception("elo_replay skipped row %s vs %s (%s)", team_a, team_b, date)
            skipped += 1
            continue
        ratings.update(moved)
        replayed += 1
        if date > latest_date:
            latest_date = date

    if seed_as_of and latest_date:
        as_of = max(seed_as_of, latest_date)
    else:
        as_of = seed_as_of or latest_date

    return ReplayOutcome(ratings=ratings, as_of=as_of, replayed=replayed, skipped=skipped)
