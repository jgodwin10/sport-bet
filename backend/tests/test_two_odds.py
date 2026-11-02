"""Daily 2 odds slip: checks, search, publishing rules and results. Data SYNTHETIC."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.backtest.engine import slip_summary
from app.core.config import get_settings
from app.db.models import AiAnalysis, DailySlip, Fixture, MatchResult
from app.engine.slip import (
    FAIL, NOTE, PASS, Check, SlipLeg, SlipRules, build_slip, combined_odds, core_checks, leg_passes,
)
from app.ingestion.store import Store
from app.main import create_app
from app.services import two_odds
from app.services.prediction import PredictionService
from app.services.settlement import settle_finished
from tests.conftest import make_batch, synthetic_league

RULES = SlipRules()
COMPONENTS = {"dixon_coles": [0.66, 0.2, 0.14], "elo": [0.62, 0.22, 0.16], "market": [0.65, 0.21, 0.14]}


def good_checks(**over):
    args = dict(selection="home", probability=0.65, fair=0.64, odds=1.5, reliability=80.0, disagreement=0.05,
                min_team_matches=40, odds_age_hours=3.0, components=COMPONENTS, rules=RULES)
    return core_checks(**{**args, **over})


def status(checks, key):
    return next(c.status for c in checks if c.key == key)


def test_core_checks_pass_a_solid_favourite():
    checks = good_checks()
    assert all(c.status == PASS for c in checks) and leg_passes(checks, RULES)


@pytest.mark.parametrize("over,key", [
    ({"probability": 0.59}, "probability"),
    ({"fair": None}, "market"),
    ({"fair": 0.55}, "market"),
    ({"fair": 0.75}, "market"),  # the market being much keener is also a disagreement
    ({"components": {**COMPONENTS, "elo": [0.40, 0.3, 0.3]}}, "models"),
    ({"components": {"market": [0.65, 0.21, 0.14]}}, "models"),
    ({"disagreement": 0.2}, "models"),
    ({"min_team_matches": 24}, "data"),
    ({"reliability": 59.0}, "reliability"),
    ({"odds_age_hours": None}, "odds"),
    ({"odds_age_hours": 25.0}, "odds"),
    ({"odds": 1.05}, "odds"),
])
def test_any_failed_core_check_rules_the_leg_out(over, key):
    checks = good_checks(**over)
    assert status(checks, key) == FAIL and not leg_passes(checks, RULES)


def test_two_context_notes_rule_a_leg_out_but_one_does_not():
    checks = good_checks()
    note = Check("form", "Recent form", NOTE, "worse form")
    assert leg_passes([*checks, note], RULES)
    assert not leg_passes([*checks, note, note], RULES)


def test_away_selection_reads_the_away_component():
    components = {"dixon_coles": [0.14, 0.2, 0.66], "elo": [0.5, 0.3, 0.2]}
    assert status(good_checks(selection="away", components=components), "models") == FAIL


def test_search_takes_the_most_likely_combination_in_range():
    legs = [SlipLeg("a", 0.80, 1.20), SlipLeg("b", 0.75, 1.30), SlipLeg("c", 0.70, 1.40), SlipLeg("d", 0.62, 1.55),
            SlipLeg("e", 0.60, 1.60)]
    slip = build_slip(legs, RULES)
    assert 2.0 <= combined_odds(slip) <= 2.4
    # b+d = 2.02 at 46.5%, b+e = 2.08 at 45%, a+b+c = 2.18 at 42%: the highest chance wins
    assert {leg.fixture for leg in slip} == {"b", "d"}


def test_search_uses_at_most_one_leg_per_fixture_and_can_decline():
    assert build_slip([SlipLeg("a", 0.7, 1.45), SlipLeg("a", 0.2, 1.45)], RULES) is None
    assert build_slip([SlipLeg("a", 0.9, 1.1)], RULES) is None
    assert build_slip([], RULES) is None
    assert build_slip([SlipLeg(str(i), 0.9, 1.1) for i in range(5)], SlipRules(max_legs=4)) is None  # 1.1^4 < 2


def test_slip_settlement_treats_a_void_leg_as_odds_of_one():
    assert two_odds.slip_status([]) == "none"
    assert two_odds.slip_status(["win", None]) == "pending"
    assert two_odds.slip_status(["loss", None]) == "lost"
    assert two_odds.slip_status(["win", "void"]) == "won"
    assert two_odds.slip_status(["void", "void"]) == "void"
    assert two_odds.settled_odds([(1.5, "win"), (1.4, "void")]) == pytest.approx(1.5)
    assert two_odds.settled_odds([(1.5, "win"), (1.4, "win")]) == pytest.approx(2.1)


def test_table_positions_read_as_ordinals():
    assert [two_odds._ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd"]


def test_backtest_summary_reports_hit_rate_and_losing_run():
    rows = []
    for day, hit in enumerate((True, False, False, True)):
        legs = [SlipLeg(f"{day}{m}", 0.7, 1.45, {"hit": hit, "average_odds": 1.40}) for m in "ab"]
        rows.append({"date": f"2026-01-0{day + 1}T15:00:00", "slip_legs": legs})
    rows.append({"date": "2026-01-09T15:00:00"})  # a matchday without a slip
    out = slip_summary(rows, RULES)
    assert (out["slips"], out["days_with_matches"], out["won"], out["longest_losing_run"]) == (4, 5, 2, 2)
    assert out["hit_rate"] == 0.5 and out["expected_hit_rate"] == pytest.approx(0.49)
    assert out["roi"] == pytest.approx((1.45 ** 2 - 1 - 1) / 2)
    assert out["roi_at_average_odds"] == pytest.approx((1.40 ** 2 - 1 - 1) / 2)
    assert slip_summary([{"date": "2026-01-01T15:00:00"}], RULES) == {"slips": 0, "days_with_matches": 1}


# ------------------------------------------------------------------ service
@pytest.fixture()
def league(db):
    # Every upcoming fixture counts as "today": the slip's window is fixed in the tests by `at`
    now = datetime.now(timezone.utc)
    fixtures = synthetic_league(now - timedelta(days=365 * 2 + 20), seasons=3, upcoming_after=now)
    Store(db).ingest_fixtures(make_batch(fixtures))
    PredictionService(db, get_settings()).predict_upcoming("test")
    return now


def force_slip(db, monkeypatch, now, n=2):
    """Pick n priced favourites and force their checks to pass, whatever the synthetic data says."""
    pool = two_odds.candidates(db, now, now, now + timedelta(days=30))
    assert len({c.fixture.id for c in pool}) >= n, "synthetic league has too few favourites"
    seen, wanted = set(), []
    for c in pool:
        if c.fixture.id not in seen:
            seen.add(c.fixture.id)
            wanted.append(c)
    wanted = wanted[:n]
    monkeypatch.setattr(two_odds, "day_bounds", lambda day, tz: (now, now + timedelta(days=30)))
    monkeypatch.setattr(two_odds, "analyse", lambda db, c, ai, at: [Check("x", "X", PASS, "ok")]
                        if c.fixture.id in {w.fixture.id for w in wanted} else [Check("x", "X", FAIL, "no")])
    # A lower bound just under the pair's odds makes the search take both legs, not the likelier one alone
    least = wanted[0].selection.decimal_odds * wanted[1].selection.decimal_odds - 0.001
    monkeypatch.setattr(two_odds, "RULES", SlipRules(min_combined_odds=least, max_combined_odds=100.0, max_legs=n))
    return wanted


def test_analysis_reports_every_check_and_waits_for_the_ai_when_configured(db, league):
    now = league
    pool = two_odds.candidates(db, now, now, now + timedelta(days=30))
    assert pool and all(c.selection.selection in ("home", "away") and c.selection.market == "1x2" for c in pool)
    checks = two_odds.analyse(db, pool[0], False, now)
    assert {c.key for c in checks} >= {"probability", "market", "models", "data", "reliability", "odds", "form", "venue",
                                       "h2h", "table", "rest", "absences", "ai"}
    assert status(checks, "ai") == "unchecked"
    assert status(two_odds.analyse(db, pool[0], True, now), "ai") == FAIL


def test_ai_doubt_drops_a_leg_and_low_confidence_only_notes_it(db, league):
    now = league
    c = two_odds.candidates(db, now, now, now + timedelta(days=30))[0]
    side = c.selection.selection

    def with_view(p, confidence="high"):
        db.add(AiAnalysis(fixture_id=c.fixture.id, prediction_id=c.prediction.id, created_at=now, status="ok",
                          provider="openai", trigger="scheduled", content={
                              "probability_view": {side: p}, "confidence": confidence, "summary": "Read the news."}))
        db.commit()
        return status(two_odds.analyse(db, c, True, now + timedelta(seconds=1)), "ai")

    assert with_view(c.selection.probability - 0.2) == FAIL
    assert with_view(c.selection.probability, "low") == NOTE
    assert with_view(c.selection.probability) == PASS
    assert status(two_odds.analyse(db, c, True, now + timedelta(hours=25)), "ai") == FAIL  # too old


def test_slip_is_published_kept_while_passing_then_frozen_at_kickoff(db, league, monkeypatch):
    now = league
    wanted = force_slip(db, monkeypatch, now)
    assert two_odds.record_two_odds(db, now, "UTC", False)["legs"] == 2
    slip = db.get(DailySlip, two_odds.slip_day(now, "UTC"))
    ids = {row["fixture_id"] for row in slip.legs}
    assert ids == {w.fixture.id for w in wanted}
    assert slip.combined_odds == pytest.approx(wanted[0].selection.decimal_odds * wanted[1].selection.decimal_odds, abs=1e-3)
    assert not slip.changes

    # still passing: same legs, even if a stronger leg appears
    assert two_odds.record_two_odds(db, now + timedelta(minutes=5), "UTC", False)["kept"] is True

    # the first leg kicks off: the slip no longer changes, even though that leg would fail now
    first = db.get(Fixture, wanted[0].fixture.id)
    first.kickoff_utc = now - timedelta(minutes=1)
    db.commit()
    before = slip.updated_at
    assert two_odds.record_two_odds(db, now, "UTC", False)["frozen"] is True
    assert slip.updated_at == before


def test_published_slip_is_withdrawn_when_a_leg_stops_passing(db, league, monkeypatch):
    now = league
    wanted = force_slip(db, monkeypatch, now)
    two_odds.record_two_odds(db, now, "UTC", False)
    db.get(Fixture, wanted[0].fixture.id).status = "postponed"
    db.commit()
    assert two_odds.record_two_odds(db, now + timedelta(minutes=5), "UTC", False)["legs"] == 0
    slip = db.get(DailySlip, two_odds.slip_day(now, "UTC"))
    assert slip.legs == [] and slip.combined_odds is None
    assert "withdrawn" in slip.changes[0]["reason"]


def test_day_with_no_qualifying_slip_is_recorded_with_reasons(db, league, monkeypatch):
    now = league
    monkeypatch.setattr(two_odds, "day_bounds", lambda day, tz: (now, now + timedelta(days=30)))
    monkeypatch.setattr(two_odds, "analyse", lambda db, c, ai, at: [Check("x", "X", FAIL, "failed the test")])
    out = two_odds.record_two_odds(db, now, "UTC", False)
    assert out["legs"] == 0 and out["analysed"] > 0
    slip = db.get(DailySlip, two_odds.slip_day(now, "UTC"))
    assert slip.rejected and slip.rejected[0]["reasons"] == ["failed the test"]


def test_api_serves_the_slip_and_its_settled_record(db, league, monkeypatch):
    now = league
    wanted = force_slip(db, monkeypatch, now)
    two_odds.record_two_odds(db, now, "UTC", False)
    with TestClient(create_app()) as client:
        r = client.get("/api/v1/predictions/two-odds")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["built"] and body["status"] == "pending" and not body["locked"] and len(body["legs"]) == 2
        assert body["legs"][0]["checks"][0]["status"] == "pass"
        none_yet = client.get("/api/v1/predictions/two-odds", params={"date": "2020-01-01"}).json()
        assert none_yet["built"] is False and none_yet["status"] == "none"
        assert client.get("/api/v1/predictions/two-odds", params={"date": "nope"}).status_code == 422

        # both legs are played and the backed sides win
        for w in wanted:
            f = db.get(Fixture, w.fixture.id)
            f.kickoff_utc, f.status = now - timedelta(hours=3), "finished"
            won = (2, 0) if w.selection.selection == "home" else (0, 2)
            db.add(MatchResult(fixture_id=f.id, home_goals=won[0], away_goals=won[1]))
        db.commit()
        settle_finished(db)
        body = client.get("/api/v1/predictions/two-odds", params={"date": str(two_odds.slip_day(now, "UTC"))}).json()
        assert body["status"] == "won" and body["locked"]
        assert body["paid_odds"] == pytest.approx(body["combined_odds"], abs=1e-3)

        rec = client.get("/api/v1/predictions/two-odds/record").json()
        assert rec["summary"]["won"] == 1 and rec["summary"]["settled"] == 1
        assert rec["summary"]["profit"] == pytest.approx(body["combined_odds"] - 1, abs=1e-3)
        assert rec["history"][0]["status"] == "won"


def test_one_lost_leg_loses_the_slip_with_the_other_leg_pending(db, league, monkeypatch):
    now = league
    wanted = force_slip(db, monkeypatch, now)
    two_odds.record_two_odds(db, now, "UTC", False)
    f = db.get(Fixture, wanted[0].fixture.id)
    f.kickoff_utc, f.status = now - timedelta(hours=3), "finished"
    lost = (0, 2) if wanted[0].selection.selection == "home" else (2, 0)
    db.add(MatchResult(fixture_id=f.id, home_goals=lost[0], away_goals=lost[1]))
    db.commit()
    settle_finished(db)
    rec = two_odds.track_record(db)
    assert rec["summary"]["lost"] == 1 and rec["summary"]["profit"] == -1.0 and rec["summary"]["roi"] == -1.0
    assert rec["summary"]["pending"] == 0
