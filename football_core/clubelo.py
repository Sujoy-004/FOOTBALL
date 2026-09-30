"""ClubElo ranking scraper — the live source of club Elo ratings.

The dated CSV endpoint (``api.clubelo.com/YYYY-MM-DD``) and the per-team
history endpoint on the same host are both dead (HTTP 502). The public
ranking page is still served and carries the whole world ranking in a
single response, so one request there replaces both.

``clubelo.com/Ranking`` embeds its table as a JavaScript array whose rows
pair a club link with that club's current Elo::

    ['<td class="l">...<a href="/LiverpoolUY">Liverpool<span ...></span></a></td>', '1585', ...]

The club's *display name* is not an identity: 34 names on this page are
shared by more than one club ("Liverpool" 1937 is the club, "Liverpool" 1585
is Liverpool of Uruguay). The link target is. So rows are keyed by the
normalized ``href`` slug, which is unique per club, and callers are
expected to look up the slug they have in hand. Keying on the display name
would silently return whichever duplicate came last.

The page is untrusted input: it is never executed, ``eval``'d, or
interpolated into anything, and a response that does not look like a full
ranking is rejected outright rather than partially trusted.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import urllib.request

logger = logging.getLogger(__name__)

RANKING_URL = "https://clubelo.com/Ranking"
FETCH_TIMEOUT = 30

USER_AGENT = "football-predictor/1.0 (ClubElo rating sync)"
"""Self-identifying user agent.

The page is a public ratings table, so this asks for it the way a small
syncer should: named, over HTTPS, once per day. Spoofing a browser string
buys nothing and is the fastest way to get throttled — measured here, a
generic desktop-browser UA stalled until timeout while this one was served
in 0.7s.
"""

MIN_ROWS = 1000
"""Floor for a believable ranking page.

A markup change would otherwise yield zero rows, and zero rows would look
exactly like "ClubElo has no ratings for these teams" — silently emptying
the view instead of failing. The live page carries ~1650 clubs, so a floor
of 1000 leaves generous headroom for a real re-layout while still
catching a broken selector.
"""

_ROW = re.compile(
    r'<a href="/(?P<slug>[^"]+)">[^<]*<span class="min481"></span></a>'
    r"</td>',\s*'(?P<elo>[0-9]+(?:\.[0-9]+)?)'",
    re.S,
)


class ClubEloUnavailable(RuntimeError):
    """The ranking page could not be read, or did not look like a ranking."""


def slug_key(value: str) -> str:
    """Comparison key for a ClubElo slug: lowercase, ASCII-only, no separators.

    Slugs are compared rather than looked up verbatim because the site is
    inconsistent about case and separators across its 1650 entries
    (``BodoeGlimt``, ``AstonVilla``, ``sabah-fk``). Normalizing collapses
    that without inventing a second alias list.

    Note the one thing this cannot do: ``ø`` has no NFKD decomposition, and
    the ASCII filter then drops it, so a *display* name like ``Bodø/Glimt``
    reduces to ``bodglimt`` and will not match the slug ``bodoeglimt``. That
    is why the alias map holds slugs rather than the names the site prints.
    """
    decomposed = unicodedata.normalize("NFKD", str(value))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", stripped.lower())


def ranking_html_to_ratings(html: str, min_rows: int | None = None) -> dict[str, float]:
    """Ranking page HTML -> {normalized slug: Elo}.

    Raises :class:`ClubEloUnavailable` if fewer than *min_rows* (default
    :data:`MIN_ROWS`) rows parse, so a changed page fails loudly instead of
    looking like an empty ranking.
    """
    floor = MIN_ROWS if min_rows is None else min_rows
    matches = list(_ROW.finditer(html))
    if len(matches) < floor:
        raise ClubEloUnavailable(
            f"parsed {len(matches)} ranking rows from the page, floor is {floor}; "
            "the page markup likely changed, refusing to report ratings"
        )
    ratings: dict[str, float] = {}
    for match in matches:
        ratings[slug_key(match.group("slug"))] = float(match.group("elo"))
    return ratings


MAX_BYTES = 8 * 1024 * 1024
"""Ceiling on the ranking response.

The live page is ~940KB. 8MB leaves room for ClubElo to grow the table many
times over while still bounding what a bad response can cost: the read stops
here instead of filling memory with whatever the connection sends.
"""


def fetch_ranking(url: str = RANKING_URL) -> dict[str, float]:
    """GET *url* once and return the whole world ranking.

    HTTPS, a self-identifying user agent, one request, no retry loop, and a
    bounded read. The response is a few hundred KB and normally lands well
    under a second, so a stall is a real failure worth reporting rather than
    hammering: the caller keeps the ratings it already stored and the next
    scheduled refresh tries again.

    Network errors propagate. Callers already degrade to a labelled
    fallback, and swallowing the error here would hide a dead source.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    logger.debug("Fetching ClubElo ranking from %s", url)
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ClubEloUnavailable(
            f"ranking page exceeded {MAX_BYTES} bytes; refusing to parse it"
        )
    return ranking_html_to_ratings(raw.decode("utf-8", errors="replace"))
