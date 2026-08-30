from football_core.data_providers.football_data_org_provider import FootballDataOrgProvider


def test_fdo_fetch_matches_builds_season_query(monkeypatch):
    provider = FootballDataOrgProvider("test-key")
    seen = {}

    def fake_request(url, timeout=10):
        seen["url"] = url
        return {"matches": []}

    monkeypatch.setattr(provider, "_request", fake_request)
    assert provider.fetch_matches(competition_id="CL", season=2026, matchday=1) == []
    assert seen["url"].endswith("/competitions/CL/matches?season=2026&matchday=1")


def test_fdo_fetch_matches_without_season_preserves_default_query(monkeypatch):
    provider = FootballDataOrgProvider("test-key")
    seen = {}

    def fake_request(url, timeout=10):
        seen["url"] = url
        return {"matches": []}

    monkeypatch.setattr(provider, "_request", fake_request)
    assert provider.fetch_matches(competition_id="CL") == []
    assert seen["url"].endswith("/competitions/CL/matches")
