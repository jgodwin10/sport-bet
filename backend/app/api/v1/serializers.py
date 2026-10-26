from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Fixture, Prediction
from app.schemas.api import CompetitionOut, FixtureOut, PredictionBrief, TeamRef
from app.services.crests import crest_url


def team_ref(t) -> TeamRef:
    return TeamRef(id=t.id, name=t.name, logo_url=crest_url(t))


def latest_predictions(db: Session, fixture_ids: list[int]) -> dict[int, Prediction]:
    if not fixture_ids:
        return {}
    rows = db.scalars(select(Prediction).where(Prediction.fixture_id.in_(fixture_ids))
                      .order_by(Prediction.fixture_id, Prediction.created_at, Prediction.id))
    out: dict[int, Prediction] = {}
    for p in rows:
        out[p.fixture_id] = p  # ordered ascending: last one wins
    return out


def prediction_brief(p: Prediction | None) -> PredictionBrief | None:
    if p is None:
        return None
    qualifying = [s for s in p.selections if s.qualifies]
    best = max(qualifying, key=lambda s: s.expected_value, default=None)
    return PredictionBrief(
        id=p.id, created_at=p.created_at, classification=p.classification,
        one_x_two=p.markets.get("1x2", {}), reliability_score=p.reliability["score"],
        reliability_label=p.reliability["label"], lineup_status=p.lineup_status,
        best_selection={"market": best.market, "selection": best.selection, "odds": best.decimal_odds,
                        "probability": best.probability, "expected_value": best.expected_value,
                        "edge": best.edge, "bookmaker": best.bookmaker} if best else None,
        odds_age_hours=p.data_quality.get("odds_age_hours"),
    )


def fixture_out(f: Fixture, p: Prediction | None) -> FixtureOut:
    return FixtureOut(
        id=f.id, competition=CompetitionOut.model_validate(f.competition), season=f.season.label,
        home_team=team_ref(f.home_team), away_team=team_ref(f.away_team), kickoff_utc=f.kickoff_utc,
        status=f.status, neutral=f.neutral, venue=f.venue,
        score={"home": f.result.home_goals, "away": f.result.away_goals,
               "ht_home": f.result.ht_home_goals, "ht_away": f.result.ht_away_goals} if f.result else None,
        latest_prediction=prediction_brief(p),
    )


def prediction_detail(p: Prediction) -> dict:
    return {
        "id": p.id, "created_at": p.created_at, "information_cutoff": p.information_cutoff,
        "trigger": p.trigger, "lineup_status": p.lineup_status, "markets": p.markets,
        "components": p.components, "intervals": p.intervals, "reliability": p.reliability,
        "classification": p.classification, "data_quality": p.data_quality,
        "model_version_id": p.model_version_id, "supersedes_id": p.supersedes_id,
        "change_summary": p.change_summary,
        "explanations": [{"category": e.category, "text": e.text, "evidence": e.evidence} for e in p.explanations],
        "selections": [{
            "id": s.id, "market": s.market, "selection": s.selection, "line": s.line,
            "probability": s.probability, "probability_lower": s.probability_lower, "odds": s.decimal_odds,
            "bookmaker": s.bookmaker, "implied_probability": s.implied_probability,
            "fair_probability": s.fair_probability, "edge": s.edge, "expected_value": s.expected_value,
            "qualifies": s.qualifies, "rejection_reasons": s.rejection_reasons,
        } for s in sorted(p.selections, key=lambda s: (-s.qualifies, -s.expected_value))],
    }
