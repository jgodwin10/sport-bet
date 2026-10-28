"""Read-side queries: training records, odds at a point in time, form, H2H, standings."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, aliased

from app.db.models import (
    Bookmaker, Fixture, MatchResult, OddsSnapshot, Season, Team, TeamMatchStats,
)
from app.engine.features import MatchRecord
from app.services.crests import crest_url


def load_records(db: Session, competition_id: int | list[int], before: datetime,
                 since: datetime | None = None) -> list[MatchRecord]:
    """Finished matches with kickoff strictly before `before`, in kickoff order, from one
    competition or several pooled ones. Team keys are internal team ids (as strings),
    never provider names."""
    ids = competition_id if isinstance(competition_id, list) else [competition_id]
    hs, as_ = aliased(TeamMatchStats), aliased(TeamMatchStats)
    q = (
        select(Fixture, MatchResult, hs, as_)
        .join(MatchResult, MatchResult.fixture_id == Fixture.id)
        .outerjoin(hs, and_(hs.fixture_id == Fixture.id, hs.team_id == Fixture.home_team_id))
        .outerjoin(as_, and_(as_.fixture_id == Fixture.id, as_.team_id == Fixture.away_team_id))
        .where(Fixture.competition_id.in_(ids), Fixture.kickoff_utc < before,
               Fixture.status == "finished")
        .order_by(Fixture.kickoff_utc, Fixture.id)
    )
    if since is not None:
        q = q.where(Fixture.kickoff_utc >= since)
    out = []
    for fx, res, h, a in db.execute(q):
        out.append(MatchRecord(
            key=str(fx.id), kickoff=fx.kickoff_utc, pool=str(fx.competition_id),
            home=str(fx.home_team_id), away=str(fx.away_team_id),
            home_goals=res.home_goals, away_goals=res.away_goals,
            home_shots_on_target=h.shots_on_target if h else None,
            away_shots_on_target=a.shots_on_target if a else None,
            home_xg=h.xg if h else None, away_xg=a.xg if a else None,
        ))
    return out


@dataclass
class OddsView:
    """Latest pre-match price per bookmaker/market/line/selection at a cutoff."""

    rows: list[dict]

    def books(self, market: str, line: float = 0.0) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = defaultdict(dict)
        for r in self.rows:
            if r["market"] == market and abs(r["line"] - line) < 1e-9:
                out[r["bookmaker"]][r["selection"]] = r["odds"]
        return dict(out)

    def lines(self, market: str) -> list[float]:
        return sorted({r["line"] for r in self.rows if r["market"] == market})

    @property
    def latest_observed(self) -> datetime | None:
        return max((r["observed_at"] for r in self.rows), default=None)

    def bookmaker_names(self) -> dict[str, str]:
        return {r["bookmaker"]: r["bookmaker_name"] for r in self.rows}


def odds_at(db: Session, fixture_id: int, cutoff: datetime, kind: str = "pre_match") -> OddsView:
    q = (
        select(OddsSnapshot, Bookmaker.key, Bookmaker.name)
        .join(Bookmaker, Bookmaker.id == OddsSnapshot.bookmaker_id)
        .where(OddsSnapshot.fixture_id == fixture_id, OddsSnapshot.kind == kind,
               OddsSnapshot.observed_at <= cutoff)
        .order_by(OddsSnapshot.observed_at)
    )
    latest: dict[tuple, dict] = {}
    for snap, key, name in db.execute(q):
        latest[(key, snap.market, snap.line, snap.selection)] = {
            "bookmaker": key, "bookmaker_name": name, "market": snap.market, "line": snap.line,
            "selection": snap.selection, "odds": snap.decimal_odds, "observed_at": snap.observed_at,
            "source_record_id": snap.source_record_id,
        }
    return OddsView(list(latest.values()))


def team_recent(db: Session, team_id: int, before: datetime, limit: int = 15) -> list[dict]:
    """Most recent finished matches for a team (any competition), newest first."""
    ht, at = aliased(Team), aliased(Team)
    hs, as_ = aliased(TeamMatchStats), aliased(TeamMatchStats)
    q = (
        select(Fixture, MatchResult, ht, at, hs, as_)
        .join(MatchResult, MatchResult.fixture_id == Fixture.id)
        .join(ht, ht.id == Fixture.home_team_id).join(at, at.id == Fixture.away_team_id)
        .outerjoin(hs, and_(hs.fixture_id == Fixture.id, hs.team_id == Fixture.home_team_id))
        .outerjoin(as_, and_(as_.fixture_id == Fixture.id, as_.team_id == Fixture.away_team_id))
        .where(or_(Fixture.home_team_id == team_id, Fixture.away_team_id == team_id),
               Fixture.kickoff_utc < before)
        .order_by(Fixture.kickoff_utc.desc()).limit(limit)
    )
    rows = []
    for fx, res, hteam, ateam, h, a in db.execute(q):
        home = fx.home_team_id == team_id
        opp = ateam if home else hteam
        gf, ga = (res.home_goals, res.away_goals) if home else (res.away_goals, res.home_goals)
        mine, theirs = (h, a) if home else (a, h)
        rows.append({
            "fixture_id": fx.id, "date": fx.kickoff_utc.isoformat(), "venue": "H" if home else "A",
            "opponent": opp.name, "opponent_id": opp.id, "opponent_logo": crest_url(opp), "goals_for": gf, "goals_against": ga,
            "result": "W" if gf > ga else "D" if gf == ga else "L",
            "xg_for": mine.xg if mine else None, "xg_against": theirs.xg if theirs else None,
            "shots_on_target_for": mine.shots_on_target if mine else None,
            "shots_on_target_against": theirs.shots_on_target if theirs else None,
            "red_cards": mine.red_cards if mine else None,
        })
    return rows


def summarise_form(rows: list[dict]) -> dict:
    """Last 5/10/15 aggregates plus home/away splits. Windows overlap, so they are
    shown for context only and are not fed separately into the model."""

    def agg(sub: list[dict]) -> dict | None:
        if not sub:
            return None
        n = len(sub)

        def mean(key: str) -> float | None:
            vals = [r[key] for r in sub if r[key] is not None]
            return round(sum(vals) / len(vals), 2) if vals else None

        return {
            "matches": n, "wins": sum(r["result"] == "W" for r in sub),
            "draws": sum(r["result"] == "D" for r in sub), "losses": sum(r["result"] == "L" for r in sub),
            "goals_for": sum(r["goals_for"] for r in sub), "goals_against": sum(r["goals_against"] for r in sub),
            "points_per_game": round(sum(3 if r["result"] == "W" else 1 if r["result"] == "D" else 0
                                         for r in sub) / n, 2),
            "clean_sheets": sum(r["goals_against"] == 0 for r in sub),
            "failed_to_score": sum(r["goals_for"] == 0 for r in sub),
            "xg_for": mean("xg_for"), "xg_against": mean("xg_against"),
            "sot_for": mean("shots_on_target_for"), "sot_against": mean("shots_on_target_against"),
            "xg_coverage": sum(r["xg_for"] is not None for r in sub) / n,
        }

    return {
        "last_5": agg(rows[:5]), "last_10": agg(rows[:10]), "last_15": agg(rows[:15]),
        "home": agg([r for r in rows if r["venue"] == "H"][:10]),
        "away": agg([r for r in rows if r["venue"] == "A"][:10]),
        "sequence": "".join(r["result"] for r in rows[:10]),
    }


def head_to_head(db: Session, home_id: int, away_id: int, before: datetime, limit: int = 8) -> list[dict]:
    ht, at = aliased(Team), aliased(Team)
    q = (
        select(Fixture, MatchResult, ht, at, Season.label)
        .join(MatchResult, MatchResult.fixture_id == Fixture.id)
        .join(ht, ht.id == Fixture.home_team_id).join(at, at.id == Fixture.away_team_id)
        .join(Season, Season.id == Fixture.season_id)
        .where(or_(and_(Fixture.home_team_id == home_id, Fixture.away_team_id == away_id),
                   and_(Fixture.home_team_id == away_id, Fixture.away_team_id == home_id)),
               Fixture.kickoff_utc < before)
        .order_by(Fixture.kickoff_utc.desc()).limit(limit)
    )
    return [{"date": fx.kickoff_utc.isoformat(), "season": season, "home": hn.name, "away": an.name,
             "home_logo": crest_url(hn), "away_logo": crest_url(an),
             "home_goals": r.home_goals, "away_goals": r.away_goals,
             "age_days": (before - fx.kickoff_utc).days}
            for fx, r, hn, an, season in db.execute(q)]


def standings(db: Session, season_id: int, before: datetime) -> list[dict]:
    """League table computed from stored results (only matches before `before`)."""
    q = (
        select(Fixture, MatchResult)
        .join(MatchResult, MatchResult.fixture_id == Fixture.id)
        .where(Fixture.season_id == season_id, Fixture.stage == "league", Fixture.kickoff_utc < before)
    )
    table: dict[int, dict] = defaultdict(lambda: {"played": 0, "won": 0, "drawn": 0, "lost": 0, "gf": 0, "ga": 0,
                                                  "points": 0})
    for fx, r in db.execute(q):
        for tid, gf, ga in ((fx.home_team_id, r.home_goals, r.away_goals), (fx.away_team_id, r.away_goals, r.home_goals)):
            t = table[tid]
            t["played"] += 1
            t["gf"] += gf
            t["ga"] += ga
            if gf > ga:
                t["won"] += 1
                t["points"] += 3
            elif gf == ga:
                t["drawn"] += 1
                t["points"] += 1
            else:
                t["lost"] += 1
    names = dict(db.execute(select(Team.id, Team.name).where(Team.id.in_(table.keys()))).all()) if table else {}
    rows = [{"team_id": tid, "team": names.get(tid, str(tid)), **v, "gd": v["gf"] - v["ga"]} for tid, v in table.items()]
    rows.sort(key=lambda r: (-r["points"], -r["gd"], -r["gf"], r["team"]))
    for i, r in enumerate(rows, 1):
        r["position"] = i
    return rows


def last_match_before(db: Session, team_id: int, before: datetime) -> datetime | None:
    return db.scalar(select(Fixture.kickoff_utc).where(
        or_(Fixture.home_team_id == team_id, Fixture.away_team_id == team_id),
        Fixture.kickoff_utc < before, Fixture.status == "finished",
    ).order_by(Fixture.kickoff_utc.desc()).limit(1))
