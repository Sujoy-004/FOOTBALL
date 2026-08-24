"""DataProvider protocol conformance for BSDDataProvider.

The shared protocol declares fetch_matches(competition_id, **kwargs); both
call sites (WC pipeline, UCL app) pass competition_id=. BSD selects
competitions via league_id, so it must accept and ignore competition_id
instead of raising TypeError when auto-detection selects BSD.
"""

from __future__ import annotations

from football_core.data_providers.bsd_provider import BSDDataProvider
from football_core.provider import DataProvider


class TestBSDProviderProtocol:
    def _provider_with_stub(self, monkeypatch, pages):
        provider = BSDDataProvider(api_key="fake-key", league_id=7)
        responses = iter(pages)

        def fake_request(url, timeout=10):
            return next(responses)

        monkeypatch.setattr(provider, "_request", fake_request)
        return provider

    def test_satisfies_runtime_protocol(self):
        assert isinstance(BSDDataProvider("k", league_id=27), DataProvider)

    def test_accepts_competition_id_kwarg(self, monkeypatch):
        provider = self._provider_with_stub(
            monkeypatch,
            [{"results": [], "next": None}],
        )
        events = provider.fetch_matches(competition_id="CL")
        assert events == []

    def test_filters_by_league_and_follows_pagination(self, monkeypatch):
        page1 = {
            "results": [
                {"id": 1, "league": {"id": 7}},
                {"id": 2, "league": {"id": 99}},
            ],
            "next": "http://x/?page=2",
        }
        page2 = {"results": [{"id": 3, "league": {"id": 7}}], "next": None}
        provider = self._provider_with_stub(monkeypatch, [page1, page2])
        events = provider.fetch_matches(competition_id="CL")
        assert [e["id"] for e in events] == [1, 3]
