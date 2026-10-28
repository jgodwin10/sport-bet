"""Top picks: the best priced selection per upcoming match, ranked across matches.

Ranking uses the model only. Each selection is scored by its expected value at the cautious
end of the probability interval (falling back to the point estimate), scaled by data
reliability, so a big edge on thin data does not outrank a solid one. Selections that pass
every rule come first; the list is topped up with positive-value selections that failed a
check, which are labelled as such.

Each prediction run records the list (`record_top_picks`) so its results can be tracked: a
match's entry follows the list until kickoff and is then frozen, and `track_record` reports
level-stakes P&L from the settled selections.

The AI analysis is attached for reading only: whether its own 1X2 view still sees value at
the offered odds. It does not move a pick, for the reasons in app.services.ai_analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.db.models import AiAnalysis, Competition, Fixture, Prediction, Selection, SettledSelection, Team, TopPickEntry


def latest_prediction_ids():
    """Latest snapshot per fixture: predictions are only made before kickoff,
    so this is also the final pre-match decision for settled fixtures."""
    return select(func.max(Prediction.id)).group_by(Prediction.fixture_id).scalar_subquery()


@dataclass
class TopPick:
    selection: Selection
    prediction: Prediction
    fixture: Fixture
    competition: str
    home: Team
    away: Team
    score: float
    tier: str  # recommended|watchlist
    ai: dict | None = None


def pick_score(s: Selection, reliability: float) -> float:
    p = s.probability_lower if s.probability_lower is not None else s.probability
    return (p * s.decimal_odds - 1) * reliability / 100


def ai_view(a: AiAnalysis, s: Selection, prediction_id: int) -> dict:
    content = a.content or {}
    view, verdict, ai_p = content.get("probability_view"), None, None
    if s.market == "1x2" and view and s.selection in view:
        ai_p = view[s.selection]
        verdict = "supports" if ai_p * s.decimal_odds > 1 else "doubts"
    return {"analysis_id": a.id, "created_at": a.created_at, "summary": content.get("summary", ""),
            "confidence": content.get("confidence"), "probability": ai_p, "verdict": verdict,
            "current": a.prediction_id == prediction_id}


def top_picks(db: Session, now: datetime, limit: int = 10, days: int = 7) -> list[TopPick]:
    ht, at = aliased(Team), aliased(Team)
    rows = db.execute(
        select(Selection, Prediction, Fixture, Competition.code, ht, at)
        .join(Prediction, Prediction.id == Selection.prediction_id)
        .join(Fixture, Fixture.id == Selection.fixture_id)
        .join(Competition, Competition.id == Fixture.competition_id)
        .join(ht, ht.id == Fixture.home_team_id).join(at, at.id == Fixture.away_team_id)
        .where(Prediction.id.in_(latest_prediction_ids()), Fixture.status == "scheduled",
               Fixture.kickoff_utc > now, Fixture.kickoff_utc < now + timedelta(days=days),
               Selection.expected_value > 0)
    )
    best: dict[int, TopPick] = {}
    for s, p, f, comp, home, away in rows:
        pick = TopPick(s, p, f, comp, home, away, pick_score(s, p.reliability["score"]),
                       "recommended" if s.qualifies else "watchlist")
        cur = best.get(f.id)
        if cur is None or (pick.tier == "recommended", pick.score) > (cur.tier == "recommended", cur.score):
            best[f.id] = pick
    picks = sorted(best.values(), key=lambda t: (t.tier != "recommended", -t.score, t.fixture.kickoff_utc))[:limit]

    analyses: dict[int, AiAnalysis] = {}
    if picks:
        for a in db.scalars(select(AiAnalysis).where(
                AiAnalysis.fixture_id.in_([t.fixture.id for t in picks]), AiAnalysis.status == "ok")
                .order_by(AiAnalysis.created_at, AiAnalysis.id)):
            analyses[a.fixture_id] = a  # ordered ascending: last one wins
    for t in picks:
        if a := analyses.get(t.fixture.id):
            t.ai = ai_view(a, t.selection, t.prediction.id)
    return picks


def record_top_picks(db: Session, now: datetime) -> dict:
    """Store the current Top 10. Entries of matches that have kicked off are left untouched."""
    picks = top_picks(db, now)
    open_entries = {e.fixture_id: e for e in db.scalars(
        select(TopPickEntry).join(Fixture, Fixture.id == TopPickEntry.fixture_id).where(Fixture.kickoff_utc > now))}
    listed = set()
    for rank, t in enumerate(picks, 1):
        fid = t.fixture.id
        listed.add(fid)
        e = open_entries.get(fid)
        if e is None:
            e = TopPickEntry(fixture_id=fid, best_rank=rank, first_listed_at=now)
            db.add(e)
        e.selection_id, e.rank, e.tier, e.in_list = t.selection.id, rank, t.tier, True
        e.best_rank, e.last_listed_at, e.recorded_at = min(e.best_rank, rank), now, now
    for fid, e in open_entries.items():
        if fid not in listed:
            e.in_list, e.recorded_at = False, now
    db.commit()
    return {"listed": len(listed), "new": len(listed - open_entries.keys()),
            "dropped": len(open_entries.keys() - listed)}


def _tally(rows: list[tuple]) -> dict:
    settled = [st for _, _, st in rows if st is not None]
    profit = sum(st.profit for st in settled)
    return {"picks": len(rows), "settled": len(settled), "pending": len(rows) - len(settled),
            "won": sum(st.outcome in ("win", "half_win") for st in settled),
            "lost": sum(st.outcome in ("loss", "half_loss") for st in settled),
            "void": sum(st.outcome in ("push", "void") for st in settled),
            "profit": round(profit, 4), "roi": round(profit / len(settled), 4) if settled else None}


def track_record(db: Session, now: datetime, limit: int = 100) -> dict:
    """Level-stakes (1 unit) results of every match that was in the Top 10 at kickoff."""
    ht, at = aliased(Team), aliased(Team)
    rows = list(db.execute(
        select(TopPickEntry, Selection, Fixture, Competition.code, ht, at, SettledSelection)
        .join(Selection, Selection.id == TopPickEntry.selection_id)
        .join(Fixture, Fixture.id == TopPickEntry.fixture_id)
        .join(Competition, Competition.id == Fixture.competition_id)
        .join(ht, ht.id == Fixture.home_team_id).join(at, at.id == Fixture.away_team_id)
        .outerjoin(SettledSelection, SettledSelection.selection_id == Selection.id)
        .where(Fixture.kickoff_utc <= now)
        .order_by(Fixture.kickoff_utc, Fixture.id)
    ))
    counted = [(e, s, st) for e, s, _, _, _, _, st in rows if e.in_list]
    running, history = 0.0, []
    for e, s, f, comp, home, away, st in rows:
        if e.in_list and st is not None:
            running += st.profit
        history.append({"entry": e, "selection": s, "fixture": f, "competition": comp, "home": home, "away": away,
                        "settled": st, "counted": e.in_list, "running_profit": round(running, 4)})
    return {"summary": {"all": _tally(counted),
                        **{tier: _tally([r for r in counted if r[0].tier == tier])
                           for tier in ("recommended", "watchlist")}},
            "dropped": sum(not e.in_list for e, *_ in rows),
            "history": history[::-1][:limit]}
