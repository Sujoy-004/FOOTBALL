"""World Cup seed+replay Elo runtime adapter.

Layer boundary: this module lives in the World Cup brain and imports
from ``football_core`` only. It feeds the seed+replay Elo kernel
(``football_core.elo_replay.replay_elo``) with the World Cup's own seed
(``teams.json`` Elo ratings) and its played-match stores, and performs
ZERO network requests in every mode — the whole compute is local.

Row normalization mirrors ``football_core.elo.apply_elo_update``
byte-for-byte so the replayed canon stays identical to the locked
predictor path: ``pk_winner`` carries the row's winner only when the row
is a decided non-draw (penalty/normative weighting 0.75/0.25), and the
per-row mean-reversion base is ``K = compute_k_factor(...)`` over the
tournament-standard ``football_core.constants.K_FACTOR`` (60).

METHODOLOGY BOUNDARY (do not "fix" this): ``/api/validation`` and
``evaluation.py``'s elo-only evaluation lanes replay the RAW teams.json
seed on purpose — they judge PRE-TOURNAMENT predictions made with the
shipped ratings, so a rating that includes elapsed tournament results
would be hindsight fraud. Only the what-if/simulation runtime baselines
flow through this module's elapsed replay.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from football_core.constants import K_FACTOR
from football_core.elo_replay import replay_elo

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"

_PLAYED_STORES = ("played_groups.json", "played.json")


def _load_store(path: Path):
    """Tolerant JSON load: absent/unreadable stores yield ``{}`` (honest)."""
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError) as exc:
        logger.warning("World Cup Elo replay skipped store %s (%s)", path, exc)
        return {}
    return payload


def _seed_from_teams(data_dir: Path) -> dict[str, float]:
    """teams.json Elo map (the stored seed), or ``{}`` when absent."""
    payload = _load_store(Path(data_dir) / "teams.json")
    seed: dict[str, float] = {}
    if isinstance(payload, dict):
        for name, entry in payload.items():
            # Missing/non-numeric ratings are skipped honestly — never a
            # fabricated DEFAULT_ELO fill (kernel drops them anyway).
            if not isinstance(entry, dict):
                continue
            value = entry.get("elo")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                seed[str(name)] = float(value)
    return seed


def _kernel_rows(data_dir: Path) -> list[dict]:
    """played_groups.json + played.json rows → the kernel row contract.

    Same normalization as ``apply_elo_update``: explicit ``winner``
    pass-through and ``pk_winner`` present only for decided rows
    (``is_draw`` False with a non-empty winner). Group rows come first
    (chronologically earlier), knockout rows after; the kernel re-sorts
    by ``(date, team_a, team_b)`` so merge order is irrelevant.
    """
    rows: list[dict] = []
    dp = Path(data_dir)
    for store_name in _PLAYED_STORES:
        payload = _load_store(dp / store_name)
        matches = (
            payload.values() if isinstance(payload, dict)
            else payload if isinstance(payload, list)
            else []
        )
        for row in matches:
            if not isinstance(row, dict):
                continue
            winner = row.get("winner")
            is_draw = row.get("is_draw", True)
            rows.append({
                "team_a": row.get("team_a"),
                "team_b": row.get("team_b"),
                "home_score": row.get("home_score"),
                "away_score": row.get("away_score"),
                "date": row.get("completed_at") or "",
                "winner": winner,
                "pk_winner": winner if (not is_draw and winner) else None,
            })
    return rows


def computed_baseline_elos(data_dir: Path | None = None) -> dict[str, float]:
    """Elapsed-replay Elo baseline from committed stores (zero network).

    Seed = the stored ``teams.json`` ratings with as-of "" (teams.json
    carries no date, so every date-stamped played row qualifies for the
    replay); rows = played_groups.json + played.json merged. Ratings for
    teams absent from the seed are kernel-skipped (never fabricated),
    matching the evaluation lane's skip behavior. The caller's seed dict
    is left untouched — the kernel replays on a private copy.
    """
    dp = Path(data_dir) if data_dir is not None else _DATA_DIR
    seed = _seed_from_teams(dp)
    if not seed:
        return {}
    outcome = replay_elo(seed, "", _kernel_rows(dp), base_k=K_FACTOR)
    return outcome.ratings
