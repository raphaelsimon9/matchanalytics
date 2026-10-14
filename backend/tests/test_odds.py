import asyncio

import httpx
import pytest

from app import config, odds, providers

FIXTURES = [
    {"id": 1, "kickoff": "2026-10-17T11:30:00Z", "home": "Everton FC", "away": "Chelsea FC"},
    {"id": 2, "kickoff": "2026-10-17T14:00:00Z", "home": "Brighton & Hove Albion FC", "away": "Manchester United FC"},
    {"id": 3, "kickoff": "2026-10-18T13:00:00Z", "home": "Wolverhampton Wanderers FC", "away": "Tottenham Hotspur FC"},
]


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    providers._cache.clear(); odds._errors.clear(); odds._quota.clear()
    monkeypatch.setattr(config, "PREFERRED_BOOKMAKERS", [])


def mock_client(monkeypatch, handler):
    monkeypatch.setattr(odds, "_client", lambda **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), timeout=5, **kw))


def test_name_matching():
    assert odds.same("Manchester United FC", "Man United")
    assert odds.same("Brighton & Hove Albion FC", "Brighton and Hove Albion")
    assert odds.same("Wolverhampton Wanderers FC", "Wolves")
    assert odds.same("Tottenham Hotspur FC", "Tottenham")
    assert odds.same("1. FC Köln", "FC Koln")
    assert not odds.same("Manchester United FC", "Manchester City FC")
    assert not odds.same("Leeds United FC", "Sheffield United")


def test_match_fixture_uses_date_window():
    assert odds.match_fixture(FIXTURES, "Everton", "Chelsea", "2026-10-17T12:00:00Z") == 1
    assert odds.match_fixture(FIXTURES, "Everton", "Chelsea", "2026-11-30T12:00:00Z") is None


def test_theoddsapi(monkeypatch):
    monkeypatch.setattr(config, "ODDS_API_KEY", "k")
    payload = [{"home_team": "Everton", "away_team": "Chelsea", "commence_time": "2026-10-17T11:30:00Z",
                "bookmakers": [
                    {"title": "BookA", "markets": [
                        {"key": "h2h", "outcomes": [{"name": "Everton", "price": 2.5}, {"name": "Draw", "price": 3.3}, {"name": "Chelsea", "price": 2.9}]},
                        {"key": "totals", "outcomes": [{"name": "Over", "point": 2.5, "price": 1.9}, {"name": "Under", "point": 2.5, "price": 1.95}]}]},
                    {"title": "BookB", "markets": [
                        {"key": "h2h", "outcomes": [{"name": "Everton", "price": 2.6}, {"name": "Draw", "price": 3.2}, {"name": "Chelsea", "price": 2.8}]},
                        {"key": "totals", "outcomes": [{"name": "Over", "point": 1.5, "price": 1.3}, {"name": "Over", "point": 3.5, "price": 3.0}]}]}]}]
    seen = {}
    def handler(req):
        seen.update(dict(req.url.params))
        return httpx.Response(200, json=payload, headers={"x-requests-remaining": "498"})
    mock_client(monkeypatch, handler)
    out = asyncio.run(odds.fetch_theoddsapi("PL", FIXTURES))
    assert seen["regions"] == "eu" and seen["markets"] == "h2h,totals"
    assert sorted(out[1]["home"]) == [(2.5, "BookA"), (2.6, "BookB")]
    assert out[1]["over15"] == [(1.3, "BookB")] and "over35" not in out[1]
    assert odds._quota["The Odds API"] == 498


def test_apifootball_pagination_and_bet_parsing(monkeypatch):
    monkeypatch.setattr(config, "API_FOOTBALL_KEY", "k")
    fx = {"errors": [], "response": [
        {"fixture": {"id": 900, "date": "2026-10-17T11:30:00+00:00"}, "teams": {"home": {"name": "Everton"}, "away": {"name": "Chelsea"}}},
        {"fixture": {"id": 901, "date": "2026-10-17T14:00:00+00:00"}, "teams": {"home": {"name": "Brighton"}, "away": {"name": "Manchester United"}}}]}
    def odds_item(fid, over15):
        return {"fixture": {"id": fid}, "bookmakers": [{"id": 8, "name": "Bet365", "bets": [
            {"id": 1, "name": "Match Winner", "values": [{"value": "Home", "odd": "2.10"}, {"value": "Draw", "odd": "3.40"}, {"value": "Away", "odd": "3.20"}]},
            {"id": 5, "name": "Goals Over/Under", "values": [{"value": "Over 1.5", "odd": over15}, {"value": "Under 1.5", "odd": "3.4"}, {"value": "Over 2.5", "odd": "1.95"}]},
            {"id": 8, "name": "Both Teams Score", "values": [{"value": "Yes", "odd": "1.80"}, {"value": "No", "odd": "2.00"}]}]}]}
    pages = {"1": {"errors": [], "paging": {"current": 1, "total": 2}, "response": [odds_item(900, "1.30")]},
             "2": {"errors": [], "paging": {"current": 2, "total": 2}, "response": [odds_item(901, "1.25")]}}
    calls = []
    def handler(req):
        assert req.headers["x-apisports-key"] == "k"
        calls.append(req.url.path)
        hdr = {"x-ratelimit-requests-remaining": "93"}
        if req.url.path == "/fixtures": return httpx.Response(200, json=fx, headers=hdr)
        return httpx.Response(200, json=pages[req.url.params["page"]], headers=hdr)
    mock_client(monkeypatch, handler)
    out = asyncio.run(odds.fetch_apifootball("PL", FIXTURES))
    assert out[1]["over15"] == [(1.3, "Bet365")] and out[2]["over15"] == [(1.25, "Bet365")]
    assert out[1]["btts_yes"] == [(1.8, "Bet365")] and out[1]["draw"] == [(3.4, "Bet365")]
    assert calls == ["/fixtures", "/odds", "/odds"] and odds._quota["API-Football"] == 93


def test_apifootball_reports_plan_errors(monkeypatch):
    monkeypatch.setattr(config, "API_FOOTBALL_KEY", "k")
    mock_client(monkeypatch, lambda req: httpx.Response(200, json={"errors": {"plan": "Free plans do not have access to this season"}, "response": []}))
    with pytest.raises(RuntimeError, match="Free plans"):
        asyncio.run(odds.fetch_apifootball("PL", FIXTURES))


def test_oddsapiio_flow(monkeypatch):
    monkeypatch.setattr(config, "ODDSAPIIO_KEY", "k")
    def handler(req):
        p = req.url.path
        if p.endswith("/leagues"):
            return httpx.Response(200, json=[{"name": "England - Premier League", "slug": "england-premier-league", "eventsCount": 30}])
        if p.endswith("/events"):
            assert req.url.params["league"] == "england-premier-league"
            return httpx.Response(200, json=[{"id": 555, "home": "Everton", "away": "Chelsea", "date": "2026-10-17T11:30:00Z"}])
        if p.endswith("/odds/multi"):
            assert req.url.params["bookmakers"] == "SportyBet,Stake"
            return httpx.Response(200, headers={"x-ratelimit-remaining": "4990"}, json=[{"id": 555, "bookmakers": {
                "SportyBet": [{"name": "ML", "odds": [{"home": "2.40", "draw": "3.30", "away": "2.95"}]},
                              {"name": "Totals", "odds": [{"hdp": 1.5, "over": "1.28", "under": "3.6"}, {"hdp": 2.5, "over": "1.85", "under": "1.95"}]},
                              {"name": "Both Teams To Score", "odds": [{"yes": "1.75", "no": "2.05"}]}]}}])
        return httpx.Response(404)
    mock_client(monkeypatch, handler)
    out = asyncio.run(odds.fetch_oddsapiio("PL", FIXTURES))
    assert out[1]["over15"] == [(1.28, "SportyBet")] and out[1]["btts_no"] == [(2.05, "SportyBet")]
    assert out[1]["home"] == [(2.4, "SportyBet")]


def test_gather_merge_preference_and_failure_isolation(monkeypatch):
    calls = {"bad": 0}
    async def good(comp, fx): return {1: {"home": [(2.0, "OtherBook")], "over15": [(1.30, "SportyBet")]}}
    async def good2(comp, fx): return {1: {"home": [(2.2, "AnotherBook")], "over15": [(1.40, "BigBook")]}}
    async def bad(comp, fx):
        calls["bad"] += 1
        raise RuntimeError("HTTP 401 invalid key")
    monkeypatch.setattr(odds, "PROVIDERS", {"a": ("A", lambda: "k", good), "b": ("B", lambda: "k", good2), "c": ("C", lambda: "k", bad)})
    monkeypatch.setattr(config, "ODDS_PROVIDERS", [])
    monkeypatch.setattr(config, "PREFERRED_BOOKMAKERS", ["sportybet"])
    async def up(comp, days): return FIXTURES
    monkeypatch.setattr(providers, "upcoming", up)

    merged, status = asyncio.run(odds.gather("PL"))
    assert merged[1]["over15"]["bookmaker"] == "SportyBet" and merged[1]["over15"]["preferred"] is True   # preferred wins over higher 1.40
    assert merged[1]["home"]["odds"] == 2.2 and merged[1]["home"]["preferred"] is False                 # no preferred quote: best overall
    assert [s["ok"] for s in status] == [True, True, False] and "401" in status[2]["error"]
    asyncio.run(odds.gather("PL"))
    assert calls["bad"] == 1    # failing provider is not hammered again straight away


def test_gather_without_keys_is_noop(monkeypatch):
    monkeypatch.setattr(config, "ODDS_API_KEY", ""); monkeypatch.setattr(config, "API_FOOTBALL_KEY", ""); monkeypatch.setattr(config, "ODDSAPIIO_KEY", "")
    assert asyncio.run(odds.gather("PL")) == ({}, [])
