# -*- coding: utf-8 -*-
"""Tests for the ClubElo ranking scraper and the stored-ratings refresh.

Covers the three things that can silently go wrong with an HTML scrape:
the row shape changes, the page comes back empty, and two different clubs
share a display name. Plus the store: one fetch per day, a re-fetch when a
team is new, a log entry only when a rating actually moves.
"""

from __future__ import annotations

import pytest

from football_core.clubelo import (
    MIN_ROWS,
    ClubEloUnavailable,
    ranking_html_to_ratings,
    slug_key,
)
from football_core.elo_fetcher import refresh_elos_if_stale

# One real row from clubelo.com/Ranking, verbatim in shape. The page embeds
# its table as a JS array, so each entry is a quoted <td> blob followed by
# the rank, the rating, and trailing fields we do not need.
def _row(slug: str, display: str, elo: str, change: str = "+0.01") -> str:
    return (
        f"['<td class=\"l\"><a href=\"/{slug}\">{display}"
        f"<span class=\"min481\"></span></a></td>', '{elo}', '{change}', '1.30'],"
    )


_PAGE = "".join([
    _row("Shakhtar", "Shakhtar", "1689"),
    _row("Liverpool", "Liverpool", "1937"),
    # Same display name, different club. This is the case that made
    # display-name keying return Liverpool of Uruguay for "Liverpool".
    _row("LiverpoolUY", "Liverpool", "1585"),
    _row("Barcelona", "Barcelona", "2024"),
    _row("BarcelonaEC", "Barcelona", "1642"),
    _row("sabah-fk", "Sabah FK", "1563"),
    _row("BodoeGlimt", "Bodø/Glimt", "1779"),
])


def test_parses_rows_keyed_by_slug():
    ratings = ranking_html_to_ratings(_PAGE, min_rows=1)
    assert ratings == {
        "shakhtar": 1689.0,
        "liverpool": 1937.0,
        "liverpooluy": 1585.0,
        "barcelona": 2024.0,
        "barcelonaec": 1642.0,
        "sabahfk": 1563.0,
        "bodoeglimt": 1779.0,
    }


def test_duplicate_display_names_stay_separate_clubs():
    """Two clubs can share a display name; the slug keeps them distinct.

    Keying on the display name would collapse these and hand back whichever
    row came last — a plausible-looking number for the wrong club.
    """
    ratings = ranking_html_to_ratings(_PAGE, min_rows=1)
    assert ratings["liverpool"] == 1937.0
    assert ratings["liverpooluy"] == 1585.0
    assert ratings["barcelona"] == 2024.0
    assert ratings["barcelonaec"] == 1642.0


def test_empty_page_is_rejected_not_treated_as_no_ratings():
    """Zero rows must fail loudly, not look like 'ClubElo knows nothing'."""
    with pytest.raises(ClubEloUnavailable):
        ranking_html_to_ratings("<html><body>nope</body></html>")


def test_partial_page_is_rejected():
    """A half-parsed page is as wrong as an empty one."""
    with pytest.raises(ClubEloUnavailable):
        ranking_html_to_ratings(_PAGE, min_rows=MIN_ROWS)


def test_markup_change_is_rejected():
    """A page that still has content but no rating rows is a broken selector."""
    drifted = "".join(
        f"['<td class=\"l\"><a href=\"/{s}\">{s}</a></td>', '1']," for s in "abcdefg"
    )
    with pytest.raises(ClubEloUnavailable):
        ranking_html_to_ratings(drifted)


def test_slug_key_ignores_case_and_separators():
    assert slug_key("sabah-fk") == slug_key("SabahFK") == "sabahfk"
    assert slug_key("BodoeGlimt") == slug_key("bodoeglimt") == "bodoeglimt"
    assert slug_key("Bayern München") == slug_key("Bayern Munchen") == "bayernmunchen"


def test_slug_key_cannot_reduce_slash_o():
    """Documented limit: ø is dropped, not transliterated.

    That is why the alias map stores slugs rather than the names the page
    prints — a display name like "Bodø/Glimt" reduces to "bodglimt" and
    misses the real "bodoeglimt".
    """
    assert slug_key("Bodø/Glimt") == "bodglimt"
    assert slug_key("Bodø/Glimt") != slug_key("BodoeGlimt")


# ── Stored ratings ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_daily_memo():
    """Clear the process-wide one-per-day ranking memo between tests.

    ``_fetch_ranking`` memoizes on the snapshot date at module scope, so
    without this a dict memoized by one test leaks into the next.
    """
    from football_core.elo_fetcher import _fetch_ranking

    _fetch_ranking.cache_clear()
    yield
    _fetch_ranking.cache_clear()


def _alias_file(tmp_path, mapping: dict[str, str]):
    """Write an alias file in the on-disk shape: team -> list of ClubElo slugs."""
    import json
    path = tmp_path / "aliases.json"
    path.write_text(
        json.dumps({team: [slug] for team, slug in mapping.items()}), encoding="utf-8"
    )
    return str(path)


def _age_store(tmp_path, hours: float = 25.0) -> None:
    """Backdate the store past its freshness window.

    Standing in for a day passing: the alternative is patching the clock
    inside the implementation, which is the thing under test here.
    """
    import json
    from datetime import datetime, timedelta, timezone

    path = tmp_path / "elo_cache.json"
    cache = json.loads(path.read_text(encoding="utf-8"))
    cache["fetched_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=hours)
    ).isoformat()
    path.write_text(json.dumps(cache), encoding="utf-8")


def test_one_fetch_then_served_from_the_store(tmp_path, monkeypatch):
    """A second call the same day must not touch the network."""
    alias = _alias_file(tmp_path, {"Real Madrid": "RealMadrid"})
    calls = []

    def _fake_ranking(*a, **k):
        calls.append(1)
        return {"realmadrid": 1972.0}

    monkeypatch.setattr("football_core.elo_fetcher.fetch_ranking", _fake_ranking)

    first = refresh_elos_if_stale(["Real Madrid"], alias, tmp_path)
    second = refresh_elos_if_stale(["Real Madrid"], alias, tmp_path)

    assert first == second == {"Real Madrid": 1972.0}
    assert len(calls) == 1, "second call re-fetched a fresh store"


def test_new_team_forces_a_refetch(tmp_path, monkeypatch):
    """A team missing from the store is a reason to re-fetch, not to guess.

    ClubElo rates a club from its first top-flight appearance, so a newly
    drawn team would otherwise sit at DEFAULT_ELO inside a store that is
    still minutes old. Age is not what makes this store unusable here —
    coverage is, so the refresh must happen even well inside the 24h window.
    """
    alias = _alias_file(tmp_path, {"Real Madrid": "RealMadrid", "Sabah": "sabah-fk"})
    calls = []

    def _ranking(*a, **k):
        calls.append(1)
        # The first ranking does not carry Sabah yet.
        if len(calls) == 1:
            return {"realmadrid": 1972.0}
        return {"realmadrid": 1972.0, "sabahfk": 1563.0}

    monkeypatch.setattr("football_core.elo_fetcher.fetch_ranking", _ranking)
    day = _step_day(monkeypatch)

    assert refresh_elos_if_stale(["Real Madrid"], alias, tmp_path) == {
        "Real Madrid": 1972.0
    }

    # Next day, same wall clock: the store is nowhere near 24h old, but Sabah
    # is not in it, so the ranking is fetched again.
    ratings = refresh_elos_if_stale(["Real Madrid", "Sabah"], alias, tmp_path)

    assert len(calls) == 2, "incomplete coverage did not force a re-fetch"
    assert day["n"] == 2
    assert ratings == {"Real Madrid": 1972.0, "Sabah": 1563.0}
    assert 1500.0 not in ratings.values(), "a placeholder was stored as a rating"


def test_only_changed_ratings_are_logged(tmp_path, monkeypatch):
    """The log records drift, not a daily re-stamp of every team.

    Days are stepped explicitly because the ranking is memoized per snapshot
    date: a second fetch can only happen on a new day, which is also the only
    time the real page can have moved.
    """
    import json

    alias = _alias_file(tmp_path, {"Real Madrid": "RealMadrid", "Sabah": "sabah-fk"})
    day = {"n": 0}

    def _ranking(*a, **k):
        # _next_day() runs before the fetch, so the first two fetches are
        # days 1 and 2; the club moves on day 3.
        return (
            {"realmadrid": 1972.0, "sabahfk": 1563.0}
            if day["n"] <= 2
            else {"realmadrid": 1972.0, "sabahfk": 1600.0}
        )

    monkeypatch.setattr("football_core.elo_fetcher.fetch_ranking", _ranking)

    def _next_day():
        day["n"] += 1
        return f"2026-09-{29 + day['n']}"

    monkeypatch.setattr(
        "football_core.elo_fetcher.get_clubelo_snapshot_date", _next_day
    )
    teams = ["Real Madrid", "Sabah"]

    def _next_refresh():
        """Age the store past its window and step the ranking's daily memo."""
        _age_store(tmp_path)
        refresh_elos_if_stale(teams, alias, tmp_path)

    refresh_elos_if_stale(teams, alias, tmp_path)
    # Cold cache: nothing to compare against, so the first day is not backfilled.
    assert not (tmp_path / "elo_update_log.json").exists()

    _next_refresh()
    # A fetch really did happen, the ratings just did not move.
    assert day["n"] == 2
    assert not (tmp_path / "elo_update_log.json").exists()

    _next_refresh()

    log = json.loads((tmp_path / "elo_update_log.json").read_text(encoding="utf-8"))
    assert len(log) == 1, "only the team that moved should be logged"
    assert log[0]["team"] == "Sabah"
    assert log[0]["old_value"] == 1563.0
    assert log[0]["new_value"] == 1600.0
    assert log[0]["drift_magnitude"] == 37.0
    assert log[0]["source"] == "clubelo"


def test_failed_fetch_serves_stored_ratings(tmp_path, monkeypatch):
    """A ClubElo outage degrades to stale numbers, not to no numbers."""
    alias = _alias_file(tmp_path, {"Real Madrid": "RealMadrid"})
    monkeypatch.setattr(
        "football_core.elo_fetcher.fetch_ranking",
        lambda *a, **k: {"realmadrid": 1972.0},
    )
    refresh_elos_if_stale(["Real Madrid"], alias, tmp_path)

    def _dead(*a, **k):
        raise ClubEloUnavailable("page changed")

    monkeypatch.setattr("football_core.elo_fetcher.fetch_ranking", _dead)
    _age_store(tmp_path)

    assert refresh_elos_if_stale(["Real Madrid"], alias, tmp_path) == {
        "Real Madrid": 1972.0
    }


def test_failed_fetch_with_no_store_raises(tmp_path, monkeypatch):
    """With nothing stored there is nothing honest to return, so it raises."""
    alias = _alias_file(tmp_path, {"Real Madrid": "RealMadrid"})

    def _dead(*a, **k):
        raise ClubEloUnavailable("page changed")

    monkeypatch.setattr("football_core.elo_fetcher.fetch_ranking", _dead)
    with pytest.raises(ClubEloUnavailable):
        refresh_elos_if_stale(["Real Madrid"], alias, tmp_path)


def _step_day(monkeypatch) -> dict:
    """Advance the ranking's daily memo key, the way a new day does in production.

    ``_fetch_ranking`` memoizes per snapshot date at module scope, so a second
    call on the same day is served from memory and never reaches the network.
    Tests that need two distinct fetches have to cross a day boundary.
    """
    day = {"n": 0}

    def _today():
        day["n"] += 1
        return f"2026-09-{28 + day['n']}"

    monkeypatch.setattr("football_core.elo_fetcher.get_clubelo_snapshot_date", _today)
    return day


def test_placeholder_is_never_treated_as_covered(tmp_path, monkeypatch):
    """A DEFAULT_ELO stand-in must not make the store look complete.

    ClubElo has no entry for an unrated club, so ``fetch_team_elos`` hands
    back 1500. If that counted as coverage, the store would go quiet for a
    day with a confident-looking placeholder in it.
    """
    alias = _alias_file(
        tmp_path, {"Real Madrid": "RealMadrid", "Newly Drawn": "NewlyDrawn"}
    )
    monkeypatch.setattr(
        "football_core.elo_fetcher.fetch_ranking",
        lambda *a, **k: {"realmadrid": 1972.0},  # no entry for Newly Drawn
    )
    _step_day(monkeypatch)

    ratings = refresh_elos_if_stale(["Real Madrid", "Newly Drawn"], alias, tmp_path)
    assert ratings["Newly Drawn"] == 1500.0

    # Next day: the store holds both teams, but one is a placeholder, so it is
    # still uncovered and the ranking is fetched again.
    calls = []
    monkeypatch.setattr(
        "football_core.elo_fetcher.fetch_ranking",
        lambda *a, **k: (calls.append(1), {"realmadrid": 1972.0})[1],
    )
    refresh_elos_if_stale(["Real Madrid", "Newly Drawn"], alias, tmp_path)
    assert calls, "a placeholder was served from a 'fresh' store"


def test_partial_stored_ratings_are_not_served_as_if_complete(tmp_path, monkeypatch):
    """A stale set missing a requested team must not look like success.

    The caller labels any non-empty rating dict as ClubElo, so quietly
    dropping a team here would misrepresent the result.
    """
    alias = _alias_file(tmp_path, {"Real Madrid": "RealMadrid", "Sabah": "sabah-fk"})
    monkeypatch.setattr(
        "football_core.elo_fetcher.fetch_ranking",
        lambda *a, **k: {"realmadrid": 1972.0},
    )
    _step_day(monkeypatch)
    refresh_elos_if_stale(["Real Madrid"], alias, tmp_path)

    def _dead(*a, **k):
        raise ClubEloUnavailable("page changed")

    monkeypatch.setattr("football_core.elo_fetcher.fetch_ranking", _dead)
    _age_store(tmp_path)

    with pytest.raises(ClubEloUnavailable):
        refresh_elos_if_stale(["Real Madrid", "Sabah"], alias, tmp_path)


def test_oversized_response_is_refused(monkeypatch):
    """A runaway response is stopped instead of read into memory whole."""

    class _Huge:
        def read(self, n):
            return b"x" * n

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    from football_core import clubelo

    monkeypatch.setattr(clubelo.urllib.request, "urlopen", lambda *a, **k: _Huge())
    with pytest.raises(ClubEloUnavailable):
        clubelo.fetch_ranking()
