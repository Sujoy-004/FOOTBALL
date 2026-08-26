"""Offline backfill — restore 2025/26 UCL knockout history into store v2.

Purely explicit one-shot command; NEVER invoked by server startup::

    python -m competitions.ucl.backfill [--data-dir PATH]

Reads ``bootstrap/2025_26_knockout_results.json`` (v1 historical aggregates
extracted byte-identical from git 7cbc0f6) from the data dir and writes
``knockout_results.json`` AS SCHEMA V2 with:

- canonical match_ids: ``playoff_tN`` for playoffs; R16 ids resolved by
  walking ``bracket_rules.json`` from the known playoff winners (each
  ``r16_NN`` slot receives the playoff winner named by its
  ``away_playoff_tie``); QF/SF/FINAL ids resolved by walking the
  ``source_matches`` chain; ``final_01`` for the final;
- ``legs=null`` everywhere (historical ties are aggregate-only records);
- ``provenance="manual"`` EVERYWHERE — honest labeling: hand-recorded
  historical aggregates without independent verification;
- ``status="played"`` for decided two-legged ties, ``"played_pens"`` for
  the penalty-decided final;
- champion PSG and ``meta.backfilled_from = "bootstrap/
  2025_26_knockout_results.json (git 7cbc0f6)"``.

Validates counts (8/8/4/2/1 + champion) before writing; refuses partial
writes (single atomic replace, nothing touched on validation failure).

Exit codes: 0 success, 1 failure (missing/unreadable bootstrap, unresolvable
bracket mapping, or count validation mismatch).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):  # allow direct-script execution fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from competitions.ucl.src.ingest import BACKFILL_SOURCE_TAG, _atomic_write_json, write_knockout_store


class BackfillError(Exception):
    """Bootstrap cannot be converted completely — refuse to write."""


def _manual_tie(
    match_id: str,
    round_: str,
    entry_a: str | None,
    entry_b: str | None,
    agg_a: int | None,
    agg_b: int | None,
    winner: str | None,
    *,
    tie_num: int | None = None,
    quarter: int | None = None,
    slot_sources: dict | None = None,
    source_matches: list[str] | None = None,
) -> dict:
    out = {
        "match_id": match_id,
        "round": round_,
        "quarter": quarter,
        "team_a": entry_a,
        "team_b": entry_b,
        "slot_sources": slot_sources,
        "source_matches": source_matches,
        # Historical aggregates carry no leg detail — never fabricate any.
        "legs": None,
        "aggregate_a": agg_a,
        "aggregate_b": agg_b,
        "et_played": False,
        "et_a": 0,
        "et_b": 0,
        "penalties_played": False,
        "penalty_a": 0,
        "penalty_b": 0,
        "penalty_winner": None,
        "winner": winner or None,
        "status": "played" if winner else "unknown",
        "provenance": "manual",
    }
    if tie_num is not None:
        out["tie_num"] = tie_num
    return out


def _convert_bootstrap(bootstrap: dict, pairings: dict, rules: dict) -> dict:
    """Convert a v1 bootstrap payload into a validated v2 document."""
    b = bootstrap.get("matches") or {}
    rounds_v1 = b.get("rounds") or {}

    pair_by_tie = {int(p["tie"]): p for p in pairings.get("pairings", [])}

    playoff = []
    playoff_winners: dict[int, str] = {}
    for e in sorted(b.get("playoff") or [], key=lambda x: x.get("tie_num", 0)):
        tie_num = int(e["tie_num"])
        template = pair_by_tie.get(tie_num)
        slot_sources = (
            {"position_a": template["position_a"], "position_b": template["position_b"]}
            if template else None
        )
        winner = e.get("winner") or None
        if winner:
            playoff_winners[tie_num] = winner
        playoff.append(_manual_tie(
            f"playoff_t{tie_num}", "playoff",
            e.get("team_a"), e.get("team_b"),
            e.get("aggregate_a", e.get("score_a")),
            e.get("aggregate_b", e.get("score_b")),
            winner,
            tie_num=tie_num,
            slot_sources=slot_sources,
        ))
    if len(playoff) != 8:
        raise BackfillError(f"expected 8 playoff ties, found {len(playoff)}")

    rules_by_id = {m["match_id"]: m for m in rules.get("matches", [])}
    r16_rule_ids = [m["match_id"] for m in rules.get("matches", []) if m.get("round") == "R16"]

    remaining_r16 = [dict(e) for e in (rounds_v1.get("R16") or [])]
    r16: list[dict] = []
    r16_winners: dict[str, str] = {}
    for rid in r16_rule_ids:
        rule = rules_by_id[rid]
        expected_winner = playoff_winners.get(rule.get("away_playoff_tie"))
        match_entry = next(
            (e for e in remaining_r16
             if expected_winner and expected_winner in (e.get("team_a"), e.get("team_b"))),
            None,
        )
        if match_entry is None:
            raise BackfillError(
                f"cannot resolve {rid}: no bootstrap R16 entry contains "
                f"playoff-tie-{rule.get('away_playoff_tie')} winner {expected_winner!r}"
            )
        remaining_r16.remove(match_entry)
        other = (
            match_entry["team_b"] if match_entry.get("team_a") == expected_winner
            else match_entry["team_a"]
        )
        winner = match_entry.get("winner") or None
        if winner:
            r16_winners[rid] = winner
        r16.append(_manual_tie(
            rid, "R16", other, expected_winner,
            match_entry.get("score_a"), match_entry.get("score_b"),
            winner,
            quarter=rule.get("quarter"),
            slot_sources={
                "home_seed": rule.get("home_seed"),
                "away_playoff_tie": rule.get("away_playoff_tie"),
            },
        ))
    if len(r16) != 8:
        raise BackfillError(f"expected 8 R16 ties, resolved {len(r16)}")
    if remaining_r16:
        raise BackfillError(f"{len(remaining_r16)} bootstrap R16 entries could not be mapped")

    def _convert_source_round(round_name: str, pool_v1: list[dict]) -> tuple[list[dict], dict[str, str]]:
        pool = [dict(e) for e in pool_v1]
        converted: list[dict] = []
        winners: dict[str, str] = {}
        rule_ids = [m["match_id"] for m in rules.get("matches", []) if m.get("round") == round_name]
        for rid in rule_ids:
            rule = rules_by_id[rid]
            sources = rule.get("source_matches") or []
            expected_pair = {upstream[s] for s in sources if s in upstream}
            entry = next(
                (e for e in pool if {e.get("team_a"), e.get("team_b")} == expected_pair),
                None,
            )
            if entry is None:
                raise BackfillError(
                    f"cannot resolve {rid}: no bootstrap {round_name} entry matches "
                    f"source winners {sorted(expected_pair)!r}"
                )
            pool.remove(entry)
            winner = entry.get("winner") or None
            if winner:
                winners[rid] = winner
            converted.append(_manual_tie(
                rid, round_name, entry.get("team_a"), entry.get("team_b"),
                entry.get("score_a"), entry.get("score_b"),
                winner,
                quarter=rule.get("quarter"),
                source_matches=sources,
            ))
        if pool:
            raise BackfillError(f"{len(pool)} bootstrap {round_name} entries could not be mapped")
        return converted, winners

    upstream: dict[str, str] = dict(r16_winners)
    qf, qf_winners = _convert_source_round("QF", rounds_v1.get("QF") or [])
    upstream.update(qf_winners)
    sf, sf_winners = _convert_source_round("SF", rounds_v1.get("SF") or [])
    upstream.update(sf_winners)
    if len(qf) != 4:
        raise BackfillError(f"expected 4 QF ties, resolved {len(qf)}")
    if len(sf) != 2:
        raise BackfillError(f"expected 2 SF ties, resolved {len(sf)}")

    final_v1_list = rounds_v1.get("FINAL") or []
    if len(final_v1_list) != 1:
        raise BackfillError(f"expected exactly 1 FINAL entry, found {len(final_v1_list)}")
    final_v1 = final_v1_list[0]
    final_rule = rules_by_id.get("final_01", {})
    final_sources = final_rule.get("source_matches") or ["sf_01", "sf_02"]
    expected_final_pair = {upstream[s] for s in final_sources if s in upstream}
    actual_final_pair = {final_v1.get("team_a"), final_v1.get("team_b")}
    if expected_final_pair != actual_final_pair:
        raise BackfillError(
            f"FINAL teams {sorted(actual_final_pair)!r} do not match SF winners "
            f"{sorted(expected_final_pair)!r}"
        )
    pens = final_v1.get("penalties") or {}
    penalties_played = bool(pens or final_v1.get("penalties_played"))
    final_winner = final_v1.get("winner") or None
    final_entry = {
        "match_id": "final_01",
        "round": "FINAL",
        "team_a": final_v1.get("team_a"),
        "team_b": final_v1.get("team_b"),
        "score": {"home": final_v1.get("score_a"), "away": final_v1.get("score_b")},
        "et_played": bool(final_v1.get("et_played", False)),
        "et_a": int(final_v1.get("et_a", 0) or 0),
        "et_b": int(final_v1.get("et_b", 0) or 0),
        "penalties_played": penalties_played,
        "penalty_winner": pens.get("winner") or final_v1.get("penalty_winner"),
        "penalty_score": pens.get("score") or final_v1.get("penalty_score"),
        "winner": final_winner,
        "status": "played_pens" if penalties_played else "played",
        "provenance": "manual",
        "source_matches": final_sources,
    }

    champion = (b.get("champion") or final_winner) or None
    if champion != final_winner:
        raise BackfillError(
            f"bootstrap champion {champion!r} does not match FINAL winner {final_winner!r}"
        )

    return {
        "schema": 2,
        "matches": {
            "playoff": playoff,
            "rounds": {"R16": r16, "QF": qf, "SF": sf},
            "final": [final_entry],
            "champion": champion,
        },
        "meta": {
            "provider": None,
            "backfilled_from": BACKFILL_SOURCE_TAG,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def run_backfill(data_dir: str | Path) -> dict:
    """Convert + validate + atomically write. Returns the v2 document.

    Raises BackfillError (or OSError) without touching the target file when
    validation fails.
    """
    dp = Path(data_dir) if isinstance(data_dir, str) else data_dir
    bootstrap_path = dp / "bootstrap" / "2025_26_knockout_results.json"
    if not bootstrap_path.exists():
        raise BackfillError(f"bootstrap file not found: {bootstrap_path}")
    try:
        bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise BackfillError(f"bootstrap file unreadable: {exc}") from exc

    pairings_path = dp / "playoff_pairings.json"
    rules_path = dp / "bracket_rules.json"
    try:
        pairings = json.loads(pairings_path.read_text(encoding="utf-8"))
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise BackfillError(f"bracket template unreadable: {exc}") from exc

    document = _convert_bootstrap(bootstrap, pairings, rules)

    matches = document["matches"]
    counts = (
        len(matches["playoff"]),
        len(matches["rounds"]["R16"]),
        len(matches["rounds"]["QF"]),
        len(matches["rounds"]["SF"]),
        len(matches["final"]),
    )
    if counts != (8, 8, 4, 2, 1) or not matches["champion"]:
        raise BackfillError(
            f"validation failed: counts={counts} (want (8, 8, 4, 2, 1)), "
            f"champion={matches['champion']!r}"
        )

    write_knockout_store(dp, document)
    return document


def main(argv: list[str] | None = None) -> int:
    default_data_dir = Path(__file__).resolve().parent / "data"
    parser = argparse.ArgumentParser(
        prog="python -m competitions.ucl.backfill",
        description="Offline backfill of 2025/26 UCL knockout history into store v2.",
    )
    parser.add_argument(
        "--data-dir", default=str(default_data_dir),
        help=f"UCL data directory (default: {default_data_dir})",
    )
    args = parser.parse_args(argv)

    print(f"[ucl-backfill] data dir: {args.data_dir}")
    try:
        document = run_backfill(args.data_dir)
    except (BackfillError, OSError) as exc:
        print(f"[ucl-backfill] FAILED: {exc}")
        return 1

    matches = document["matches"]
    print("[ucl-backfill] wrote knockout_results.json (schema 2)")
    print(f"  playoff : {len(matches['playoff'])} ties")
    print(f"  R16     : {len(matches['rounds']['R16'])} ties")
    print(f"  QF      : {len(matches['rounds']['QF'])} ties")
    print(f"  SF      : {len(matches['rounds']['SF'])} ties")
    print(f"  final   : {len(matches['final'])} match")
    print(f"  champion: {matches['champion']}")
    print(f"  provenance: manual (all); backfilled_from: {document['meta']['backfilled_from']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
