"""Tests for the backfill canonical team-key mapping."""

from __future__ import annotations

import pytest

from competitions.ucl.historical_backfill.team_map import canonical, is_known

# (source spelling, expected canonical production key)
EXPECTED: tuple[tuple[str, str], ...] = (
    ("Dortmund", "Borussia Dortmund"),
    ("Borussia Dortmund", "Borussia Dortmund"),
    ("Bayern München", "Bayern Munich"),
    ("Bayern", "Bayern Munich"),
    ("PSG", "Paris Saint-Germain"),
    ("Paris Saint-Germain", "Paris Saint-Germain"),
    ("Inter", "Inter Milan"),
    ("Inter Milan", "Inter Milan"),
    ("Man City", "Manchester City"),
    ("Manchester City", "Manchester City"),
    ("PSV", "PSV Eindhoven"),
    ("Sporting", "Sporting CP"),
    ("Olympiakos Piraeus", "Olympiacos"),
    ("Club Brugge KV", "Club Brugge"),
    ("Tottenham Hotspur", "Tottenham"),
    ("Crvena Zvezda", "Red Star Belgrade"),
    ("FK Crvena Zvezda", "Red Star Belgrade"),
    ("Dinamo Kiev", "Dynamo Kyiv"),
    ("Bor. Mönchengladbach", "Borussia Monchengladbach"),
    ("Olympique Marseille", "Marseille"),
    ("Sporting Clube de Braga", "Braga"),
    ("1. FC Union Berlin", "Union Berlin"),
    ("Racing Club de Lens", "Lens"),
    ("Royal Antwerp FC", "Antwerp"),
    ("Real Madrid", "Real Madrid"),
    ("Atalanta BC", "Atalanta"),
)


@pytest.mark.parametrize(("source", "expected"), EXPECTED)
def test_canonical(source, expected):
    assert canonical(source) == expected


def test_mapping_is_direction_consistent():
    for _, expected in EXPECTED:
        assert canonical(expected) == expected


def test_unknown_raises_and_is_known_false():
    assert not is_known("Nonexistent FC")
    with pytest.raises(KeyError):
        canonical("Nonexistent FC")