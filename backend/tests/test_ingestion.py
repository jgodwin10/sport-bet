"""Ingestion: idempotency, identity resolution, conflicts and leakage guards.
All data is SYNTHETIC."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from sqlalchemy import event, func, select

from app.db.models import DataConflict, Fixture, MatchResult, OddsSnapshot, SourceRecord, Team
from app.ingestion.store import Store
from app.ingestion.teams import TeamResolver, normalize
from app.providers.base import NormalizedFixture, NormalizedOdds
from tests.conftest import make_batch, synthetic_league

KICKOFF = datetime(2026, 11, 7, 15, 0, tzinfo=timezone.utc)


def _fx(provider="football_data_co_uk", kickoff=KICKOFF, status="scheduled", home="Alpha", away="Beta", **kw):
    return NormalizedFixture(provider=provider, provider_fixture_id=kw.pop("pid", None), competition_code="ENG-1",
                             season_label="2026-2027", home_name=home, away_name=away, kickoff_utc=kickoff,
                             status=status, **kw)


def test_normalize_handles_common_variants():
    assert normalize("Manchester United FC") == normalize("Man United")
    assert normalize("Bayer 04 Leverkusen") == "bayer leverkusen"
    assert normalize("Atlético Madrid") == "atletico madrid"


def test_identical_payload_is_ingested_once(db):
    fixtures = synthetic_league(datetime(2024, 8, 10, tzinfo=timezone.utc), seasons=1)
    s1 = Store(db).ingest_fixtures(make_batch(fixtures))
    db.commit()
    s2 = Store(db).ingest_fixtures(make_batch(fixtures))
    assert s1.fixtures_created == 90 and s1.results == 90
    assert s2.skipped_duplicate_payload
    assert db.scalar(select(func.count(Fixture.id))) == 90


def test_reingesting_a_changed_season_file_takes_few_queries(db):
    # The production database is remote: per-fixture queries made each daily season file take minutes.
    fixtures = synthetic_league(datetime(2024, 8, 10, tzinfo=timezone.utc), seasons=1)
    Store(db).ingest_fixtures(make_batch(fixtures))
    db.commit()
    statements = []
    listener = lambda *args: statements.append(args[2])  # noqa: E731
    event.listen(db.get_bind(), "before_cursor_execute", listener)
    try:
        stats = Store(db).ingest_fixtures(replace(make_batch(fixtures), payload_hash="changed"))
        db.commit()
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    assert stats.fixtures_created == 0 and not stats.skipped_duplicate_payload
    assert db.scalar(select(func.count(Fixture.id))) == 90
    assert db.scalar(select(func.count(MatchResult.fixture_id))) == 90
    assert len(statements) < 40


def test_unknown_provider_team_name_is_flagged_not_guessed(db):
    Store(db).ingest_fixtures(make_batch([_fx(home="Alpha Rovers", away="Beta Athletic")]))
    resolver = TeamResolver(db)
    assert resolver.resolve("the_odds_api", "Alpha Rovers FC", "ENG-1") is not None  # safe normalised match
    assert resolver.resolve("the_odds_api", "Completely Different", "ENG-1") is None
    conflict = db.scalar(select(DataConflict).where(DataConflict.entity_type == "team_mapping"))
    assert conflict is not None and conflict.values[0]["value"] == "Completely Different"


def test_curated_alias_maps_to_canonical_team(db):
    Store(db).ingest_fixtures(make_batch([_fx(home="Man United", away="Wolves")]))
    resolver = TeamResolver(db)
    man_utd = db.scalar(select(Team.id).where(Team.name == "Man United"))
    assert resolver.resolve("football_data_org", "Manchester United FC", "ENG-1") == man_utd
    assert resolver.resolve("the_odds_api", "Wolverhampton Wanderers", "ENG-1") == db.scalar(
        select(Team.id).where(Team.name == "Wolves"))


def test_higher_trust_kickoff_wins_and_conflict_is_recorded(db):
    Store(db).ingest_fixtures(make_batch([_fx()], trust=70))
    later = KICKOFF + timedelta(hours=2)
    Store(db).ingest_fixtures(make_batch([_fx(provider="football_data_org", kickoff=later, pid="99")],
                                         provider="football_data_org", trust=85, resource="/m"))
    f = db.scalar(select(Fixture))
    assert f.kickoff_utc == later
    conflict = db.scalar(select(DataConflict).where(DataConflict.field == "kickoff_utc"))
    assert conflict.material and conflict.resolved
    assert len(conflict.values) == 2  # both original values preserved


def test_lower_trust_source_does_not_override_or_unpostpone(db):
    Store(db).ingest_fixtures(make_batch([_fx(provider="football_data_org", status="postponed", pid="1")],
                                         provider="football_data_org", trust=85, resource="/m"))
    Store(db).ingest_fixtures(make_batch([_fx(kickoff=KICKOFF + timedelta(hours=1))], trust=70))
    f = db.scalar(select(Fixture))
    assert f.status == "postponed"
    assert f.kickoff_utc == KICKOFF


def test_approximate_kickoff_never_overrides(db):
    Store(db).ingest_fixtures(make_batch([_fx()], trust=70))
    Store(db).ingest_fixtures(make_batch([_fx(kickoff=KICKOFF + timedelta(hours=3), kickoff_approximate=True)],
                                         trust=70, resource="/other"))
    assert db.scalar(select(Fixture)).kickoff_utc == KICKOFF


def test_conflicting_results_are_flagged(db):
    Store(db).ingest_fixtures(make_batch([_fx(status="finished", home_goals=2, away_goals=1)]))
    Store(db).ingest_fixtures(make_batch([_fx(status="finished", home_goals=1, away_goals=1)], resource="/b"))
    assert db.scalar(select(MatchResult)).home_goals == 2  # original kept
    c = db.scalar(select(DataConflict).where(DataConflict.entity_type == "match_result"))
    assert c is not None and not c.resolved and c.material


def test_pre_match_odds_observed_after_kickoff_are_dropped(db):
    odds = [NormalizedOdds("b365", "Bet365", "1x2", "home", 2.0, "pre_match", KICKOFF - timedelta(hours=1)),
            NormalizedOdds("b365", "Bet365", "1x2", "away", 3.0, "pre_match", KICKOFF + timedelta(minutes=5))]
    Store(db).ingest_fixtures(make_batch([_fx(odds=odds)]))
    rows = db.scalars(select(OddsSnapshot)).all()
    assert [r.selection for r in rows] == ["home"]
    assert rows[0].source_record_id == db.scalar(select(SourceRecord.id))


def test_odds_only_provider_does_not_create_fixtures(db):
    stats = Store(db).ingest_fixtures(make_batch([_fx(provider="the_odds_api", pid="e1")],
                                                 provider="the_odds_api", trust=80, resource="/odds"))
    assert stats.fixtures_created == 0 and stats.unmatched


def test_cup_events_create_fixtures_for_league_teams_and_dedupe_by_window(db):
    Store(db).ingest_fixtures(make_batch(synthetic_league(datetime(2025, 8, 10, tzinfo=timezone.utc), seasons=1)))
    db.commit()
    teams_before = db.scalar(select(func.count(Team.id)))
    cup = dict(provider="the_odds_api", home="Synthetic Town 01 FC", away="Synthetic Town 02",
               competition_code="ENG-LC", stage="cup")
    first = Store(db).ingest_fixtures(make_batch([_cup_fx(pid="e1", **cup)], provider="the_odds_api", trust=80))
    db.commit()
    # Another source reports the same tie a day later: same fixture, not a second one
    moved = Store(db).ingest_fixtures(make_batch([_cup_fx(kickoff=KICKOFF + timedelta(days=1), **{
        **cup, "provider": "api_football"})], provider="api_football", trust=75))
    assert first.fixtures_created == 1 and moved.fixtures_created == 0
    assert db.scalar(select(func.count(Team.id))) == teams_before
    assert db.scalar(select(Fixture.stage).where(Fixture.natural_key.like("ENG-LC:%"))) == "cup"


def test_league_odds_from_odds_api_still_never_create_fixtures(db):
    stats = Store(db).ingest_fixtures(make_batch([_cup_fx(provider="the_odds_api", competition_code="ENG-1")],
                                                 provider="the_odds_api", trust=80))
    assert stats.fixtures_created == 0


def _cup_fx(provider, competition_code, kickoff=KICKOFF, home="Alpha", away="Beta", **kw):
    return NormalizedFixture(provider=provider, provider_fixture_id=kw.pop("pid", None),
                             competition_code=competition_code, season_label="2026-2027", home_name=home,
                             away_name=away, kickoff_utc=kickoff, status="scheduled", **kw)
