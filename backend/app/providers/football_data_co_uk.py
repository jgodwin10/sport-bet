"""football-data.co.uk adapter.

Free CSV files (no key), published for personal/research use:
* /mmz4281/{yyYY}/{DIV}.csv - season results, match stats and bookmaker odds.
  "Pre-match" odds are snapshots the site collects before kickoff (typically the
  afternoon before weekend or midweek rounds); columns with a "C" (e.g. AvgCH)
  are closing odds. xG columns (HxG/AxG) only exist in recent seasons.
* /fixtures.csv - the coming round across divisions, with pre-match odds.

Kickoff times are UK local time; they are converted to UTC here. Older seasons
have no kickoff time; those fixtures get 15:00 local and are flagged.
"""

from __future__ import annotations

import io
import logging
import math
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from app.engine.elo import season_of
from app.ingestion.competitions import BY_FDCUK, COMPETITIONS
from app.providers.base import NormalizedFixture, NormalizedOdds, ProviderBatch, TeamStats
from app.providers.http import HttpResult, ProviderHttpClient

log = logging.getLogger(__name__)

PROVIDER = "football_data_co_uk"

BOOKMAKERS = {
    "B365": "Bet365", "BW": "Bet&Win", "PS": "Pinnacle", "WH": "William Hill", "VC": "BetVictor",
    "IW": "Interwetten", "BV": "BetVictor", "BFD": "Betfred", "BMGM": "BetMGM", "CL": "Coral",
    "LB": "Ladbrokes", "PP": "Paddy Power", "SKB": "Sky Bet", "BFE": "Betfair Exchange",
    "Max": "Market maximum", "Avg": "Market average",
}
# Over/under 2.5 and AH columns use a different prefix for Pinnacle
TOTALS_PREFIX = {"B365": "B365", "P": "PS", "Max": "Max", "Avg": "Avg", "BFE": "BFE"}


def season_code(start_year: int) -> str:
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def _num(row: pd.Series, col: str) -> float | None:
    v = row.get(col)
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _int(row: pd.Series, col: str) -> int | None:
    v = _num(row, col)
    return None if v is None else int(v)


def _parse_kickoff(row: pd.Series, tz: ZoneInfo) -> tuple[datetime, bool]:
    raw_date = str(row["Date"]).strip()
    fmt = "%d/%m/%Y" if len(raw_date.split("/")[-1]) == 4 else "%d/%m/%y"
    d = datetime.strptime(raw_date, fmt).date()
    raw_time = row.get("Time")
    approximate = not isinstance(raw_time, str) or ":" not in raw_time
    t = time(15, 0) if approximate else datetime.strptime(raw_time.strip(), "%H:%M").time()
    return datetime.combine(d, t, tzinfo=tz).astimezone(timezone.utc), approximate


def parse_odds(
    row: pd.Series, kickoff: datetime, pre_match_observed: datetime, include_closing: bool = True
) -> list[NormalizedOdds]:
    out: list[NormalizedOdds] = []

    def add(bk: str, market: str, selection: str, col: str, kind: str, line: float = 0.0) -> None:
        if kind == "closing" and not include_closing:
            return
        price = _num(row, col)
        if price is not None and price > 1.0:
            observed = kickoff if kind == "closing" else pre_match_observed
            out.append(NormalizedOdds(bk.lower(), BOOKMAKERS.get(bk, bk), market, selection, price, kind,
                                      observed, line))

    for bk in BOOKMAKERS:
        for sel, suffix in (("home", "H"), ("draw", "D"), ("away", "A")):
            add(bk, "1x2", sel, f"{bk}{suffix}", "pre_match")
            add(bk, "1x2", sel, f"{bk}C{suffix}", "closing")
    for prefix, bk in TOTALS_PREFIX.items():
        add(bk, "totals", "over", f"{prefix}>2.5", "pre_match", 2.5)
        add(bk, "totals", "under", f"{prefix}<2.5", "pre_match", 2.5)
        add(bk, "totals", "over", f"{prefix}C>2.5", "closing", 2.5)
        add(bk, "totals", "under", f"{prefix}C<2.5", "closing", 2.5)
        line, cline = _num(row, "AHh"), _num(row, "AHCh")
        if line is not None:
            add(bk, "asian_handicap", "home", f"{prefix}AHH", "pre_match", line)
            add(bk, "asian_handicap", "away", f"{prefix}AHA", "pre_match", line)
        if cline is not None:
            add(bk, "asian_handicap", "home", f"{prefix}CAHH", "closing", cline)
            add(bk, "asian_handicap", "away", f"{prefix}CAHA", "closing", cline)
    return out


def parse_csv(content: bytes, *, upcoming: bool, observed_at: datetime | None = None) -> list[NormalizedFixture]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    df = pd.read_csv(io.StringIO(text), on_bad_lines="skip")
    df = df.dropna(subset=["Div", "Date", "HomeTeam", "AwayTeam"])
    fixtures: list[NormalizedFixture] = []
    for _, row in df.iterrows():
        comp = BY_FDCUK.get(str(row["Div"]).strip())
        if comp is None:
            continue
        try:
            kickoff, approximate = _parse_kickoff(row, ZoneInfo(comp.timezone))
        except ValueError:
            log.warning("unparseable date in %s row: %s", row.get("Div"), row.get("Date"))
            continue
        home_goals, away_goals = _int(row, "FTHG"), _int(row, "FTAG")
        finished = not upcoming and home_goals is not None and away_goals is not None
        # Historical pre-match prices were collected before kickoff, but the exact
        # time is not published; we record them as observed 24h before kickoff.
        pre_obs = observed_at if upcoming and observed_at else kickoff - timedelta(hours=24)
        fx = NormalizedFixture(
            provider=PROVIDER,
            provider_fixture_id=None,
            competition_code=comp.code,
            season_label=season_of(kickoff.date()),
            home_name=str(row["HomeTeam"]).strip(),
            away_name=str(row["AwayTeam"]).strip(),
            kickoff_utc=kickoff,
            status="finished" if finished else "scheduled",
            referee=str(row["Referee"]).strip() if isinstance(row.get("Referee"), str) else None,
            odds=parse_odds(row, kickoff, pre_obs, include_closing=not upcoming),
            kickoff_approximate=approximate,
        )
        if finished:
            fx.home_goals, fx.away_goals = home_goals, away_goals
            fx.ht_home_goals, fx.ht_away_goals = _int(row, "HTHG"), _int(row, "HTAG")
            fx.home_stats = TeamStats(_int(row, "HS"), _int(row, "HST"), _num(row, "HxG"), _int(row, "HC"),
                                      _int(row, "HF"), _int(row, "HY"), _int(row, "HR"))
            fx.away_stats = TeamStats(_int(row, "AS"), _int(row, "AST"), _num(row, "AxG"), _int(row, "AC"),
                                      _int(row, "AF"), _int(row, "AY"), _int(row, "AR"))
        fixtures.append(fx)
    return fixtures


class FootballDataCoUk:
    name = PROVIDER
    trust_level = 70  # reliable for results/odds; kickoff times are local and sometimes missing

    def __init__(self, base_url: str, client: ProviderHttpClient | None = None, enabled: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.enabled = enabled
        self.client = client or ProviderHttpClient(PROVIDER, min_interval_seconds=1.0)

    @property
    def configured(self) -> bool:
        return self.enabled

    def capabilities(self) -> dict[str, object]:
        return {
            "requires_key": False,
            "fixtures": "upcoming round only (weekly file)",
            "results": True,
            "team_stats": ["shots", "shots_on_target", "corners", "fouls", "cards", "xg (2026-27 onwards)"],
            "odds": "pre-match and closing: 1X2, O/U 2.5, Asian handicap; multiple bookmakers",
            "injuries": False,
            "lineups": False,
            "competitions": sorted(c for c in COMPETITIONS if COMPETITIONS[c].fdcuk),
        }

    def _batch(self, res: HttpResult, resource: str, fixtures: list[NormalizedFixture]) -> ProviderBatch:
        return ProviderBatch(self.name, resource, res.retrieved_at, res.sha256, self.trust_level, fixtures,
                             meta={"last_modified": res.last_modified.isoformat() if res.last_modified else None})

    def season(self, competition_code: str, start_year: int) -> ProviderBatch:
        comp = COMPETITIONS[competition_code]
        if not comp.fdcuk:
            raise ValueError(f"{competition_code} not covered by {self.name}")
        resource = f"/mmz4281/{season_code(start_year)}/{comp.fdcuk}.csv"
        res = self.client.get(self.base_url + resource, cache_ttl=600)
        return self._batch(res, resource, parse_csv(res.content, upcoming=False))

    def upcoming(self) -> ProviderBatch:
        resource = "/fixtures.csv"
        res = self.client.get(self.base_url + resource, cache_ttl=600)
        observed = min(res.last_modified or res.retrieved_at, res.retrieved_at)
        return self._batch(res, resource, parse_csv(res.content, upcoming=True, observed_at=observed))


def current_season_start(today: date) -> int:
    return today.year if today.month >= 7 else today.year - 1
