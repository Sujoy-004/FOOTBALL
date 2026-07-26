"""football-data.org API data provider — replaces BSD for match results.

Field mapping (football-data.org → BSD-compatible flat dict):

+---------------------------+------------------------------------------+
| BSD field                 | football-data.org source                 |
+---------------------------+------------------------------------------+
| home_team                 | homeTeam.name                            |
| away_team                 | awayTeam.name                            |
| home_score                | score.fullTime.home                      |
| away_score                | score.fullTime.away                      |
| status                    | status.lower()                           |
| event_date                | utcDate                                  |
| group_name                | group ("GROUP_A" → "Group A")            |
| round_number              | matchday                                 |
| id                        | id                                       |
| winner                    | derived from score / score.winner        |
+---------------------------+------------------------------------------+
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

_GROUP_PATTERN = re.compile(r"^GROUP_([A-Z])$")


class FootballDataOrgProvider:
    """Data provider for ``api.football-data.org`` (v4).

    Provides match results for supported competitions.
    Predictions, managers, and players are **not** available from this source.

    Parameters
    ----------
    api_key:
        Free API key from `football-data.org/client/register`__.

    .. __: https://www.football-data.org/client/register

    Competition codes
    -----------------
    - ``WC`` — FIFA World Cup
    - ``CL`` — UEFA Champions League
    """

    BASE_URL = "https://api.football-data.org/v4"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._session = requests.Session()
        self._session.headers.update({"X-Auth-Token": api_key})

    # ── shared HTTP helpers ──────────────────────────────────────────────

    def _request(self, url: str, timeout: int = 10) -> dict[str, Any] | None:
        """GET *url* with retry/backoff. Returns parsed JSON or *None*."""
        backoff = [1, 2, 4]
        for attempt in range(3):
            try:
                resp = self._session.get(url, timeout=timeout)
                if resp.status_code == 401:
                    logger.warning("HTTP 401 (invalid API key) for %s", url)
                    return None
                if resp.status_code == 429:
                    logger.warning("Rate limited (429) for %s — retrying", url)
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.Timeout:
                logger.debug("Request timed out (attempt %d/3): %s", attempt + 1, url)
                if attempt < 2:
                    time.sleep(backoff[attempt])
                    continue
                return None
            except requests.exceptions.ConnectionError:
                logger.debug("Connection error (attempt %d/3): %s", attempt + 1, url)
                if attempt < 2:
                    time.sleep(backoff[attempt])
                    continue
                return None
            except requests.exceptions.HTTPError as e:
                logger.debug("HTTP error (attempt %d/3): %s — %s", attempt + 1, url, e)
                if attempt < 2:
                    time.sleep(backoff[attempt])
                    continue
                return None
        return None

    # ── field mapping ────────────────────────────────────────────────────

    @staticmethod
    def _map_group(raw_group: str | None) -> str:
        """Convert ``"GROUP_A"`` → ``"Group A"`` (BSD convention)."""
        if not raw_group:
            return ""
        m = _GROUP_PATTERN.match(raw_group)
        if m:
            return f"Group {m.group(1)}"
        return raw_group

    @staticmethod
    def _map_match(raw: dict[str, Any]) -> dict[str, Any]:
        """Map football-data.org match schema to BSD-compatible flat dict."""
        ht = raw.get("homeTeam") or {}
        at = raw.get("awayTeam") or {}
        home_team = (
            ht.get("name") if isinstance(ht, dict) else ""
        )
        away_team = (
            at.get("name") if isinstance(at, dict) else ""
        )

        score = raw.get("score") or {}
        duration = score.get("duration", "")
        # football-data.org's fullTime includes penalty shootout goals.
        # For penalty shootouts, use regularTime (90-min result) instead.
        if duration == "PENALTY_SHOOTOUT":
            rt = score.get("regularTime") or {}
            home_score = rt.get("home") if rt.get("home") is not None else None
            away_score = rt.get("away") if rt.get("away") is not None else None
        else:
            ft = score.get("fullTime") or {}
            home_score = ft.get("home") if ft.get("home") is not None else None
            away_score = ft.get("away") if ft.get("away") is not None else None

        status = (raw.get("status") or "").lower()
        group = FootballDataOrgProvider._map_group(raw.get("group"))
        matchday = raw.get("matchday") or 1

        mapped: dict[str, Any] = {
            "id": raw.get("id", 0),
            "home_team": home_team,
            "away_team": away_team,
            "home_score": home_score,
            "away_score": away_score,
            "status": status,
            "event_date": raw.get("utcDate", ""),
            "group_name": group,
            "round_number": matchday,
            "stage": raw.get("stage", ""),
        }

        # Derive winner from score.winner or fall back to score comparison
        if status == "finished":
            sw = score.get("winner")
            if sw == "HOME_TEAM":
                mapped["winner"] = home_team
            elif sw == "AWAY_TEAM":
                mapped["winner"] = away_team
            elif sw == "DRAW":
                mapped["winner"] = None
            else:
                mapped["winner"] = None

        return mapped

    # ── endpoint methods ─────────────────────────────────────────────────

    def fetch_matches(
        self,
        competition_id: str = "WC",
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Fetch matches for *competition_id* from football-data.org.

        Returns flattened dicts matching the BSD event schema expected by
        the existing processing pipeline (``process_matches``, etc.).

        Parameters
        ----------
        competition_id:
            Competition code (``"WC"``, ``"CL"``, etc.).
        """
        url = f"{self.BASE_URL}/competitions/{competition_id}/matches"
        data = self._request(url)
        if data is None:
            return []
        raw_matches = data.get("matches", [])
        return [self._map_match(m) for m in raw_matches]

    def fetch_predictions(
        self,
        competition_id: str = "WC",
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Not available from football-data.org."""
        return []

    def fetch_managers(
        self,
        competition_id: str = "WC",
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Not available from football-data.org."""
        return []

    def fetch_players(
        self,
        competition_id: str = "WC",
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Not available from football-data.org."""
        return []
