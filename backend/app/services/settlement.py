"""Settle selections against stored results and compute closing-line value."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DataConflict, Fixture, MatchResult, Selection, SettledSelection
from app.services.analytics import odds_at


def settle_asian(goal_diff: int, line: float) -> tuple[str, float]:
    """Outcome and profit multiplier for a side with handicap `line`, where
    goal_diff is that side's goals minus the opponent's. Profit is in units of
    (odds - 1) for wins; returns (outcome, win_fraction) with win_fraction in
    {1, 0.5, 0, -0.5, -1}."""
    parts = [line - 0.25, line + 0.25] if (line * 4) % 2 != 0 else [line]
    scores = []
    for part in parts:
        v = goal_diff + part
        scores.append(1 if v > 0 else 0 if v == 0 else -1)
    s = sum(scores) / len(scores)
    return {1: "win", 0.5: "half_win", 0: "push", -0.5: "half_loss", -1: "loss"}[s], s


def selection_profit(sel: Selection, home_goals: int, away_goals: int) -> tuple[str, float]:
    odds = sel.decimal_odds
    if sel.market == "1x2":
        actual = "home" if home_goals > away_goals else "draw" if home_goals == away_goals else "away"
        return ("win", odds - 1) if sel.selection == actual else ("loss", -1.0)
    if sel.market.startswith("totals_"):
        over = home_goals + away_goals > sel.line
        won = over if sel.selection == "over" else not over
        return ("win", odds - 1) if won else ("loss", -1.0)
    if sel.market == "asian_handicap":
        side, line_txt = sel.selection.split()
        gd = home_goals - away_goals if side == "home" else away_goals - home_goals
        outcome, frac = settle_asian(gd, float(line_txt))
        profit = {1: odds - 1, 0.5: (odds - 1) / 2, 0: 0.0, -0.5: -0.5, -1: -1.0}[frac]
        return outcome, profit
    raise ValueError(f"cannot settle market {sel.market}")


def settle_finished(db: Session) -> dict:
    q = (
        select(Selection, Fixture, MatchResult)
        .join(Fixture, Fixture.id == Selection.fixture_id)
        .join(MatchResult, MatchResult.fixture_id == Fixture.id)
        .outerjoin(SettledSelection, SettledSelection.selection_id == Selection.id)
        .where(SettledSelection.selection_id.is_(None), Fixture.status == "finished")
    )
    settled = withheld = 0
    disputed = set(db.scalars(select(DataConflict.entity_id).where(
        DataConflict.entity_type == "match_result", DataConflict.resolved.is_(False))))
    closing_cache: dict[int, object] = {}
    for sel, fx, res in db.execute(q):
        if fx.id in disputed:
            withheld += 1
            continue
        outcome, profit = selection_profit(sel, res.home_goals, res.away_goals)
        if fx.id not in closing_cache:
            closing = odds_at(db, fx.id, fx.kickoff_utc, kind="closing")
            if not closing.rows:  # fall back to the last pre-match price in the final hour
                late = odds_at(db, fx.id, fx.kickoff_utc)
                closing = type(late)([r for r in late.rows
                                      if r["observed_at"] >= fx.kickoff_utc - timedelta(hours=1)])
            closing_cache[fx.id] = closing
        view = closing_cache[fx.id]
        market = "1x2" if sel.market == "1x2" else "totals" if sel.market.startswith("totals_") else "asian_handicap"
        books = view.books(market, sel.line)
        selection_key = sel.selection.split()[0]
        close = (books.get(sel.bookmaker or "", {}).get(selection_key) or books.get("avg", {}).get(selection_key))
        db.add(SettledSelection(selection_id=sel.id, outcome=outcome, profit=profit, closing_odds=close,
                                clv=(sel.decimal_odds / close - 1) if close else None))
        settled += 1
    db.commit()
    return {"settled": settled, "withheld_due_to_conflict": withheld}
