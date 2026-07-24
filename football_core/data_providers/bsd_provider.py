"""BSD API data provider — wraps sports.bzzoiro.com endpoints.

Consolidates HTTP retry/auth/pagination logic from fetcher.py, manager.py,
player.py, and catboost.py into a single class. Returns raw list-of-dict
data; consumers handle parsing + caching.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from football_core import constants
from football_core.provider import DataProvider

logger = logging.getLogger(__name__)


class BSDDataProvider:
    """Data provider for BSD API (sports.bzzoiro.com).

    Encapsulates 4 endpoint types: matches, predictions, managers, players.
    Each method returns raw list-of-dict data matching the existing BSD schema.

    Parameters
    ----------
    api_key:
        BSD API token.
    league_id:
        Default BSD league ID (e.g. 27 = World Cup 2026, 7 = UCL 2025/26).
    """

    BASE_URL = "https://sports.bzzoiro.com"

    def __init__(self, api_key: str, league_id: int = 27) -> None:
        self.api_key = api_key
        self.league_id = league_id
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Token {api_key}"})

    # ── shared HTTP helpers ──────────────────────────────────────────────

    def _request(self, url: str, timeout: int = 10) -> dict[str, Any] | None:
        """GET *url* with retry/backoff. Returns parsed JSON or *None*."""
        if timeout == 10:
            timeout = constants.API_TIMEOUT
        backoff = [1, 2, 4]
        for attempt in range(3):
            try:
                resp = self._session.get(url, timeout=timeout)
                if resp.status_code == 401:
                    logger.debug("HTTP 401 (invalid API key) for %s", url)
                    return None
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
            except requests.exceptions.HTTPError:
                logger.debug("HTTP error (attempt %d/3): %s", attempt + 1, url)
                if attempt < 2:
                    time.sleep(backoff[attempt])
                    continue
                return None
            except (json.JSONDecodeError, requests.exceptions.JSONDecodeError):
                logger.debug("Malformed JSON response from %s", url)
                return None
        return None

    def _paginate(self, url: str, timeout: int = 10) -> list[dict[str, Any]]:
        """Fetch a paginated endpoint, following ``next`` links."""
        results: list[dict[str, Any]] = []
        next_url: str | None = url
        while next_url:
            data = self._request(next_url, timeout=timeout)
            if data is None:
                break
            results.extend(data.get("results", []))
            next_url = data.get("next")
        return results

    # ── endpoint methods ─────────────────────────────────────────────────

    def fetch_matches(
        self,
        url: str | None = None,
        league_id: int | None = None,
        timeout: int = 10,
    ) -> list[dict[str, Any]]:
        """Fetch raw match events from BSD ``/api/events/``.

        Parameters
        ----------
        url:
            Full API URL (e.g. from ``build_historic_url()``). If *None*,
            builds one from ``BASE_URL`` + *league_id*.
        league_id:
            Filter results to this league. Falls back to ``self.league_id``.
        timeout:
            Request timeout in seconds.
        """
        lid = league_id if league_id is not None else self.league_id
        if url is None:
            url = f"{self.BASE_URL}/api/events/?league_id={lid}"

        data = self._request(url, timeout=timeout)
        if data is None:
            return []

        all_events: list[dict[str, Any]] = list(data.get("results", []))
        next_url: str | None = data.get("next")
        while next_url:
            data = self._request(next_url, timeout=timeout)
            if data is None:
                break
            all_events.extend(data.get("results", []))
            next_url = data.get("next")

        return [
            e
            for e in all_events
            if isinstance(e.get("league"), dict) and e["league"].get("id") == lid
        ]

    def fetch_predictions(
        self,
        league_id: int | None = None,
        timeout: int = 10,
    ) -> list[dict[str, Any]]:
        """Fetch predictions from BSD ``/api/predictions/``."""
        lid = league_id if league_id is not None else self.league_id
        url = f"{self.BASE_URL}/api/predictions/?league={lid}"
        data = self._request(url, timeout=timeout)
        if data is None:
            return []
        results = data.get("results", [])
        return results if isinstance(results, list) else []

    def fetch_managers(
        self,
        league_id: int | None = None,
        timeout: int = 10,
    ) -> list[dict[str, Any]]:
        """Fetch manager profiles from BSD ``/api/managers/``."""
        lid = league_id if league_id is not None else self.league_id
        url = f"{self.BASE_URL}/api/managers/?league={lid}"
        data = self._request(url, timeout=timeout)
        if data is None:
            return []
        results = data.get("results", [])
        return results if isinstance(results, list) else []

    def fetch_players(
        self,
        league_id: int | None = None,
        timeout: int = 10,
    ) -> list[dict[str, Any]]:
        """Fetch player profiles from BSD ``/api/v2/players/``."""
        lid = league_id if league_id is not None else self.league_id
        url = f"{self.BASE_URL}/api/v2/players/?league_id={lid}&limit=200"
        return self._paginate(url, timeout=timeout)
