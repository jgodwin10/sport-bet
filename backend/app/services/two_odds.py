"""The daily 2 odds slip: analyse today's favourites in depth and publish one accumulator.

Each candidate gets the core checks from app.engine.slip, then the context the model does not
weigh directly: form, venue record, head-to-head, league table, rest, reported absences and the
AI analysis of current news. Context can only remove a leg, never add one, and only the core
checks are covered by the backtest.

`record_two_odds` runs after every prediction and AI refresh. A published slip keeps its legs while
they still pass, so it does not change under someone who already took it, and it is frozen once
its first match kicks off. Results come from the settlement of each leg's selection.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.db.models import (
    AiAnalysis, AvailabilityReport, Backtest, Competition, DailySlip, Fixture, ModelVersion, Prediction, Selection,
    SettledSelection, Team,
)
from app.engine.slip import (
    FAIL, NOTE, PASS, UNCHECKED, Check, SlipLeg, SlipRules, build_slip, combined_odds,
    combined_probability, core_checks, in_range, leg_passes,
)
from app.services.analytics import head_to_head, standings, summarise_form, team_recent
from app.services.top_picks import latest_prediction_ids

RULES = SlipRules()
LEG_SELECTIONS = ("home", "away")
AI_MAX_AGE_HOURS = 24.0
AI_MAX_DOUBT = 0.10  # the AI's own chance may sit this far below ours before the leg is dropped
FORM_MATCHES = 6
H2H_YEARS = 4
MIN_REST_DAYS, RESTED_DAYS = 3, 5
MAX_ABSENCES = 3
VOID_STATUSES = ("postponed", "abandoned", "cancelled")
LEG_MULTIPLIER = {"win": None, "push": 1.0, "void": 1.0, "loss": 0.0}  # None: the leg's odds


@dataclass
class Candidate:
    selection: Selection
    prediction: Prediction
    fixture: Fixture
    competition: str
    home: Team
    away: Team
    checks: list[Check] = field(default_factory=list)


def slip_day(now: datetime, tz: str) -> date:
    return now.astimezone(ZoneInfo(tz)).date()


def day_bounds(day: date, tz: str) -> tuple[datetime, datetime]:
    zone, nxt = ZoneInfo(tz), day + timedelta(days=1)
    return (datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(timezone.utc),
            datetime(nxt.year, nxt.month, nxt.day, tzinfo=zone).astimezone(timezone.utc))


def candidates(db: Session, now: datetime, start: datetime, end: datetime) -> list[Candidate]:
    """Priced favourites kicking off in the window, strongest first."""
    ht, at = aliased(Team), aliased(Team)
    rows = db.execute(
        select(Selection, Prediction, Fixture, Competition.code, ht, at)
        .join(Prediction, Prediction.id == Selection.prediction_id)
        .join(Fixture, Fixture.id == Selection.fixture_id)
        .join(Competition, Competition.id == Fixture.competition_id)
        .join(ht, ht.id == Fixture.home_team_id).join(at, at.id == Fixture.away_team_id)
        .where(Prediction.id.in_(latest_prediction_ids()), Fixture.status == "scheduled",
               Fixture.kickoff_utc > max(now, start), Fixture.kickoff_utc < end,
               Selection.market == "1x2", Selection.selection.in_(LEG_SELECTIONS),
               Selection.probability >= RULES.min_leg_probability)
        .order_by(Selection.probability.desc(), Selection.id)
    )
    return [Candidate(*row) for row in rows]


def candidate_fixture_ids(db: Session, now: datetime, tz: str) -> list[int]:
    """Today's possible legs, for the AI analysis to read first."""
    start, end = day_bounds(slip_day(now, tz), tz)
    return [c.fixture.id for c in candidates(db, now, start, end)][:RULES.pool_size]


# ---------------------------------------------------------------- analysis
def _odds_age(p: Prediction, now: datetime) -> float | None:
    observed = p.data_quality.get("odds_latest_observed")
    return (now - datetime.fromisoformat(observed)).total_seconds() / 3600 if observed else None


def _form_check(team: str, mine: dict, theirs: dict, opponent: str) -> Check:
    a, b = mine.get("last_5"), theirs.get("last_5")
    seq = mine.get("sequence", "")[:FORM_MATCHES]
    if not a or not b:
        return Check("form", "Recent form", UNCHECKED, "too few recent matches to compare")
    ok = a["points_per_game"] >= b["points_per_game"]
    return Check("form", "Recent form", PASS if ok else NOTE,
                 f"{team} {seq}: {a['points_per_game']:.1f} points a game over 5, {opponent} {b['points_per_game']:.1f}")


def _venue_check(team: str, split: dict | None, venue: str) -> Check:
    if not split or split["matches"] < 3:
        return Check("venue", f"{venue} record", UNCHECKED, f"too few recent {venue.lower()} matches")
    ok = split["points_per_game"] >= 1.5
    return Check("venue", f"{venue} record", PASS if ok else NOTE,
                 f"{team}: {split['wins']}W {split['draws']}D {split['losses']}L in the last {split['matches']} "
                 f"{venue.lower()} matches")


def _h2h_check(team: str, meetings: list[dict]) -> Check:
    recent = [m for m in meetings if m["age_days"] <= H2H_YEARS * 365]
    if len(recent) < 2:
        return Check("h2h", "Head to head", UNCHECKED, "fewer than two meetings in the last four years")
    wins = losses = 0
    for m in recent:
        mine, theirs = (m["home_goals"], m["away_goals"]) if m["home"] == team else (m["away_goals"], m["home_goals"])
        wins += mine > theirs
        losses += mine < theirs
    return Check("h2h", "Head to head", PASS if losses <= wins else NOTE,
                 f"{team} won {wins}, lost {losses} of the last {len(recent)} meetings")


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _table_check(db: Session, f: Fixture, backed: int, opponent: int, team: str, now: datetime) -> Check:
    if f.competition.format == "cup":
        return Check("table", "League table", UNCHECKED, "a cup has no league table")
    pos = {r["team_id"]: r for r in standings(db, f.season_id, now)}
    a, b = pos.get(backed), pos.get(opponent)
    if not a or not b or a["played"] < 5:
        return Check("table", "League table", UNCHECKED, "too early in the season to read the table")
    return Check("table", "League table", PASS if a["position"] < b["position"] else NOTE,
                 f"{team} {_ordinal(a['position'])} on {a['points']} points, "
                 f"opponent {_ordinal(b['position'])} on {b['points']}")


def _rest_check(team: str, mine: list[dict], theirs: list[dict], kickoff: datetime) -> Check:
    if not mine or not theirs:
        return Check("rest", "Rest", UNCHECKED, "no recent match dates")
    a, b = ((kickoff - datetime.fromisoformat(rows[0]["date"])).days for rows in (mine, theirs))
    tired = a < MIN_REST_DAYS and b >= RESTED_DAYS
    return Check("rest", "Rest", NOTE if tired else PASS, f"{team} {a} days since their last match, opponent {b}")


def _absences_check(db: Session, f: Fixture, team_id: int, team: str, now: datetime) -> Check:
    rows = db.scalars(select(AvailabilityReport).where(
        AvailabilityReport.fixture_id == f.id, AvailabilityReport.team_id == team_id,
        AvailabilityReport.retrieved_at <= now).order_by(AvailabilityReport.retrieved_at.desc()))
    latest = {}
    for a in rows:
        latest.setdefault(a.player_name, a)
    out = [a.player_name for a in latest.values() if a.kind in ("injury", "suspension")]
    if not latest:
        return Check("absences", "Reported absences", UNCHECKED, "no injury or suspension data for this match")
    names = ", ".join(out[:4]) or "nobody"
    return Check("absences", "Reported absences", NOTE if len(out) >= MAX_ABSENCES else PASS, f"{team}: {names} out")


def _ai_check(a: AiAnalysis | None, c: Candidate, configured: bool, now: datetime) -> Check:
    label = "AI news check"
    if not configured:
        return Check("ai", label, UNCHECKED, "AI analysis is not set up, so current news was not read")
    if a is None or now - a.created_at > timedelta(hours=AI_MAX_AGE_HOURS):
        return Check("ai", label, FAIL, "waiting for an analysis of current team news")
    content = a.content or {}
    summary = content.get("model_assessment") or content.get("summary") or ""
    ai_p = (content.get("probability_view") or {}).get(c.selection.selection)
    if ai_p is not None and ai_p < c.selection.probability - AI_MAX_DOUBT:
        return Check("ai", label, FAIL, f"the AI puts this at {ai_p:.0%} after reading the news. {summary}".strip())
    status = NOTE if content.get("confidence") == "low" else PASS
    prefix = f"The AI puts this at {ai_p:.0%}. " if ai_p is not None else ""
    return Check("ai", label, status, f"{prefix}{summary}".strip())


def analyse(db: Session, c: Candidate, ai_configured: bool, now: datetime) -> list[Check]:
    s, p, f = c.selection, c.prediction, c.fixture
    home_side = s.selection == "home"
    backed, opponent = (c.home, c.away) if home_side else (c.away, c.home)
    components = (p.components or {}).get("one_x_two", {})
    sizes = (p.data_quality.get("sample_sizes") or {}).values()
    checks = core_checks(s.selection, s.probability, s.fair_probability, s.decimal_odds, p.reliability["score"],
                         (p.components or {}).get("disagreement"), min(sizes, default=0), _odds_age(p, now),
                         components, RULES)
    mine, theirs = team_recent(db, backed.id, now), team_recent(db, opponent.id, now)
    form_mine, form_theirs = summarise_form(mine), summarise_form(theirs)
    latest = db.scalar(select(AiAnalysis).where(AiAnalysis.fixture_id == f.id, AiAnalysis.status == "ok")
                       .order_by(AiAnalysis.created_at.desc(), AiAnalysis.id.desc()).limit(1))
    checks += [
        _form_check(backed.name, form_mine, form_theirs, opponent.name),
        _venue_check(backed.name, form_mine["home" if home_side else "away"], "Home" if home_side else "Away"),
        _h2h_check(backed.name, head_to_head(db, f.home_team_id, f.away_team_id, now)),
        _table_check(db, f, backed.id, opponent.id, backed.name, now),
        _rest_check(backed.name, mine, theirs, f.kickoff_utc),
        _absences_check(db, f, backed.id, backed.name, now),
        _ai_check(latest, c, ai_configured, now),
    ]
    return checks


# ---------------------------------------------------------------- recording
def _leg_row(c: Candidate) -> dict:
    return {"selection_id": c.selection.id, "fixture_id": c.fixture.id, "checks": [x.to_dict() for x in c.checks]}


def _rejected_row(c: Candidate) -> dict:
    reasons = [x.detail for x in c.checks if x.status == FAIL] or [x.detail for x in c.checks if x.status == NOTE]
    return {"fixture_id": c.fixture.id, "match": f"{c.home.name} v {c.away.name}", "selection": c.selection.selection,
            "home": c.home.name, "away": c.away.name, "probability": c.selection.probability,
            "odds": c.selection.decimal_odds, "reasons": reasons}


def record_two_odds(db: Session, now: datetime, tz: str, ai_configured: bool) -> dict:
    """Build or refresh today's slip. A slip whose first match has kicked off is left untouched."""
    day = slip_day(now, tz)
    slip = db.get(DailySlip, day)
    if slip is not None and slip.legs and _first_kickoff(db, slip) <= now:
        return {"date": day.isoformat(), "legs": len(slip.legs), "frozen": True}

    start, end = day_bounds(day, tz)
    pool = candidates(db, now, start, end)
    for c in pool:
        c.checks = analyse(db, c, ai_configured, now)
    passing = {(c.fixture.id, c.selection.selection): c for c in pool if leg_passes(c.checks, RULES)}

    chosen = _keep_existing(db, slip, passing)
    kept = chosen is not None
    if not kept:
        built = build_slip([SlipLeg(k[0], c.selection.probability, c.selection.decimal_odds, c)
                            for k, c in passing.items()], RULES)
        chosen = [leg.payload for leg in built] if built else []
    # Kickoff order: the slip reads the way it will play out
    chosen = sorted(chosen, key=lambda c: (c.fixture.kickoff_utc, c.fixture.id))

    used = {c.fixture.id for c in chosen}
    rejected = [_rejected_row(c) for c in pool if c.fixture.id not in used and not leg_passes(c.checks, RULES)]
    spare = len(passing) - len(chosen)
    legs = [SlipLeg(c.fixture.id, c.selection.probability, c.selection.decimal_odds) for c in chosen]

    if slip is None:
        slip = DailySlip(slip_date=day, first_built_at=now, legs=[], changes=[])
        db.add(slip)
    before = {row["fixture_id"] for row in slip.legs}
    if slip.legs and before != used:
        slip.changes = [*slip.changes, {"at": now.isoformat(), "reason": _change_reason(chosen)}]
    slip.legs = [_leg_row(c) for c in chosen]
    slip.combined_odds = round(combined_odds(legs), 4) if legs else None
    slip.combined_probability = round(combined_probability(legs), 4) if legs else None
    slip.analysed, slip.rejected, slip.spare, slip.updated_at = len(pool), rejected, spare, now
    db.commit()
    return {"date": day.isoformat(), "legs": len(chosen), "analysed": len(pool), "kept": kept,
            "odds": slip.combined_odds, "probability": slip.combined_probability}


def _change_reason(chosen: Sequence[Candidate]) -> str:
    return ("A leg stopped passing its checks, so the slip was rebuilt." if chosen
            else "A leg stopped passing its checks and no other combination qualifies, so the slip was withdrawn.")


def _keep_existing(db: Session, slip: DailySlip | None, passing: dict[tuple[int, str], Candidate]) -> list[Candidate] | None:
    """The published legs at their latest prices, if all still pass and the odds are still in range."""
    if slip is None or not slip.legs:
        return None
    out = []
    for row in slip.legs:
        sel = db.get(Selection, row["selection_id"])
        c = passing.get((row["fixture_id"], sel.selection))
        if c is None:
            return None
        out.append(c)
    return out if in_range(combined_odds([SlipLeg(c.fixture.id, 0, c.selection.decimal_odds) for c in out]), RULES) else None


def _first_kickoff(db: Session, slip: DailySlip) -> datetime:
    return min(db.get(Fixture, row["fixture_id"]).kickoff_utc for row in slip.legs)


# ---------------------------------------------------------------- reading
def _leg_outcome(f: Fixture, st: SettledSelection | None) -> str | None:
    if st is not None:
        return st.outcome
    return "void" if f.status in VOID_STATUSES else None


def slip_status(outcomes: Sequence[str | None]) -> str:
    if not outcomes:
        return "none"
    if "loss" in outcomes:
        return "lost"
    if None in outcomes:
        return "pending"
    return "won" if "win" in outcomes else "void"


def settled_odds(rows: Sequence[tuple[float, str | None]]) -> float:
    """What the slip paid per unit: a void leg counts as odds of 1, as bookmakers settle it."""
    out = 1.0
    for odds, outcome in rows:
        multiplier = LEG_MULTIPLIER.get(outcome, 1.0)
        out *= odds if multiplier is None else multiplier
    return out


def load_legs(db: Session, slip: DailySlip) -> list[dict]:
    ht, at = aliased(Team), aliased(Team)
    ids = [row["selection_id"] for row in slip.legs]
    if not ids:
        return []
    found = {s.id: (s, p, f, comp, home, away, st) for s, p, f, comp, home, away, st in db.execute(
        select(Selection, Prediction, Fixture, Competition.code, ht, at, SettledSelection)
        .join(Prediction, Prediction.id == Selection.prediction_id)
        .join(Fixture, Fixture.id == Selection.fixture_id)
        .join(Competition, Competition.id == Fixture.competition_id)
        .join(ht, ht.id == Fixture.home_team_id).join(at, at.id == Fixture.away_team_id)
        .outerjoin(SettledSelection, SettledSelection.selection_id == Selection.id)
        .where(Selection.id.in_(ids)))}
    legs = []
    for row in slip.legs:
        s, p, f, comp, home, away, st = found[row["selection_id"]]
        legs.append({"selection": s, "prediction": p, "fixture": f, "competition": comp, "home": home, "away": away,
                     "settled": st, "outcome": _leg_outcome(f, st), "checks": row["checks"]})
    return legs


def track_record(db: Session, limit: int = 60) -> dict:
    """Slips staked at 1 unit each. A slip counts once all its legs have a result or one has lost."""
    slips = list(db.scalars(select(DailySlip).order_by(DailySlip.slip_date)))
    history = []
    won = lost = void = no_slip = 0
    running = staked = expected = 0.0
    for slip in slips:
        if not slip.legs:
            no_slip += 1
            continue
        legs = load_legs(db, slip)
        status = slip_status([leg["outcome"] for leg in legs])
        profit = None
        if status in ("won", "lost", "void"):
            paid = settled_odds([(leg["selection"].decimal_odds, leg["outcome"]) for leg in legs])
            profit = paid - 1 if status != "lost" else -1.0
            won, lost, void = won + (status == "won"), lost + (status == "lost"), void + (status == "void")
            running += profit
            if status != "void":
                staked += 1
                expected += slip.combined_probability or 0.0
        history.append({"slip": slip, "legs": legs, "status": status, "profit": profit, "running_profit": running})
    pending = sum(h["status"] == "pending" for h in history)
    return {
        "summary": {"slips": len(history), "settled": won + lost, "pending": pending, "won": won, "lost": lost,
                    "void": void, "profit": round(running, 4), "roi": round(running / staked, 4) if staked else None,
                    "hit_rate": round(won / staked, 4) if staked else None,
                    "expected_hit_rate": round(expected / staked, 4) if staked else None, "days_without_slip": no_slip},
        "history": history[::-1][:limit],
        "backtest": _latest_backtest(db),
    }


def _latest_backtest(db: Session) -> dict | None:
    """Walk-forward results of this slip from the deployed model's backtest, if it has them."""
    version = db.scalar(select(ModelVersion).where(ModelVersion.status == "deployed")
                        .order_by(ModelVersion.created_at.desc()).limit(1))
    bt = db.get(Backtest, version.backtest_id) if version and version.backtest_id else None
    return (bt.metrics or {}).get("two_odds") if bt else None

