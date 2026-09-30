"""Canonical team-key mapping for the historical UCL backfill.

``canonical()`` maps ANY source spelling (openfootball cl.txt fixtures, the
ClubElo archive mirror, odds feeds) to a single canonical key. Keys are the
exact strings from ``data/team_aliases.json`` with the long-form 2026/27
production key preferred wherever an alias is ambiguous, plus a small stable
set of keys for clubs absent from the production fixtures (see
``_ADDED_CANONICAL_KEYS``).

Resolution order:
    1. case-insensitive reverse lookup of ``data/team_aliases.json``
       (an ambiguous alias resolves to its long-form 2026/27 key)
    2. explicit curated table (``_CURATED``) for spellings the alias file
       does not cover (diacritic variants, latinized forms, abbreviations)
    3. normalisation fallback: trailing 3-letter country tag stripped,
       diacritics folded, whitespace collapsed, then the alias / canonical
       lookups are re-run.

Unmappable input raises :class:`KeyError`; callers are expected to catch it
and fail loudly (unmapped teams are data errors). Building the tables is
pure and deterministic; importing this module has no side effects.

The resolution engine itself (and LaLiga's identical one) lives once in
``football_core.historical_backfill.TeamKeys``; this module is UCL's
curated-table configuration of it.
"""

from __future__ import annotations

import os

from football_core.historical_backfill import TeamKeys

_ALIASES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "team_aliases.json",
)

# Aliases that appear under more than one key must resolve to the long-form
# 2026/27 production key (see data/seasons/2026_27/fixtures.json).
_LONG_FORM: dict[str, str] = {
    "Bayern": "Bayern Munich",
    "FC Bayern München": "Bayern Munich",
    "Dortmund": "Borussia Dortmund",
    "Inter": "Inter Milan",
    "FC Internazionale Milano": "Inter Milan",
    "Man City": "Manchester City",
    "Manchester City FC": "Manchester City",
    "PSG": "Paris Saint-Germain",
    "Paris SG": "Paris Saint-Germain",
    "Paris Saint-Germain FC": "Paris Saint-Germain",
    "PSV": "PSV Eindhoven",
    "Sporting": "Sporting CP",
    "Sporting Clube de Portugal": "Sporting CP",
    "Bodoe Glimt": "Bodø/Glimt",
}

# Stable canonical keys for clubs absent from data/team_aliases.json.
_ADDED_CANONICAL_KEYS: tuple[str, ...] = (
    "Red Star Belgrade",
    "Dinamo Zagreb",
    "Zenit Saint Petersburg",
    "Lokomotiv Moscow",
    "Salzburg",
    "Genk",
    "Valencia",
    "Sevilla",
    "Lyon",
    "Rennes",
    "Celtic",
    "Rangers",
    "Midtjylland",
    "Ferencvaros",
    "Krasnodar",
    "Lazio",
    "AC Milan",
    "Malmö",
    "Young Boys",
    "Sheriff Tiraspol",
    "Ludogorets",
    "Braga",
    "Real Sociedad",
    "Antwerp",
    "Maccabi Haifa",
    "Viktoria Plzen",
    "Wolfsburg",
    "Union Berlin",
    "Borussia Monchengladbach",
    "Dynamo Kyiv",
    "Basaksehir",
    "Besiktas",
)

# Explicit spellings that survive neither the alias reverse lookup nor (on
# their own) normalisation: diacritic variants, latinized forms, and
# abbreviations as used by ClubElo / openfootball / odds feeds.
_CURATED: dict[str, str] = {
    # international / transliterated variants
    "Bayern München": "Bayern Munich",
    "Bayern Munchen": "Bayern Munich",
    "Olympiakos Piraeus": "Olympiacos",
    "Olympiacos Piraeus": "Olympiacos",
    "Crvena Zvezda": "Red Star Belgrade",
    "Red Star": "Red Star Belgrade",
    "FK Crvena Zvezda": "Red Star Belgrade",
    "Zenit Petersburg": "Zenit Saint Petersburg",
    "Zenit St Petersburg": "Zenit Saint Petersburg",
    "Zenit St. Petersburg": "Zenit Saint Petersburg",
    "Zenit": "Zenit Saint Petersburg",
    "Lokomotiv": "Lokomotiv Moscow",
    "Lokomotiv Moskva": "Lokomotiv Moscow",
    "Dinamo Kiev": "Dynamo Kyiv",
    "Dynamo Kiev": "Dynamo Kyiv",
    "Juve": "Juventus",
    "Internazionale": "Inter Milan",
    "Internazionale Milano": "Inter Milan",
    "Milan": "AC Milan",
    "Milan AC": "AC Milan",
    "Atlético": "Atletico Madrid",
    "Atlético Madrid": "Atletico Madrid",
    "Leipzig": "RB Leipzig",
    "Red Bull Leipzig": "RB Leipzig",
    "Red Bull Salzburg": "Salzburg",
    "RB Salzburg": "Salzburg",
    "FC Red Bull Salzburg": "Salzburg",
    "Borussia Mönchengladbach": "Borussia Monchengladbach",
    "Borussia M'gladbach": "Borussia Monchengladbach",
    "Borussia M. Gladbach": "Borussia Monchengladbach",
    "Bor. Mönchengladbach": "Borussia Monchengladbach",
    "Bor. Monchengladbach": "Borussia Monchengladbach",
    "Gladbach": "Borussia Monchengladbach",
    "Mönchengladbach": "Borussia Monchengladbach",
    "Monchengladbach": "Borussia Monchengladbach",
    "VfL Wolfsburg": "Wolfsburg",
    "KRC Genk": "Genk",
    "Racing Genk": "Genk",
    "Olympique Lyonnais": "Lyon",
    "Olympique Lyon": "Lyon",
    "Olympique Marseille": "Marseille",
    "Stade Rennais": "Rennes",
    "Stade Rennais FC": "Rennes",
    "Sevilla FC": "Sevilla",
    "Valencia CF": "Valencia",
    "Sporting Lisbon": "Sporting CP",
    "Sporting Lisboa": "Sporting CP",
    "SL Benfica": "Benfica",
    "Benfica Lisbon": "Benfica",
    "Ajax Amsterdam": "Ajax",
    "FC Copenhagen": "Copenhagen",
    "F.C. Copenhagen": "Copenhagen",
    "Kobenhavn": "Copenhagen",
    "København": "Copenhagen",
    "FC Midtjylland": "Midtjylland",
    "Malmö FF": "Malmö",
    "Malmo": "Malmö",
    "Malmo FF": "Malmö",
    "Malmoe": "Malmö",
    "Malmoe FF": "Malmö",
    "SC Braga": "Braga",
    "Sporting Braga": "Braga",
    "Sporting Clube de Braga": "Braga",
    "Glasgow Celtic": "Celtic",
    "Celtic FC": "Celtic",
    "Glasgow Rangers": "Rangers",
    "Rangers FC": "Rangers",
    "BSC Young Boys": "Young Boys",
    "YB Bern": "Young Boys",
    "Y.B. Bern": "Young Boys",
    "Young Boys Bern": "Young Boys",
    "GNK Dinamo Zagreb": "Dinamo Zagreb",
    "FK Krasnodar": "Krasnodar",
    "Ludogorets Razgrad": "Ludogorets",
    "Sheriff": "Sheriff Tiraspol",
    "FC Sheriff": "Sheriff Tiraspol",
    "SS Lazio": "Lazio",
    "Lazio Roma": "Lazio",
    "Atalanta Bergamo": "Atalanta",
    "Ferencváros": "Ferencvaros",
    "Ferencvárosi TC": "Ferencvaros",
    "Ferencvarosi TC": "Ferencvaros",
    "Viktoria Plzeň": "Viktoria Plzen",
    "Viktoria Pilsen": "Viktoria Plzen",
    "Maccabi Haifa FC": "Maccabi Haifa",
    "Real Sociedad de Futbol": "Real Sociedad",
    "FK Qarabag": "Qarabag",
    "Union Saint-Gilloise": "Union SG",
    "Union St. Gilloise": "Union SG",
    "St. Gilloise": "Union SG",
    "LOSC": "Lille",
    "Racing Club de Lens": "Lens",
    "1. FC Union Berlin": "Union Berlin",
    "Man Utd": "Manchester United",
    "Spurs": "Tottenham",
    "Tottenham Hotspur": "Tottenham",
    "Istanbul Basaksehir": "Basaksehir",
    "Istanbul Basakşehir": "Basaksehir",
    "Medipol Basaksehir": "Basaksehir",
    "Başakşehir": "Basaksehir",
    "Beşiktaş": "Besiktas",
    "Royal Antwerp": "Antwerp",
    "Antwerp FC": "Antwerp",
    "Royal Antwerp FC": "Antwerp",
    "FK Bodø/Glimt": "Bodø/Glimt",
    # ClubElo archive mirror (xgabora) abbreviated club names
    "Ath Madrid": "Atletico Madrid",
    "Ath Bilbao": "Athletic Bilbao",
    "Sp Lisbon": "Sporting CP",
    "Sp Braga": "Braga",
    "Lok Moskva": "Lokomotiv Moscow",
    "Ein Frankfurt": "Eintracht Frankfurt",
    "MGladbach": "Borussia Monchengladbach",
    "M'gladbach": "Borussia Monchengladbach",
    "FC Krasnodar": "Krasnodar",
    "Sociedad": "Real Sociedad",
    "Buyuksehyr": "Basaksehir",
}

_KEYS = TeamKeys(_ALIASES_FILE, _CURATED, _ADDED_CANONICAL_KEYS, _LONG_FORM)

# Full source-name -> canonical table for provenance / reporting.
canonical_map: dict[str, str] = _KEYS.canonical_map
CANONICAL_KEYS: list[str] = _KEYS.CANONICAL_KEYS
ALIAS_REV: dict[str, str] = _KEYS.ALIAS_REV
CURATED_REV: dict[str, str] = _KEYS.CURATED_REV
NORM_REV: dict[str, str] = _KEYS.NORM_REV

#: Map an arbitrary source team spelling to its canonical key.
#: Raises :class:`KeyError` if the team cannot be resolved.
canonical = _KEYS.canonical
#: True when *team* resolves to a canonical key (never raises).
is_known = _KEYS.is_known

__all__ = [
    "ALIAS_REV",
    "CANONICAL_KEYS",
    "CURATED_REV",
    "NORM_REV",
    "canonical",
    "canonical_map",
    "is_known",
]
