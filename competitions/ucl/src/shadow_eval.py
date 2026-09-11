"""LIVE SHADOW EVALUATION — frozen pre-kickoff prediction log for UCL.

Side-by-side, immutable, append-only record of what THREE strategies
(``production``, ``market_elo_equal``, ``market_elo_prior``) predicted for
NEW real UCL matches *before kickoff*, accumulating real results as they
arrive. Production behaviour is never modified: this module only *reads*
existing engines/signals and writes its own shadow stores under
``competitions/ucl/data/shadow/<season>/``.

Correctness is by construction:

* a fixture is frozen ONLY when its kickoff is strictly in the future
  relative to an injectable ``as_of`` (wall clock by default), and
* NEVER when a real result for it is already known.

A ``(season, match_id, strategy)`` record is written exactly once; results
are attached exactly once per ``(season, match_id)``. Missing scores are
never turned into 0-0. Given identical ``(fixtures, results, elo_ratings,
as_of)`` the emitted JSON lines are byte-identical (no RNG in the freeze
path).

CLI::

    python -m competitions.ucl.src.shadow_eval freeze --season 2026/27 [--dry-run]
    python -m competitions.ucl.src.shadow_eval attach --season 2026/27 [--dry-run]
    python -m competitions.ucl.src.shadow_eval report --season 2026/27
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("ucl.shadow_eval")

# ── paths ────────────────────────────────────────────────────────────────────
#
# ``__file__`` -> competitions/ucl/src/shadow_eval.py
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))          # competitions/ucl/src
_UCL_DIR = os.path.dirname(_SRC_DIR)                            # competitions/ucl
DATA_DIR = os.path.join(_UCL_DIR, "data")                       # competitions/ucl/data
SHADOW_BASE = os.path.join(DATA_DIR, "shadow")                  # competitions/ucl/data/shadow
SQUAD_VALUES_PATH = os.path.join(DATA_DIR, "squad_values.json")

# ── constants ────────────────────────────────────────────────────────────────

SCHEMA_VERSION = 1
MODEL_VERSION = "shadow-1.0.0"
SHADOW_STRATEGIES = ("production", "market_elo_equal", "market_elo_prior")
_ODDS_KEYS = ("odds_home", "odds_draw", "odds_away")
_OUTCOME_INDEX = {"H": 0, "D": 1, "A": 2}

BOOT_SEED = 20260601
N_BOOT = 2000


# ═══════════════════════════════════════════════════════════════════════════════
# Time helpers
# ═══════════════════════════════════════════════════════════════════════════════


def now_utc() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return now_utc()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_kickoff(value: str) -> datetime:
    """Parse an ISO-8601 kickoff string to a UTC datetime.

    Handles a trailing ``Z`` and naive strings (assumed UTC). Raises
    ``ValueError`` for missing/unparseable input.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"bad kickoff value: {value!r}")
    text = value.strip()
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:  # pragma: no cover - message passthrough
        raise ValueError(f"bad kickoff value: {value!r}") from exc
    return _as_utc(dt)


# ═══════════════════════════════════════════════════════════════════════════════
# IO layer
# ═══════════════════════════════════════════════════════════════════════════════


def _verbose() -> bool:
    return bool(os.environ.get("SHADOW_VERBOSE"))


def load_json(path: str | os.PathLike) -> Any:
    """Load JSON; ``None`` when absent or corrupt (never raises)."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        logger.warning("[shadow] %s unreadable (%s)", p, exc)
        return None


def load_jsonl(path: str | os.PathLike) -> list[dict]:
    """Load a JSONL file; malformed lines are skipped, absent -> []."""
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict] = []
    try:
        text = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        logger.warning("[shadow] %s unreadable (%s)", p, exc)
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("[shadow] skipping malformed line in %s", p)
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.stem + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_write_json(data: Any, path: Path) -> None:
    _atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def append_jsonl(path: str | os.PathLike, record: dict) -> None:
    """Append one canonical JSON line.

    First write to a new/empty file is atomic (temp + ``os.replace``);
    subsequent appends use mode ``'a'``. Set ``SHADOW_VERBOSE`` for logging.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    if not p.exists() or p.stat().st_size == 0:
        _atomic_write_text(p, line)
    else:
        with open(p, "a", encoding="utf-8") as f:
            f.write(line)
    if _verbose():
        logger.info("[shadow] appended record to %s", p)


# ═══════════════════════════════════════════════════════════════════════════════
# Season / shadow store paths
# ═══════════════════════════════════════════════════════════════════════════════


def season_store_dir(data_dir: str | os.PathLike, season: str) -> Path:
    """Reuse the canonical season store directory (``seasons.season_dir``)."""
    from competitions.ucl.src.seasons import season_dir

    return season_dir(data_dir, season)


def canonical_fixtures_file(data_dir: str | os.PathLike, season: str) -> str:
    return str(season_store_dir(data_dir, season) / "fixtures.json")


def canonical_results_file(data_dir: str | os.PathLike, season: str) -> str:
    return str(season_store_dir(data_dir, season) / "results.json")


def shadow_season_dir(season: str) -> Path:
    from competitions.ucl.src.seasons import season_dir_id

    return Path(SHADOW_BASE) / season_dir_id(season)


def ensure_shadow_schema(season: str) -> str:
    """Create ``shadow/<season>/schema.json`` once; never overwrite."""
    path = shadow_season_dir(season) / "schema.json"
    if path.exists():
        return str(path)
    payload = {
        "schema": SCHEMA_VERSION,
        "season": season,
        "created_at": now_utc().isoformat(),
        "model_version": MODEL_VERSION,
        "strategies": list(SHADOW_STRATEGIES),
    }
    _atomic_write_json(payload, path)
    return str(path)


# ═══════════════════════════════════════════════════════════════════════════════
# Elo resolution (offline-first, deterministic)
# ═══════════════════════════════════════════════════════════════════════════════


def _find_draw_file(data_dir: str, season: str | None) -> tuple[str | None, dict]:
    """Locate a league-draw file and return (path, {team: coefficient})."""
    draws_dir = os.path.join(data_dir, "draws")
    if not os.path.isdir(draws_dir):
        return None, {}
    candidates: list[str] = []
    for name in sorted(os.listdir(draws_dir)):
        if name.endswith("_league_draw.json"):
            candidates.append(os.path.join(draws_dir, name))
    if not candidates:
        return None, {}
    chosen = candidates[-1]
    if season:
        from competitions.ucl.src.seasons import season_dir_id

        prefix = season_dir_id(season)
        for c in candidates:
            if os.path.basename(c).startswith(prefix):
                chosen = c
                break
    doc = load_json(chosen) or {}
    coeffs: dict[str, float] = {}
    for team in doc.get("teams", []) if isinstance(doc, dict) else []:
        name = team.get("name")
        coeff = team.get("coefficient")
        if name is not None and isinstance(coeff, (int, float)) and not isinstance(coeff, bool):
            coeffs[str(name)] = float(coeff)
    return chosen, coeffs


def resolve_elo(
    team_names: list[str],
    *,
    elo_file: str | None = None,
    use_live: bool = False,
    data_dir: str | None = None,
    season: str | None = None,
) -> tuple[dict, dict]:
    """Resolve Elo ratings for *team_names* deterministically.

    Precedence:

    1. ``elo_file`` (snapshot) — missing teams fall back to DEFAULT_ELO;
    2. ``use_live`` — best-effort ClubElo fetch via the orchestrator;
    3. offline default — coefficient-derived ratings from the league draw
       (``1400 + coeff/max_coeff * 400``, mirroring ``web/ucl_app``).

    Returns ``(ratings, provenance)``. If nothing is available the ratings
    dict is empty (provenance ``{"source": "none"}``) and every team falls
    back to DEFAULT_ELO inside ``RefinedEloSignal``.
    """
    from football_core.constants import DEFAULT_ELO

    teams = list(dict.fromkeys(team_names))
    default = float(DEFAULT_ELO)

    if elo_file and os.path.exists(elo_file):
        raw = load_json(elo_file)
        raw = raw if isinstance(raw, dict) else {}
        ratings: dict[str, float] = {}
        missing: list[str] = []
        for t in teams:
            val = raw.get(t)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                ratings[t] = float(val)
            else:
                ratings[t] = default
                missing.append(t)
        prov: dict = {"source": "snapshot", "file": os.path.basename(elo_file)}
        if missing:
            prov["filled_missing"] = len(missing)
        return ratings, prov

    if use_live:
        try:
            from competitions.ucl.src.orchestrator import _resolve_elo_ratings

            live = _resolve_elo_ratings(teams)
        except Exception as exc:  # pragma: no cover - network/import guarded
            logger.warning("[shadow] live Elo resolution failed (%s)", exc)
            live = {}
        if live:
            return (
                {t: float(live.get(t, default)) for t in teams},
                {"source": "clubelo", "file": None},
            )

    data_dir = data_dir or DATA_DIR
    draw_path, coeffs = _find_draw_file(data_dir, season)
    if coeffs:
        max_c = max(coeffs.values()) or 1.0
        ratings = {t: 1400.0 + (coeffs.get(t, 0.0) / max_c) * 400.0 for t in teams}
        return ratings, {"source": "coefficient", "file": os.path.basename(draw_path) if draw_path else None}

    return {}, {"source": "none", "file": None}


# ═══════════════════════════════════════════════════════════════════════════════
# Context / engines
# ═══════════════════════════════════════════════════════════════════════════════


def make_target_match(fixture: dict) -> dict:
    """Match dict handed to signals — a shallow copy of the fixture.

    Keeps ``team_a``/``team_b``/``match_id``/``event_date`` at minimum so
    ``RestDaysSignal`` can compute (it reads ``event_date`` off the match).
    """
    return {**fixture}


def _load_squad_values() -> dict[str, float] | None:
    doc = load_json(SQUAD_VALUES_PATH)
    if not isinstance(doc, dict) or not doc:
        return None
    return {str(k): float(v) for k, v in doc.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}


def _result_row_from_fixture(fixture: dict, result_row: dict) -> dict:
    """Shape a result row exactly for RollingForm / played_results consumers."""
    hs = result_row.get("home_score")
    aws = result_row.get("away_score")
    team_a = fixture.get("team_a", "")
    team_b = fixture.get("team_b", "")
    winner = result_row.get("winner")
    if winner is None and isinstance(hs, (int, float)) and isinstance(aws, (int, float)):
        if hs > aws:
            winner = team_a
        elif aws > hs:
            winner = team_b
    return {
        "team_a": team_a,
        "team_b": team_b,
        "home_score": hs,
        "away_score": aws,
        "winner": winner,
        "is_draw": bool(isinstance(hs, (int, float)) and isinstance(aws, (int, float)) and hs == aws),
        "event_date": fixture.get("event_date", ""),
        "match_id": fixture.get("match_id", ""),
    }


def build_strict_prior_context(
    target: dict,
    all_fixtures: list[dict],
    elo_ratings: dict,
    result_rows_by_match_id: dict,
):
    """Build a STRICT-prior ``PredictionContext`` for *target*.

    Prior fixtures are those whose kickoff is STRICTLY before the target's
    kickoff. Unparseable/absent event dates are excluded (they cannot be
    ordered). ``played_results`` contains only prior fixtures with a real
    complete result, shaped for RollingForm/played_results consumers.
    """
    from football_core.signal import PredictionContext

    try:
        target_kick = parse_kickoff(target.get("event_date"))
    except ValueError:
        target_kick = None

    prior: list[dict] = []
    for f in all_fixtures:
        try:
            kick = parse_kickoff(f.get("event_date"))
        except (ValueError, AttributeError):
            continue
        if target_kick is not None and kick < target_kick:
            prior.append(f)

    played: list[dict] = []
    for f in prior:
        row = result_rows_by_match_id.get(f.get("match_id"))
        if row is None:
            continue
        if row.get("home_score") is None or row.get("away_score") is None:
            continue
        played.append(_result_row_from_fixture(f, row))

    return PredictionContext(
        fixtures=list(prior),
        elo_ratings=dict(elo_ratings or {}),
        played_results=played,
        squad_values=_load_squad_values(),
    )


def _weights_file_for(strategy: str) -> str | None:
    from competitions.ucl.src.orchestrator import _get_config_dir

    if strategy == "production":
        path = os.path.join(_get_config_dir(), "signal_weights.json")
        return "signal_weights.json" if os.path.exists(path) else None
    if strategy == "market_elo_prior":
        from competitions.ucl.src.ensemble import load_prior_weights

        _, source = load_prior_weights()
        return source if source == "market_elo_prior_weights.json" else None
    return None


def build_engines(
    elo_ratings: dict,
    results_file: str | None,
    season: str,
    data_dir: str,
) -> dict[str, Any]:
    """Build all three strategy engines (mirrors the production app)."""
    from competitions.ucl.src.orchestrator import build_signal_engine

    production = build_signal_engine(
        elo_ratings,
        results_file=results_file if (results_file and os.path.exists(results_file)) else None,
        strategy="production",
    )
    return {
        "production": production,
        "market_elo_equal": build_signal_engine(elo_ratings, strategy="market_elo_equal"),
        "market_elo_prior": build_signal_engine(elo_ratings, strategy="market_elo_prior"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Prediction record construction
# ═══════════════════════════════════════════════════════════════════════════════


def _usable_odds(match: dict) -> bool:
    for key in _ODDS_KEYS:
        val = match.get(key)
        if isinstance(val, bool) or not isinstance(val, (int, float)) or val <= 0:
            return False
    return True


def _round_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), 4)


def _round_probs(home: float, draw: float, away: float) -> dict:
    """Round to 4 dp and force the trio to sum to exactly 1.0 (deterministic)."""
    vals = [round(float(home), 4), round(float(draw), 4), round(float(away), 4)]
    diff = round(1.0 - sum(vals), 4)
    if diff != 0:
        idx = max(range(3), key=lambda i: vals[i])
        vals[idx] = round(vals[idx] + diff, 4)
    return {"home": vals[0], "draw": vals[1], "away": vals[2]}


def _weights_hash(weights: dict) -> str:
    canon = json.dumps(weights, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _build_record(
    *,
    season: str,
    fixture: dict,
    strategy: str,
    engine: Any,
    context: Any,
    elo_ratings: dict,
    elo_provenance: dict,
    weights_file: str | None,
    as_of: datetime,
) -> dict:
    from football_core.constants import DEFAULT_ELO

    match = make_target_match(fixture)
    blended = engine.evaluate(match, context)
    predicted = _round_probs(blended.home_prob, blended.draw_prob, blended.away_prob)

    odds_available = _usable_odds(match)
    odds = {key.replace("odds_", ""): _round_or_none(match.get(key)) for key in _ODDS_KEYS}

    market_elo_prov: dict | None = None
    fallback: dict | None = None
    if strategy in ("market_elo_equal", "market_elo_prior"):
        try:
            signal = engine._registry.get("market_elo")
            market_elo_prov = signal.last_provenance()
        except Exception:  # pragma: no cover - defensive
            market_elo_prov = {}
        if not (market_elo_prov or {}).get("usable_odds"):
            fallback = {"reason": "no_odds", "behavior": "elo_only"}
    else:
        if not odds_available:
            fallback = {"reason": "no_odds", "behavior": "uniform"}

    home_team = fixture.get("team_a", "")
    away_team = fixture.get("team_b", "")
    elo_source = (elo_provenance or {}).get("source", "none")
    elo_file = (elo_provenance or {}).get("file")

    weights = dict(engine.weights)
    return {
        "schema": SCHEMA_VERSION,
        "season": season,
        "match_id": fixture.get("match_id"),
        "stage": fixture.get("stage"),
        "official_matchday": fixture.get("official_matchday"),
        "simulation_matchday": fixture.get("simulation_matchday"),
        "kickoff": fixture.get("event_date"),
        "home_team": home_team,
        "away_team": away_team,
        "strategy": strategy,
        "predicted": predicted,
        "prediction_timestamp": _as_utc(as_of).isoformat(),
        "odds_available": odds_available,
        "odds": odds,
        "provenance": {
            "signals": dict(blended.signal_breakdown),
            "market_elo": market_elo_prov,
            "elo": {
                "home": float(elo_ratings.get(home_team, float(DEFAULT_ELO))),
                "away": float(elo_ratings.get(away_team, float(DEFAULT_ELO))),
                "source": elo_source,
                "file": elo_file,
            },
            "fallback": fallback,
        },
        "config": {
            "weights": weights,
            "weights_file": weights_file,
            "weights_hash": _weights_hash(weights),
            "engine_signals": list(engine._registry.list()),
        },
    }


def _fixture_sort_key(fixture: dict) -> tuple:
    try:
        kick = parse_kickoff(fixture.get("event_date"))
        return (0, kick.isoformat(), str(fixture.get("match_id", "")))
    except (ValueError, AttributeError):
        return (1, "", str(fixture.get("match_id", "")))


# ═══════════════════════════════════════════════════════════════════════════════
# Freeze
# ═══════════════════════════════════════════════════════════════════════════════


def freeze_predictions(
    *,
    season: str,
    fixtures: list[dict],
    result_rows: list[dict],
    elo_ratings: dict,
    as_of: datetime,
    data_dir: str,
    strategies: tuple | list = SHADOW_STRATEGIES,
    append_to: str | os.PathLike | None = None,
    elo_provenance: dict | None = None,
    write: bool = True,
) -> dict:
    """Freeze pre-kickoff predictions for eligible fixtures.

    Only fixtures whose kickoff is strictly after ``as_of`` AND with no
    known result are considered. ``(season, match_id, strategy)`` keys
    already present in ``append_to`` are skipped (append-only, no dupes).
    No I/O happens unless ``append_to`` is provided (and ``write`` is True).
    """
    strategy_list = tuple(strategies)
    result_rows_by_id = {
        r.get("match_id"): r for r in result_rows if r.get("match_id")
    }

    existing: set[tuple] = set()
    if append_to is not None:
        for rec in load_jsonl(append_to):
            existing.add((rec.get("season"), rec.get("match_id"), rec.get("strategy")))

    as_of_utc = _as_utc(as_of)

    kept: list[dict] = []
    n_result_known = 0
    n_kicked_off = 0
    n_unknown_kickoff = 0
    for fixture in sorted(fixtures, key=_fixture_sort_key):
        mid = fixture.get("match_id")
        if not mid:
            continue
        if mid in result_rows_by_id:
            n_result_known += 1
            continue
        try:
            kick = parse_kickoff(fixture.get("event_date"))
        except (ValueError, AttributeError):
            n_unknown_kickoff += 1
            continue
        if kick <= as_of_utc:
            n_kicked_off += 1
            continue
        kept.append(fixture)

    engines = build_engines(
        elo_ratings,
        canonical_results_file(data_dir, season),
        season,
        data_dir,
    )
    weights_files = {s: _weights_file_for(s) for s in strategy_list}

    records: list[dict] = []
    n_frozen = 0
    for fixture in kept:
        context = build_strict_prior_context(
            fixture, fixtures, elo_ratings, result_rows_by_id
        )
        for strategy in strategy_list:
            key = (season, fixture.get("match_id"), strategy)
            if key in existing:
                continue
            record = _build_record(
                season=season,
                fixture=fixture,
                strategy=strategy,
                engine=engines[strategy],
                context=context,
                elo_ratings=elo_ratings,
                elo_provenance=elo_provenance,
                weights_file=weights_files.get(strategy),
                as_of=as_of_utc,
            )
            records.append(record)
            existing.add(key)
            n_frozen += 1
            if append_to is not None and write:
                append_jsonl(append_to, record)

    return {
        "n_frozen": n_frozen,
        "n_reserved": len(kept),
        "n_skipped_result_known": n_result_known,
        "n_skipped_kicked_off": n_kicked_off,
        "n_skipped_unknown_kickoff": n_unknown_kickoff,
        "records": records,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Attach real results
# ═══════════════════════════════════════════════════════════════════════════════


def attach_results(
    *,
    season: str,
    fixtures_by_id: dict,
    result_rows: list[dict],
    result_files: list[str],
    result_log: str | os.PathLike | None,
    as_of: datetime | None = None,
    write: bool = True,
) -> dict:
    """Attach real results to the shadow log (idempotent per match_id).

    Result rows lacking either score are NEVER attached and never turned
    into a fabricated 0-0; they are reported as
    ``"not_attachable:missing_scores"``.
    """
    existing: set[str] = set()
    if result_log is not None:
        for rec in load_jsonl(result_log):
            if rec.get("season") == season and rec.get("match_id"):
                existing.add(rec["match_id"])

    source = os.path.basename(result_files[0]) if result_files else "results.json"
    known_at = _as_utc(as_of).isoformat()
    attached_at = now_utc().isoformat()

    n_attached = 0
    n_missing = 0
    n_duplicate = 0
    skipped: list[dict] = []

    for row in result_rows:
        mid = row.get("match_id")
        if not mid:
            continue
        hs = row.get("home_score")
        aws = row.get("away_score")
        if hs is None or aws is None:
            n_missing += 1
            skipped.append({"match_id": mid, "status": "not_attachable:missing_scores"})
            continue
        if mid in existing:
            n_duplicate += 1
            continue
        if hs > aws:
            outcome = "H"
        elif aws > hs:
            outcome = "A"
        else:
            outcome = "D"
        fixture = fixtures_by_id.get(mid) if fixtures_by_id else None
        status = (fixture or {}).get("status") or "finished"
        record = {
            "schema": SCHEMA_VERSION,
            "season": season,
            "match_id": mid,
            "home_score": hs,
            "away_score": aws,
            "outcome": outcome,
            "status": status,
            "result_known_at": known_at,
            "source": source,
            "attached_at": attached_at,
        }
        if result_log is not None and write:
            append_jsonl(result_log, record)
        existing.add(mid)
        n_attached += 1

    return {
        "n_attached": n_attached,
        "n_missing_scores": n_missing,
        "n_duplicate_skipped": n_duplicate,
        "skipped": skipped,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Reporting
# ═══════════════════════════════════════════════════════════════════════════════


def _metrics(probs: list[list[float]], actuals: list[int]) -> dict:
    from football_core.evaluation import (
        multi_class_brier,
        multi_class_ece,
        multi_class_log_loss,
    )

    if not probs:
        return {"n": 0, "status": "insufficient"}
    return {
        "n": len(probs),
        "log_loss": round(multi_class_log_loss(probs, actuals), 6),
        "brier": round(multi_class_brier(probs, actuals), 6),
        "ece": round(multi_class_ece(probs, actuals), 6),
    }


def _match_ll(probs: list[float], actual: int, eps: float = 1e-15) -> float:
    p = max(eps, min(1 - eps, probs[actual]))
    return -math.log(p)


def _paired_bootstrap(deltas: list[float], n_boot: int = N_BOOT, seed: int = BOOT_SEED) -> tuple[float, float, float]:
    """Paired percentile bootstrap on per-match delta series."""
    import numpy as np

    arr = np.asarray(deltas, dtype=float)
    n = arr.size
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    means = arr[idx].mean(axis=1)
    return (
        float(arr.mean()),
        float(np.percentile(means, 2.5)),
        float(np.percentile(means, 97.5)),
    )


_PREDICTION_PAIRS = (
    ("market_elo_equal", "production"),
    ("market_elo_prior", "production"),
    ("market_elo_equal", "market_elo_prior"),
)


def build_report(
    *,
    season: str,
    prediction_records: list[dict],
    result_records: list[dict],
) -> dict:
    """Pure report over already-loaded prediction/result records."""
    result_by_mid: dict[str, dict] = {}
    for rec in result_records:
        if rec.get("season") not in (None, season):
            continue
        if rec.get("outcome") in _OUTCOME_INDEX:
            result_by_mid[rec.get("match_id")] = rec

    by_strategy: dict[str, list[dict]] = {}
    for rec in prediction_records:
        if rec.get("season") not in (None, season):
            continue
        by_strategy.setdefault(rec.get("strategy"), []).append(rec)

    def _actual(mid: str) -> int:
        return _OUTCOME_INDEX[result_by_mid[mid]["outcome"]]

    def _probs(rec: dict) -> list[float]:
        p = rec.get("predicted", {})
        return [p.get("home", 0.0), p.get("draw", 0.0), p.get("away", 0.0)]

    # ── segments ──────────────────────────────────────────────────────────
    segment_predicates = (
        ("all", lambda rec: True),
        ("odds_available", lambda rec: bool(rec.get("odds_available"))),
        ("odds_unavailable", lambda rec: not bool(rec.get("odds_available"))),
    )
    segments: dict[str, dict] = {}
    for name, predicate in segment_predicates:
        strategies_out: dict[str, dict] = {}
        segment_mids: set[str] = set()
        for strategy in sorted(by_strategy):
            scored = [
                rec
                for rec in by_strategy[strategy]
                if predicate(rec) and rec.get("match_id") in result_by_mid
            ]
            probs = [_probs(rec) for rec in scored]
            actuals = [_actual(rec["match_id"]) for rec in scored]
            strategies_out[strategy] = _metrics(probs, actuals)
            segment_mids.update(rec["match_id"] for rec in scored)
        segments[name] = {"n": len(segment_mids), "strategies": strategies_out}

    # ── per-match paired comparisons ──────────────────────────────────────
    per_strategy_scored: dict[str, dict[str, tuple]] = {}
    for strategy, recs in by_strategy.items():
        per_strategy_scored[strategy] = {
            rec["match_id"]: (_probs(rec), _actual(rec["match_id"]))
            for rec in recs
            if rec.get("match_id") in result_by_mid
        }

    comparisons: dict[str, dict] = {}
    for first, second in _PREDICTION_PAIRS:
        key = f"{first}_vs_{second}"
        if first not in per_strategy_scored or second not in per_strategy_scored:
            comparisons[key] = {"verdict": "insufficient_evidence (n=0)", "n": 0}
            continue
        common = sorted(set(per_strategy_scored[first]) & set(per_strategy_scored[second]))
        n = len(common)
        if n < 30:
            comparisons[key] = {"verdict": f"insufficient_evidence (n={n})", "n": n}
            continue
        deltas = [
            _match_ll(*per_strategy_scored[second][mid])
            - _match_ll(*per_strategy_scored[first][mid])
            for mid in common
        ]
        mean, lo, hi = _paired_bootstrap(deltas)
        if lo > 0:
            verdict, preferred = "preferred", first
        elif hi < 0:
            verdict, preferred = "preferred", second
        else:
            verdict, preferred = "no_decision", None
        comparisons[key] = {
            "n": n,
            "mean_delta_ll": round(mean, 6),
            "ci95": [round(lo, 6), round(hi, 6)],
            "delta_interpretation": f"positive favours {first} (lower log loss)",
            "verdict": verdict,
            "preferred": preferred,
        }

    # ── breakdowns (n >= 10 else flagged insufficient) ────────────────────
    breakdowns: dict[str, dict] = {"by_season": {}, "by_matchday": {}}
    for label, key_fn in (
        ("by_season", lambda rec: rec.get("season")),
        ("by_matchday", lambda rec: rec.get("official_matchday")),
    ):
        groups: dict[Any, dict[str, list[dict]]] = {}
        for strategy, recs in by_strategy.items():
            for rec in recs:
                if rec.get("match_id") in result_by_mid:
                    groups.setdefault(key_fn(rec), {}).setdefault(strategy, []).append(rec)
        out: dict[str, dict] = {}
        for group_key, strat_recs in groups.items():
            entry: dict[str, dict] = {}
            for strategy, recs in sorted(strat_recs.items()):
                if len(recs) >= 10:
                    entry[strategy] = _metrics(
                        [_probs(rec) for rec in recs],
                        [_actual(rec["match_id"]) for rec in recs],
                    )
                else:
                    entry[strategy] = {"n": len(recs), "status": "insufficient"}
            out[str(group_key)] = entry
        breakdowns[label] = out

    # ── honesty / model config ────────────────────────────────────────────
    frozen_ids = {rec.get("match_id") for rec in prediction_records}
    scored_ids = {mid for mid in frozen_ids if mid in result_by_mid}
    honesty = {
        "n_prediction_records": len(prediction_records),
        "n_unique_fixtures_frozen": len(frozen_ids),
        "n_scored_fixtures": len(scored_ids),
        "n_pending_fixtures": len(frozen_ids - scored_ids),
        "n_attached_results": len(result_by_mid),
    }

    model_config: dict[str, dict] = {}
    for rec in prediction_records:
        strategy = rec.get("strategy")
        if strategy in model_config:
            continue
        cfg = rec.get("config", {}) or {}
        model_config[strategy] = {
            "weights_hash": cfg.get("weights_hash"),
            "weights_file": cfg.get("weights_file"),
            "engine_signals": cfg.get("engine_signals"),
        }

    return {
        "schema": SCHEMA_VERSION,
        "season": season,
        "meta": {
            "model_version": MODEL_VERSION,
            "strategies": sorted(by_strategy),
            "segments": ["all", "odds_available", "odds_unavailable"],
            "bootstrap": {"n_boot": N_BOOT, "seed": BOOT_SEED},
        },
        "segments": segments,
        "comparisons": comparisons,
        "breakdowns": breakdowns,
        "honesty": honesty,
        "model_config": model_config,
    }


def render_markdown(report: dict, *, fixture_count: int, score_counts: dict) -> str:
    """Human-readable markdown rendering of a report dict."""
    lines: list[str] = []
    season = report.get("season")
    lines.append(f"# Shadow Evaluation — UCL {season}")
    lines.append("")
    lines.append(f"- model version: `{report.get('meta', {}).get('model_version')}`")
    lines.append(f"- fixtures in store: {fixture_count}")
    lines.append(f"- results attached: {score_counts.get('attached', 0)}")
    honesty = report.get("honesty", {})
    lines.append(f"- prediction records: {honesty.get('n_prediction_records', 0)}")
    lines.append(f"- scored fixtures: {honesty.get('n_scored_fixtures', 0)}")
    lines.append(f"- pending fixtures: {honesty.get('n_pending_fixtures', 0)}")
    lines.append("")

    for segment in ("all", "odds_available", "odds_unavailable"):
        seg = report.get("segments", {}).get(segment)
        if not seg:
            continue
        lines.append(f"## Segment: {segment} (n={seg.get('n', 0)})")
        lines.append("")
        lines.append("| strategy | n | log_loss | brier | ece |")
        lines.append("|---|---:|---:|---:|---:|")
        for strategy, metrics in sorted(seg.get("strategies", {}).items()):
            lines.append(
                f"| {strategy} | {metrics.get('n', 0)} | "
                f"{metrics.get('log_loss', '')} | {metrics.get('brier', '')} | "
                f"{metrics.get('ece', '')} |"
            )
        lines.append("")

    lines.append("## Paired comparisons (95% paired bootstrap)")
    lines.append("")
    lines.append("| comparison | n | mean_delta_ll | ci95 | verdict |")
    lines.append("|---|---:|---:|---|---|")
    for key, comp in sorted(report.get("comparisons", {}).items()):
        ci = comp.get("ci95")
        ci_text = f"[{ci[0]}, {ci[1]}]" if ci else "—"
        lines.append(
            f"| {key} | {comp.get('n', 0)} | {comp.get('mean_delta_ll', '')} | "
            f"{ci_text} | {comp.get('verdict', '')} |"
        )
    lines.append("")

    lines.append("## Model / config version")
    lines.append("")
    lines.append("| strategy | weights_file | weights_hash |")
    lines.append("|---|---|---|")
    for strategy, cfg in sorted(report.get("model_config", {}).items()):
        lines.append(
            f"| {strategy} | {cfg.get('weights_file')} | {cfg.get('weights_hash')} |"
        )
    lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════


def _read_season(data_dir: str, season: str) -> tuple[list[dict], list[dict]]:
    fixtures_doc = load_json(canonical_fixtures_file(data_dir, season)) or {}
    results_doc = load_json(canonical_results_file(data_dir, season)) or {}
    fixtures = fixtures_doc.get("fixtures", []) if isinstance(fixtures_doc, dict) else []
    matches = results_doc.get("matches", []) if isinstance(results_doc, dict) else []
    return list(fixtures), list(matches)


def _teams_from_fixtures(fixtures: list[dict]) -> list[str]:
    names: list[str] = []
    for fixture in fixtures:
        for key in ("team_a", "team_b"):
            name = fixture.get(key)
            if name and name not in names:
                names.append(name)
    return names


def _default_predictions_path(season: str) -> str:
    return str(shadow_season_dir(season) / "predictions.jsonl")


def _default_results_path(season: str) -> str:
    return str(shadow_season_dir(season) / "results.jsonl")


def _cmd_freeze(args: argparse.Namespace) -> int:
    fixtures, result_rows = _read_season(args.data_dir, args.season)
    elo_ratings, elo_provenance = resolve_elo(
        _teams_from_fixtures(fixtures),
        elo_file=args.elo_file,
        use_live=args.live_elo,
        data_dir=args.data_dir,
        season=args.season,
    )
    as_of = parse_kickoff(args.as_of) if args.as_of else now_utc()
    out = args.out or _default_predictions_path(args.season)
    stats = freeze_predictions(
        season=args.season,
        fixtures=fixtures,
        result_rows=result_rows,
        elo_ratings=elo_ratings,
        as_of=as_of,
        data_dir=args.data_dir,
        append_to=out,
        elo_provenance=elo_provenance,
        write=not args.dry_run,
    )
    if not args.dry_run:
        ensure_shadow_schema(args.season)
    print(
        f"[freeze]{' (dry-run)' if args.dry_run else ''} season={args.season} "
        f"frozen={stats['n_frozen']} reserved={stats['n_reserved']} "
        f"skipped_result_known={stats['n_skipped_result_known']} "
        f"skipped_kicked_off={stats['n_skipped_kicked_off']} "
        f"skipped_unknown_kickoff={stats['n_skipped_unknown_kickoff']} "
        f"elo_source={elo_provenance.get('source')} out={out}"
    )
    return 0


def _cmd_attach(args: argparse.Namespace) -> int:
    fixtures, result_rows = _read_season(args.data_dir, args.season)
    fixtures_by_id = {f.get("match_id"): f for f in fixtures if f.get("match_id")}
    as_of = parse_kickoff(args.as_of) if args.as_of else None
    out = args.out or _default_results_path(args.season)
    stats = attach_results(
        season=args.season,
        fixtures_by_id=fixtures_by_id,
        result_rows=result_rows,
        result_files=[canonical_results_file(args.data_dir, args.season)],
        result_log=out,
        as_of=as_of,
        write=not args.dry_run,
    )
    print(
        f"[attach]{' (dry-run)' if args.dry_run else ''} season={args.season} "
        f"attached={stats['n_attached']} missing_scores={stats['n_missing_scores']} "
        f"duplicate_skipped={stats['n_duplicate_skipped']} out={out}"
    )
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    fixtures, _ = _read_season(args.data_dir, args.season)
    predictions_path = str(shadow_season_dir(args.season) / "predictions.jsonl")
    results_path = str(shadow_season_dir(args.season) / "results.jsonl")
    prediction_records = load_jsonl(predictions_path)
    result_records = load_jsonl(results_path)
    report = build_report(
        season=args.season,
        prediction_records=prediction_records,
        result_records=result_records,
    )
    out = args.out or str(shadow_season_dir(args.season) / "report.json")
    out_path = Path(out)
    _atomic_write_json(report, out_path)
    markdown = render_markdown(
        report,
        fixture_count=len(fixtures),
        score_counts={"attached": report["honesty"]["n_attached_results"]},
    )
    md_path = out_path.parent / "SHADOW_EVALUATION.md"
    _atomic_write_text(md_path, markdown)
    print(
        f"[report] season={args.season} predictions={len(prediction_records)} "
        f"results={len(result_records)} wrote={out_path} md={md_path}"
    )
    return 0


# ═══════════════════════════════════════════════════════════════════════════════
# Refreeze production (Phase 6 — _ReplayResultProvider correctness fix)
# ═══════════════════════════════════════════════════════════════════════════════


def refreeze_production(
    *,
    season: str,
    prediction_records: list[dict],
    fixtures: list[dict],
    result_rows: list[dict],
    as_of_batches: dict[str, datetime],
    data_dir: str,
    write: bool = True,
    out_predictions_path: str | None = None,
    out_manifest_path: str | None = None,
) -> dict:
    """Re-freeze only ``production`` records after the Phase 6 provider fix.

    * Candidate (non-production) records are kept byte-identical.
    * Each production record's ``prediction_timestamp`` is PRESERVED.
    * ``as_of_batches`` maps ``prediction_timestamp -> datetime`` used to
      filter result_rows for that re-freeze group (only results with
      fixture ``event_date`` strictly before the ``as_of``).
    * elo_ratings for each record are reconstructed from the stored
      ``provenance.elo.home``/``provenance.elo.away``.
    * A ``recomputed`` block is added to every changed record.
    * Returns manifest dict with counts, hashes, changed/unchanged lists.
    """
    fixtures_by_id: dict[str, dict] = {f.get("match_id"): f for f in fixtures if f.get("match_id")}
    result_rows_by_id: dict[str, dict] = {r.get("match_id"): r for r in result_rows if r.get("match_id")}

    prod_records = [r for r in prediction_records if r.get("strategy") == "production"]
    cand_records = [r for r in prediction_records if r.get("strategy") != "production"]

    # Candidate hash: byte-identical serialisation of non-production records.
    def _rec_canonical(rec: dict) -> str:
        return json.dumps(rec, sort_keys=True, separators=(",", ":"))

    cand_lines_before = [_rec_canonical(r) for r in cand_records]
    cand_hash_before = hashlib.sha256(
        "".join(cand_lines_before).encode("utf-8")
    ).hexdigest()

    # Group production records by prediction_timestamp.
    groups: dict[str, list[dict]] = {}
    for rec in prod_records:
        ts = rec.get("prediction_timestamp", "")
        groups.setdefault(ts, []).append(rec)

    # For each group, re-freeze all records using that group's as_of.
    from football_core.constants import DEFAULT_ELO
    from competitions.ucl.src.orchestrator import build_signal_engine

    result_file = canonical_results_file(data_dir, season)

    changed_records: list[dict] = []
    unchanged_records: list[str] = []
    skipped_fixture_changed = 0
    skipped_result_now_known = 0
    not_found = 0

    new_prod_records: list[dict] = []

    for ts_key, recs in groups.items():
        as_of = as_of_batches.get(ts_key)
        if as_of is None:
            as_of = parse_kickoff(ts_key) if ts_key else now_utc()

        # Filter result_rows to those with fixture event_date strictly before as_of.
        as_of_dt = _as_utc(as_of)
        filtered_results: list[dict] = []
        for row in result_rows:
            mid = row.get("match_id")
            fix = fixtures_by_id.get(mid) if mid else None
            if fix is None:
                continue
            try:
                kick = parse_kickoff(fix.get("event_date"))
            except (ValueError, AttributeError):
                continue
            if kick < as_of_dt:
                enriched = dict(row)
                ed = fix.get("event_date")
                if ed:
                    enriched["event_date"] = ed
                filtered_results.append(enriched)

        # Build filtered results file for the replay provider.
        import tempfile
        tmp_fd, tmp_results_path = tempfile.mkstemp(suffix=".json", prefix="refreeze_results_")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(filtered_results, f)

            for rec in recs:
                mid = rec.get("match_id")
                fix = fixtures_by_id.get(mid)

                # Guard: fixture must still exist and match teams/kickoff.
                if fix is None:
                    not_found += 1
                    new_prod_records.append(rec)
                    continue

                stored_home = rec.get("home_team", "")
                stored_away = rec.get("away_team", "")
                if fix.get("team_a") != stored_home or fix.get("team_b") != stored_away:
                    skipped_fixture_changed += 1
                    new_prod_records.append(rec)
                    continue

                try:
                    stored_kick = parse_kickoff(rec.get("kickoff"))
                    current_kick = parse_kickoff(fix.get("event_date"))
                    if stored_kick != current_kick:
                        skipped_fixture_changed += 1
                        new_prod_records.append(rec)
                        continue
                except (ValueError, AttributeError):
                    skipped_fixture_changed += 1
                    new_prod_records.append(rec)
                    continue

                # Guard: skip if result is now known (no fabrication).
                if mid in result_rows_by_id:
                    skipped_result_now_known += 1
                    new_prod_records.append(rec)
                    continue

                # Reconstruct elo_ratings from this record's stored provenance.
                elo_prov = (rec.get("provenance") or {}).get("elo") or {}
                home_elo_val = elo_prov.get("home", float(DEFAULT_ELO))
                away_elo_val = elo_prov.get("away", float(DEFAULT_ELO))
                elo_ratings = {
                    stored_home: float(home_elo_val),
                    stored_away: float(away_elo_val),
                }

                # Build engine with the filtered results for this group.
                engine = build_signal_engine(
                    elo_ratings,
                    results_file=tmp_results_path,
                    strategy="production",
                )

                # Build strict-prior context for this fixture.
                context = build_strict_prior_context(
                    fix, fixtures, elo_ratings, result_rows_by_id,
                )

                # Fresh evaluation.
                match = make_target_match(fix)
                blended = engine.evaluate(match, context)
                new_predicted = _round_probs(
                    blended.home_prob, blended.draw_prob, blended.away_prob,
                )

                # Detect if probs actually changed.
                old_predicted = rec.get("predicted", {})
                probs_changed = (
                    new_predicted.get("home") != old_predicted.get("home")
                    or new_predicted.get("draw") != old_predicted.get("draw")
                    or new_predicted.get("away") != old_predicted.get("away")
                )

                if not probs_changed:
                    unchanged_records.append(mid)
                    new_prod_records.append(rec)
                    continue

                # Capture old rolling_form weights from signal breakdown if present.
                old_rf_weights = None
                new_rf_weights = None
                old_signals = (rec.get("provenance") or {}).get("signals") or {}
                if "rolling_form" in old_signals:
                    old_rf_weights = old_signals["rolling_form"].get("weights")

                new_signals = dict(blended.signal_breakdown)
                if "rolling_form" in new_signals:
                    new_rf_weights = new_signals["rolling_form"].get("weights")

                # Build new record preserving prediction_timestamp.
                new_rec = dict(rec)
                new_rec["predicted"] = new_predicted
                new_rec["provenance"] = {
                    "signals": new_signals,
                    "market_elo": (rec.get("provenance") or {}).get("market_elo"),
                    "elo": dict(elo_prov),
                    "fallback": (rec.get("provenance") or {}).get("fallback"),
                }
                new_rec["config"] = dict(rec.get("config", {}))
                new_rec["odds_available"] = rec.get("odds_available")
                new_rec["odds"] = rec.get("odds")
                new_rec["recomputed"] = {
                    "reason": "phase6_replay_provider_fix",
                    "phase": 6,
                    "preserved_prediction_timestamp": True,
                    "as_of_used": _as_utc(as_of).isoformat(),
                }

                changed_records.append({
                    "match_id": mid,
                    "old_predicted": old_predicted,
                    "new_predicted": new_predicted,
                    "old_rolling_form_weights": old_rf_weights,
                    "new_rolling_form_weights": new_rf_weights,
                })
                new_prod_records.append(new_rec)
        finally:
            try:
                os.unlink(tmp_results_path)
            except OSError:
                pass

    # Reconstruct full output: candidates (unchanged) + new production records.
    # Preserve original order: candidates first in their original order,
    # then production records in the order they appeared.
    cand_by_key: dict[tuple, dict] = {}
    for r in cand_records:
        k = (r.get("season"), r.get("match_id"), r.get("strategy"))
        cand_by_key[k] = r

    # Build output preserving original record order.
    output_records: list[dict] = []
    seen_prod_ids: set[int] = set()  # track by id() to place each new rec once
    for rec in prediction_records:
        if rec.get("strategy") != "production":
            output_records.append(rec)
        else:
            # Find the corresponding new record.
            mid = rec.get("match_id")
            ts = rec.get("prediction_timestamp")
            placed = False
            for nr in new_prod_records:
                if (
                    nr.get("match_id") == mid
                    and nr.get("prediction_timestamp") == ts
                    and id(nr) not in seen_prod_ids
                ):
                    output_records.append(nr)
                    seen_prod_ids.add(id(nr))
                    placed = True
                    break
            if not placed:
                output_records.append(rec)

    # Candidate hash after (should be identical).
    cand_lines_after = [_rec_canonical(r) for r in output_records if r.get("strategy") != "production"]
    cand_hash_after = hashlib.sha256(
        "".join(cand_lines_after).encode("utf-8")
    ).hexdigest()

    # Serialise the full output once; hash it for post-hoc verification.
    # Text-mode writes translate "\n" to os.linesep, so hash the exact bytes
    # that will land on disk (portable across platforms).
    lines_text = "\n".join(
        json.dumps(r, sort_keys=True, ensure_ascii=False) for r in output_records
    ) + "\n"
    newline_bytes = os.linesep.encode("utf-8")
    predictions_file_line_hash = hashlib.sha256(
        lines_text.encode("utf-8").replace(b"\n", newline_bytes)
    ).hexdigest()

    # Write predictions.jsonl atomically.
    if write:
        preds_path = out_predictions_path or _default_predictions_path(season)
        _atomic_write_text(Path(preds_path), lines_text)

    # Build and write manifest.
    manifest = {
        "schema": 1,
        "phase": 6,
        "reason": "_ReplayResultProvider fix (dedupe + event_date fallback)",
        "generated_at": now_utc().isoformat(),
        "counts": {
            "changed": len(changed_records),
            "unchanged": len(unchanged_records),
            "skipped_fixture_changed": skipped_fixture_changed,
            "skipped_result_now_known": skipped_result_now_known,
            "not_found": not_found,
        },
        "candidate_records_hash_before": "sha256:" + cand_hash_before,
        "candidate_records_hash_after": "sha256:" + cand_hash_after,
        "predictions_file_line_hash": "sha256:" + predictions_file_line_hash,
        "changed_records": changed_records,
        "unchanged_records": unchanged_records,
    }

    if write:
        manifest_path = out_manifest_path or str(
            shadow_season_dir(season) / "refreeze_manifest.json"
        )
        _atomic_write_json(manifest, Path(manifest_path))

    return manifest


def _cmd_refreeze_production(args: argparse.Namespace) -> int:
    fixtures, result_rows = _read_season(args.data_dir, args.season)
    predictions_path = _default_predictions_path(args.season)
    prediction_records = load_jsonl(predictions_path)

    if not prediction_records:
        print(f"[refreeze-production] no prediction records found for {args.season}")
        return 0

    # Build as_of_batches: map each unique prediction_timestamp to a datetime.
    as_of_batches: dict[str, datetime] = {}
    for rec in prediction_records:
        ts = rec.get("prediction_timestamp", "")
        if ts and ts not in as_of_batches:
            try:
                as_of_batches[ts] = parse_kickoff(ts)
            except (ValueError, AttributeError):
                as_of_batches[ts] = now_utc()

    manifest = refreeze_production(
        season=args.season,
        prediction_records=prediction_records,
        fixtures=fixtures,
        result_rows=result_rows,
        as_of_batches=as_of_batches,
        data_dir=args.data_dir,
        write=not args.dry_run,
        out_manifest_path=args.out,
    )

    counts = manifest["counts"]
    hash_match = manifest["candidate_records_hash_before"] == manifest["candidate_records_hash_after"]
    print(
        f"[refreeze-production]{' (dry-run)' if args.dry_run else ''} "
        f"season={args.season} "
        f"changed={counts['changed']} unchanged={counts['unchanged']} "
        f"skipped_fixture_changed={counts['skipped_fixture_changed']} "
        f"skipped_result_now_known={counts['skipped_result_now_known']} "
        f"not_found={counts['not_found']} "
        f"candidate_hash_match={hash_match}"
    )
    if manifest["changed_records"]:
        for cr in manifest["changed_records"][:2]:
            print(
                f"  {cr['match_id']}: "
                f"old={cr['old_predicted']} new={cr['new_predicted']}"
            )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shadow_eval",
        description="LIVE SHADOW EVALUATION — frozen pre-kickoff predictions for UCL.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    freeze = sub.add_parser("freeze", help="freeze pre-kickoff predictions")
    freeze.add_argument("--season", required=True)
    freeze.add_argument("--data-dir", default=DATA_DIR)
    freeze.add_argument("--elo-file", default=None)
    freeze.add_argument("--live-elo", action="store_true")
    freeze.add_argument("--as-of", default=None)
    freeze.add_argument("--dry-run", action="store_true")
    freeze.add_argument("--out", default=None)
    freeze.set_defaults(func=_cmd_freeze)

    attach = sub.add_parser("attach", help="attach real results")
    attach.add_argument("--season", required=True)
    attach.add_argument("--data-dir", default=DATA_DIR)
    attach.add_argument("--as-of", default=None)
    attach.add_argument("--dry-run", action="store_true")
    attach.add_argument("--out", default=None)
    attach.set_defaults(func=_cmd_attach)

    report = sub.add_parser("report", help="build report + markdown")
    report.add_argument("--season", required=True)
    report.add_argument("--data-dir", default=DATA_DIR)
    report.add_argument("--out", default=None)
    report.set_defaults(func=_cmd_report)

    refreeze = sub.add_parser("refreeze-production", help="re-freeze production records after provider fix")
    refreeze.add_argument("--season", required=True)
    refreeze.add_argument("--data-dir", default=DATA_DIR)
    refreeze.add_argument("--dry-run", action="store_true")
    refreeze.add_argument("--out", default=None)
    refreeze.set_defaults(func=_cmd_refreeze_production)

    return parser


def main(argv: list[str] | None = None) -> int:
    if _verbose():
        logging.basicConfig(level=logging.INFO)
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
