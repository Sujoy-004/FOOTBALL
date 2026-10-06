"""Golden parity test for ``compute_full_bracket``.

The bracket is rebuilt from fixtures committed to git — never from
``competitions/worldcup/data/``, which is gitignored and absent on a clean
clone. The test therefore reproduces identically on a clean clone, a dirty
worktree, and CI, with no network access and no environment variables.

``compute_full_bracket`` is imported from ``web.wc_app`` deliberately. Plan
01-05 relocates the implementation into ``competitions/worldcup/src/bracket.py``
but the web module keeps re-exporting it, so the web path is stable on both
sides of the move. A failure here after that move means the computed output
actually changed, not merely that an import path did.

``golden_bracket.json`` is written by hand only through an explicit generation
step; this module compares against it and never rewrites it.
"""

from __future__ import annotations

import json
import pathlib

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "wc_bracket"

# Reasons ``_prob_availability`` in ``web/wc_app.py`` can return for an
# unavailable probability. Read from the implementation, not guessed.
UNAVAILABLE_REASONS = {"slot_unresolved", "no_elo_rating"}


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _compute() -> dict:
    from web.wc_app import compute_full_bracket

    return compute_full_bracket(
        groups=_load("groups.json"),
        teams=_load("teams.json"),
        bracket=_load("bracket.json"),
        annex_c=_load("annex_c.json"),
        played=_load("played.json"),
        played_groups=_load("played_groups.json"),
        engine_predictions=None,
    )


def _golden() -> dict:
    return _load("golden_bracket.json")


def _flatten(golden: dict) -> dict[str, list[dict]]:
    """Round code -> matches sorted by match_id, so dict order never matters."""
    return {
        round_code: sorted(matches, key=lambda m: m["match_id"])
        for round_code, matches in golden["rounds"].items()
    }


def _all_matches(result: dict) -> list[dict]:
    return [m for matches in result["rounds"].values() for m in matches]


def test_rounds_data_matches_golden_exactly():
    result = _compute()
    golden = _golden()

    assert sorted(result["rounds"]) == sorted(golden["rounds"])
    assert result["n_matchups"] == golden["n_matchups"]
    assert _flatten(result) == _flatten(golden)


def test_golden_pins_played_match_truth_fields():
    matches = _all_matches(_golden())
    played = [m for m in matches if m["status"] in ("played", "played_pens")]

    assert played, "fixture must pin at least one decided knockout match"
    for m in played:
        assert m["winner"], f"{m['match_id']} is played but carries no winner"
        assert m["score"] is not None, f"{m['match_id']} is played but carries no score"
        # Factual provenance only — a simulated result must never appear here.
        assert m["provenance"] in ("official", "manual"), m["match_id"]
        assert m["provenance"] != "simulated", m["match_id"]


def test_golden_pins_unavailable_probability_reasons():
    matches = _all_matches(_golden())
    unavailable = [m for m in matches if m["prob_available"] is False]

    assert unavailable, "fixture must pin at least one unavailable probability"
    for m in unavailable:
        assert m["prob_reason"] in UNAVAILABLE_REASONS, m["match_id"]


def test_every_fixture_round_survives_bucket_ordering():
    from competitions.worldcup.src.pipeline import bracket_stage_order

    order = bracket_stage_order()
    assert order == ["R32", "R16", "QF", "SF", "TPP", "FINAL"]

    golden = _golden()
    fixture_rounds = {e["round"] for e in _load("bracket.json")}
    for round_code in fixture_rounds:
        assert round_code in order, f"{round_code} is not a canonical round code"

    populated = [r for r in order if golden["rounds"].get(r)]
    assert populated, "golden must bucket at least one round"
    for round_code in populated:
        assert golden["rounds"][round_code], round_code

    # A round whose code is not in bracket_stage_order() is dropped from
    # rounds_data entirely, so an empty bucket means the fixture lost a round.
    for round_code in fixture_rounds:
        assert golden["rounds"].get(round_code), (
            f"fixture round {round_code} was silently dropped from rounds_data"
        )
    assert populated == [r for r in order if golden["rounds"].get(r)]
    assert set(golden["rounds"]) == set(order)
