"""Provider adapter parsing and HTTP resilience. Payloads below are SYNTHETIC
samples shaped like each provider's documented response format."""

from datetime import datetime, timezone

import httpx
import pytest

from app.providers.api_football import parse_injuries, parse_lineups
from app.providers.base import ProviderError
from app.providers.football_data_co_uk import parse_csv, season_code
from app.providers.football_data_org import parse_matches
from app.providers.http import ProviderHttpClient
from app.providers.the_odds_api import parse_events

CSV = (
    "﻿Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HS,AS,HST,AST,HxG,AxG,B365H,B365D,B365A,"
    "AvgH,AvgD,AvgA,AvgCH,AvgCD,AvgCA,Avg>2.5,Avg<2.5,AHh,AvgAHH,AvgAHA\n"
    "E0,21/08/2026,20:00,Alpha,Beta,3,0,H,2,0,20,4,6,1,1.88,0.20,1.20,7.0,13.0,1.19,6.77,14.19,1.20,6.72,14.0,"
    "1.55,2.38,-2,1.99,1.76\n"
    "E0,22/08/2026,12:30,Gamma,Delta,,,,,,,,,,,,8.5,5.0,1.36,8.37,4.93,1.36,,,,,,,,\n"
    "XX,22/08/2026,12:30,Ignored,League,1,1,D,,,,,,,,,,,,,,,,,,,,,,\n"
)


def test_fdcuk_parses_results_stats_odds_and_converts_uk_time_to_utc():
    fixtures = parse_csv(CSV.encode(), upcoming=False)
    assert len(fixtures) == 2  # unknown division skipped
    f = fixtures[0]
    assert f.kickoff_utc == datetime(2026, 8, 21, 19, 0, tzinfo=timezone.utc)  # BST -> UTC
    assert (f.home_goals, f.away_goals, f.status) == (3, 0, "finished")
    assert f.home_stats.xg == pytest.approx(1.88)
    kinds = {(o.bookmaker_key, o.market, o.kind) for o in f.odds}
    assert ("avg", "1x2", "closing") in kinds and ("avg", "totals", "pre_match") in kinds
    ah = [o for o in f.odds if o.market == "asian_handicap"]
    assert ah and ah[0].line == -2.0
    pre = [o for o in f.odds if o.kind == "pre_match"]
    assert all(o.observed_at < f.kickoff_utc for o in pre)
    # second row has no result -> scheduled, never invented
    assert fixtures[1].status == "scheduled" and fixtures[1].home_goals is None


def test_fdcuk_upcoming_file_never_yields_closing_odds():
    observed = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
    fixtures = parse_csv(CSV.encode(), upcoming=True, observed_at=observed)
    assert all(o.kind == "pre_match" and o.observed_at == observed for f in fixtures for o in f.odds)
    assert all(f.status == "scheduled" for f in fixtures)


def test_season_code():
    assert season_code(2026) == "2627"
    assert season_code(1999) == "9900"


def test_football_data_org_status_mapping():
    payload = {"matches": [
        {"id": 1, "utcDate": "2026-10-31T15:00:00Z", "status": "POSTPONED", "stage": "REGULAR_SEASON",
         "homeTeam": {"name": "Alpha FC", "shortName": "Alpha"}, "awayTeam": {"name": "Beta FC", "shortName": "Beta"},
         "score": {"fullTime": {"home": None, "away": None}, "halfTime": {}}, "referees": []},
        {"id": 2, "utcDate": "2026-10-20T19:00:00Z", "status": "FINISHED", "stage": "REGULAR_SEASON",
         "homeTeam": {"name": "Gamma FC"}, "awayTeam": {"name": "Delta FC"},
         "score": {"fullTime": {"home": 2, "away": 1}, "halfTime": {"home": 1, "away": 0}},
         "referees": [{"name": "Ref"}]},
    ]}
    out = parse_matches(payload, "ENG-1")
    assert out[0].status == "postponed" and out[0].home_goals is None
    assert out[1].status == "finished" and (out[1].home_goals, out[1].ht_home_goals) == (2, 1)
    assert out[1].referee == "Ref"


def test_odds_api_parsing_maps_selections():
    payload = [{"id": "e1", "commence_time": "2026-10-31T15:00:00Z", "home_team": "Alpha", "away_team": "Beta",
                "bookmakers": [{"key": "bk", "title": "Book", "last_update": "2026-10-30T10:00:00Z", "markets": [
                    {"key": "h2h", "last_update": "2026-10-30T10:00:00Z", "outcomes": [
                        {"name": "Alpha", "price": 2.1}, {"name": "Beta", "price": 3.5}, {"name": "Draw", "price": 3.3}]},
                    {"key": "totals", "outcomes": [{"name": "Over", "price": 1.9, "point": 2.5},
                                                   {"name": "Under", "price": 1.95, "point": 2.5}]}]}]}]
    f = parse_events(payload, "ENG-1")[0]
    sels = {(o.market, o.selection, o.line): o.decimal_odds for o in f.odds}
    assert sels[("1x2", "home", 0.0)] == 2.1 and sels[("1x2", "draw", 0.0)] == 3.3
    assert sels[("totals", "over", 2.5)] == 1.9


def test_api_football_injuries_are_reported_not_confirmed_and_lineups_confirmed():
    inj = parse_injuries({"response": [
        {"player": {"name": "P One", "type": "Missing Fixture", "reason": "Knee Injury"}, "team": {"name": "Alpha"},
         "fixture": {"id": 9}},
        {"player": {"name": "P Two", "type": "Missing Fixture", "reason": "Red Card"}, "team": {"name": "Alpha"},
         "fixture": {"id": 9}},
        {"player": {"name": "P Three", "type": "Questionable", "reason": "Illness"}, "team": {"name": "Beta"},
         "fixture": {"id": 9}},
    ]})
    assert [i.kind for i in inj] == ["injury", "suspension", "doubtful"]
    assert all(i.verification == "reported" for i in inj)
    lu = parse_lineups({"response": [{"team": {"name": "Alpha"}, "formation": "4-3-3",
                                      "startXI": [{"player": {"name": "GK", "number": 1, "pos": "G"}}],
                                      "substitutes": [{"player": {"name": "Sub", "number": 12, "pos": "G"}}]}]})
    assert lu[0].status == "confirmed" and lu[0].players[0]["starter"] and not lu[0].players[1]["starter"]


def test_http_client_retries_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 3 else httpx.Response(200, content=b"ok")

    client = ProviderHttpClient("test", max_retries=3, backoff_base=0, transport=httpx.MockTransport(handler))
    assert client.get("https://example.test/x").content == b"ok"
    assert calls["n"] == 3


def test_http_client_does_not_leak_api_key_in_errors():
    client = ProviderHttpClient("test", max_retries=0, backoff_base=0,
                                transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    with pytest.raises(ProviderError) as exc:
        client.get("https://example.test/odds", params={"apiKey": "SECRET123"})
    assert "SECRET123" not in str(exc.value)


def test_http_client_gives_up_after_retries():
    client = ProviderHttpClient("test", max_retries=1, backoff_base=0,
                                transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(ProviderError):
        client.get("https://example.test/y")
