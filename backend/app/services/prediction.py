"""Live prediction workflow: fit per competition at "now", score upcoming
fixtures, evaluate priced selections and persist immutable snapshots."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    AvailabilityReport, Competition, DataConflict, Fixture, Lineup, ModelFeatureSnapshot, ModelVersion,
    Prediction, PredictionExplanation, Selection, Team,
)
from app.engine.decision import (
    Candidate, ReliabilityInputs, assess_reliability, classify, evaluate_candidate,
)
from app.engine.features import MODEL_FEATURES
from app.engine.odds import asian_handicap_ev, implied_probability
from app.engine.pipeline import (
    ModelSuite, SuiteConfig, combine_1x2, market_1x2, market_binary, rake_matrix, stat_disagreement,
)
from app.ingestion.competitions import COMPETITIONS, pool_codes
from app.services.analytics import OddsView, head_to_head, load_records, odds_at, standings
from app.services.explain import build_explanations
from app.services.settings_store import get_rules, get_app_options

log = logging.getLogger(__name__)

EXCLUDED_PRICE_BOOKS = {"avg", "max", "bfe"}  # pseudo-books / exchange (commission not modelled)
HORIZON_DAYS = 14
# Bump when prediction logic changes so new snapshots are produced (part of the inputs hash).
PREDICTION_LOGIC_VERSION = "2"


def deployed_version(db: Session) -> ModelVersion | None:
    return db.scalar(select(ModelVersion).where(ModelVersion.status == "deployed")
                     .order_by(ModelVersion.created_at.desc()).limit(1))


def version_competitions(version: ModelVersion) -> set[str]:
    return set((version.config or {}).get("backtest_params", {}).get("competitions", []))


def suite_config(settings: Settings) -> SuiteConfig:
    return SuiteConfig(dc_half_life_days=settings.dc_half_life_days, dc_ridge=settings.dc_ridge,
                       max_goals=settings.max_goals)


def best_price(books: dict[str, dict[str, float]], selection: str) -> tuple[float, str] | None:
    best = None
    for bk, prices in books.items():
        if bk in EXCLUDED_PRICE_BOOKS or selection not in prices:
            continue
        if best is None or prices[selection] > best[0]:
            best = (prices[selection], bk)
    if best is None and "avg" in books and selection in books["avg"]:
        best = (books["avg"][selection], "avg")
    return best


def consensus(books: dict[str, dict[str, float]]) -> dict[str, float] | None:
    for key in ("avg", "ps", "pinnacle"):
        if key in books:
            return books[key]
    if not books:
        return None
    # Average of individual bookmakers' complete price sets
    complete = [p for p in books.values() if len(p) >= 2]
    if not complete:
        return None
    sels = set.intersection(*(set(p) for p in complete))
    return {s: float(np.mean([p[s] for p in complete])) for s in sels}


class PredictionService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def predict_upcoming(self, trigger: str = "scheduled", now: datetime | None = None,
                         fixture_ids: list[int] | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        q = select(Fixture).where(Fixture.status == "scheduled", Fixture.kickoff_utc > now,
                                  Fixture.kickoff_utc < now + timedelta(days=HORIZON_DAYS))
        if fixture_ids:
            q = q.where(Fixture.id.in_(fixture_ids))
        fixtures = list(self.db.scalars(q))
        by_comp: dict[int, list[Fixture]] = {}
        for f in fixtures:
            by_comp.setdefault(f.competition_id, []).append(f)
        summary: dict = {"created": 0, "unchanged": 0, "failed": 0, "skipped": {}}
        deployed = deployed_version(self.db)
        suites: dict[tuple[int, ...], tuple[ModelSuite, list]] = {}
        for comp_id, comp_fixtures in by_comp.items():
            # A model version's weights/validation only apply to competitions it was backtested on
            comp_code = comp_fixtures[0].competition.code
            version = deployed if deployed and comp_code in version_competitions(deployed) else None
            # Cups train on their feeder leagues; competitions sharing a pool share one fit
            pool = tuple(sorted(self.db.scalars(select(Competition.id).where(
                Competition.code.in_(pool_codes(comp_code)))))) if comp_code in COMPETITIONS else (comp_id,)
            if pool not in suites:
                records = load_records(self.db, list(pool), before=now)
                suite = ModelSuite(suite_config(self.settings), pool=",".join(map(str, pool)))
                for r in records:
                    suite.absorb(r)
                suite.refit(now)
                suites[pool] = (suite, records)
            suite, records = suites[pool]
            if suite.dc is None and suite.elo_map is None and suite.feature_model is None:
                # Without any statistical component the "prediction" would just echo the market.
                summary["skipped"][comp_code] = (f"{len(comp_fixtures)} fixture(s): insufficient match history "
                                                 f"({len(records)} matches); ingest history first")
                continue
            for f in comp_fixtures:
                try:
                    created = self.predict_fixture(f, suite, version, trigger, now, len(records))
                    summary["created" if created else "unchanged"] += 1
                except Exception:  # noqa: BLE001 - one bad fixture must not stop the batch
                    log.exception("prediction failed for fixture %s", f.id)
                    self.db.rollback()
                    summary["failed"] += 1
        return summary

    # ------------------------------------------------------------------ core
    def predict_fixture(self, fixture: Fixture, suite: ModelSuite, version: ModelVersion | None, trigger: str,
                        now: datetime, n_history: int) -> bool:
        db = self.db
        home_name, away_name = fixture.home_team.name, fixture.away_team.name
        out = suite.components(str(fixture.home_team_id), str(fixture.away_team_id), fixture.kickoff_utc,
                               fixture.neutral, with_intervals=True)
        odds = odds_at(db, fixture.id, now)
        books_1x2 = odds.books("1x2")
        mkt = market_1x2(consensus(books_1x2))
        probs = dict(out.one_x_two)
        if not probs:
            raise RuntimeError("no statistical model component could score this fixture")
        if mkt is not None:
            probs["market"] = mkt
        weights = version.ensemble_weights if version else None
        final_arr, used_weights = combine_1x2(probs, weights)
        final = {"home": float(final_arr[0]), "draw": float(final_arr[1]), "away": float(final_arr[2])}

        markets: dict = {}
        over_final = None
        totals_books = odds.books("totals", 2.5)
        mkt_over = None
        if (c := consensus(totals_books)) is not None:
            mkt_over = market_binary(c.get("over"), c.get("under"))
        if out.matrix is not None:
            dc_over = out.matrix.totals(2.5)["over"]
            w_over = float((weights or {}).get("_totals_market", 0.0))
            over_final = dc_over if mkt_over is None else (1 - w_over) * dc_over + w_over * mkt_over
            raked = rake_matrix(out.matrix, final_arr, over_final)
            markets = raked.all_markets()
            markets["score_grid"] = raked.grid(6)
            markets["expected_goals"] = {"home": out.matrix.home_rate, "away": out.matrix.away_rate}
        markets["1x2"] = final
        markets["double_chance"] = {"1X": final["home"] + final["draw"], "X2": final["draw"] + final["away"],
                                    "12": final["home"] + final["away"]}
        decisive = final["home"] + final["away"]
        markets["draw_no_bet"] = {"home": final["home"] / decisive, "away": final["away"] / decisive,
                                  "push": final["draw"]}
        markets["supported"] = {
            "half_time": False, "corners": False, "cards": False,
            "reason": "no validated model for half-time, corners or cards markets",
        }

        intervals = None
        if out.intervals and "dixon_coles" in probs:
            # Propagate Dixon-Coles parameter uncertainty through the linear pool: the
            # final estimate moves by (statistical weight share) x (DC deviation). The
            # market component carries no parameter uncertainty. Treating Elo and the
            # feature model as equally uncertain and fully correlated with DC makes this
            # an upper bound on model-parameter uncertainty (it ignores model misspecification).
            stat_share = sum(w for c, w in used_weights.items() if c != "market")
            w_over = float((weights or {}).get("_totals_market", 0.0)) if mkt_over is not None else 0.0
            intervals = {}
            for i, k in enumerate(("home", "draw", "away")):
                lo, hi = out.intervals[k]
                point = float(probs["dixon_coles"][i])
                intervals[k] = [max(0.0, final[k] + stat_share * (lo - point)),
                                min(1.0, final[k] + stat_share * (hi - point))]
            if over_final is not None and "over_2.5" in out.intervals:
                lo, hi = out.intervals["over_2.5"]
                point = out.matrix.totals(2.5)["over"]
                intervals["over_2.5"] = [max(0.0, over_final + (1 - w_over) * (lo - point)),
                                         min(1.0, over_final + (1 - w_over) * (hi - point))]
            intervals["method"] = ("Dixon-Coles parameter uncertainty (Laplace approx.) propagated through the "
                                   f"ensemble with statistical-model weight {stat_share:.2f}")

        lineup_status = self._lineup_status(fixture)
        availability = self._availability(fixture, now)
        conflicts = self._conflicts(fixture)
        stale = self._stale_inputs(fixture, now)
        odds_age = ((now - odds.latest_observed).total_seconds() / 3600) if odds.latest_observed else None
        validated = set(version.validated_markets) if version else set()
        disagreement = stat_disagreement(probs)
        width = (intervals["home"][1] - intervals["home"][0]) if intervals else None
        reliability = assess_reliability(ReliabilityInputs(
            min_team_matches=min(out.sample_sizes.values()) if out.sample_sizes else 0,
            model_disagreement=disagreement, interval_width=width, odds_age_hours=odds_age,
            lineup_status=lineup_status, unresolved_conflicts=len([c for c in conflicts if c["material"]]),
            stale_inputs=stale, market_validated="1x2" in validated, ensemble_validated=version is not None,
            missing_optional=out.missing_components,
        ))

        rules = get_rules(self.db)
        options = get_app_options(self.db)
        selections = self._candidates(odds, final, over_final, intervals, markets, validated)
        enabled = set(options.get("enabled_markets", ["1x2", "totals_2.5", "asian_handicap"]))
        for s in selections:
            reasons = evaluate_candidate(s["candidate"], rules, reliability, odds_age, disagreement)
            if s["market_group"] not in enabled:
                reasons.append("market disabled in settings")
            s["reasons"] = reasons
        # at most one qualifying selection per market group (highest EV)
        best_per_group: dict[str, dict] = {}
        for s in selections:
            if not s["reasons"]:
                g = s["market_group"]
                if g not in best_per_group or s["candidate"].ev > best_per_group[g]["candidate"].ev:
                    best_per_group[g] = s
        for s in selections:
            if not s["reasons"] and best_per_group.get(s["market_group"]) is not s:
                s["reasons"] = ["another selection in this market has higher EV"]
        qualifying = [s["candidate"] for s in selections if not s["reasons"]]
        classification = classify(qualifying, reliability)

        context = self._context(fixture, now)
        h2h = head_to_head(db, fixture.home_team_id, fixture.away_team_id, now)
        sel_dicts = [self._sel_dict(s) for s in selections]
        explanations = build_explanations(
            home=home_name, away=away_name, final=final,
            components={k: [float(x) for x in v] for k, v in probs.items()}, weights=used_weights,
            dc_params=out.dc_team_params, expected_goals=markets.get("expected_goals"), elo=out.elo,
            raw_features=out.raw_features, market=dict(zip(("home", "draw", "away"), map(float, mkt), strict=True))
            if mkt is not None else None,
            h2h=h2h, context=context, missing=out.missing_components, reliability=reliability.to_dict(),
            lineup_status=lineup_status, availability=availability, selections=sel_dicts,
            classification=classification,
        )

        odds_used = sorted((r["bookmaker"], r["market"], r["line"], r["selection"], r["odds"],
                            r["observed_at"].isoformat()) for r in odds.rows)
        inputs = {
            "features": out.feature_vector, "raw": out.raw_features, "elo": out.elo, "odds": odds_used,
            "version": version.id if version else None, "lineup": lineup_status,
            "availability": [(a["player_name"], a["kind"], a["verification"]) for a in availability],
            "conflicts": [c["id"] for c in conflicts], "history": n_history,
            "rules": rules.__dict__, "enabled": sorted(enabled), "logic": PREDICTION_LOGIC_VERSION,
        }
        inputs_hash = hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()
        previous = db.scalar(select(Prediction).where(Prediction.fixture_id == fixture.id)
                             .order_by(Prediction.created_at.desc(), Prediction.id.desc()).limit(1))
        if previous is not None and previous.inputs_hash == inputs_hash:
            return False

        snapshot = ModelFeatureSnapshot(fixture_id=fixture.id, as_of=now, features={
            "model_features": dict(zip(MODEL_FEATURES, out.feature_vector, strict=True)),
            "raw": out.raw_features, "elo": out.elo, "dc_team_params": out.dc_team_params,
            "sample_sizes": out.sample_sizes,
        })
        db.add(snapshot)
        db.flush()

        data_quality = {
            "odds_latest_observed": odds.latest_observed.isoformat() if odds.latest_observed else None,
            "odds_age_hours": odds_age, "odds_bookmakers": sorted(odds.bookmaker_names().values()),
            "odds_sources": sorted({r["source_record_id"] for r in odds.rows}),
            "lineup_status": lineup_status, "availability_reports": len(availability),
            "conflicts": conflicts, "stale_inputs": stale, "missing_components": out.missing_components,
            "training_matches": n_history, "sample_sizes": out.sample_sizes,
            "model_version": f"{version.name}:{version.version}" if version else None,
            "prediction_logic_version": PREDICTION_LOGIC_VERSION,
        }
        prediction = Prediction(
            fixture_id=fixture.id, model_version_id=version.id if version else None,
            feature_snapshot_id=snapshot.id, supersedes_id=previous.id if previous else None,
            created_at=datetime.now(timezone.utc), information_cutoff=now, trigger=trigger,
            lineup_status=lineup_status, markets=_jsonable(markets),
            components={"one_x_two": {k: [float(x) for x in v] for k, v in probs.items()},
                        "weights": used_weights, "disagreement": disagreement,
                        "weights_source": "walk-forward backtest" if version else "unvalidated equal weights"},
            intervals=intervals, reliability=reliability.to_dict(), classification=classification,
            data_quality=data_quality, inputs_hash=inputs_hash,
            change_summary=self._changes(previous, final, lineup_status, odds_age, classification, trigger)
            if previous else None,
        )
        db.add(prediction)
        db.flush()
        for i, e in enumerate(explanations):
            db.add(PredictionExplanation(prediction_id=prediction.id, position=i, category=e.category, text=e.text,
                                         evidence=_jsonable(e.evidence)))
        for s in sel_dicts:
            db.add(Selection(
                prediction_id=prediction.id, fixture_id=fixture.id, market=s["market"], selection=s["selection"],
                line=s["line"], probability=s["probability"], probability_lower=s["probability_lower"],
                decimal_odds=s["odds"], bookmaker=s["bookmaker"], implied_probability=s["implied"],
                fair_probability=s["fair"], edge=s["edge"], expected_value=s["ev"], qualifies=s["qualifies"],
                rejection_reasons=s["reasons"],
            ))
        db.commit()
        return True

    # --------------------------------------------------------------- helpers
    def _candidates(self, odds: OddsView, final: dict, over_final: float | None, intervals: dict | None,
                    markets: dict, validated: set[str]) -> list[dict]:
        out = []
        books = odds.books("1x2")
        fair = market_1x2(consensus(books))
        for i, sel in enumerate(("home", "draw", "away")):
            price = best_price(books, sel)
            if price:
                lower = intervals[sel][0] if intervals and sel in intervals else None
                out.append({"market_group": "1x2", "line": 0.0, "fair": float(fair[i]) if fair is not None else None,
                            "candidate": Candidate("1x2", sel, final[sel], price[0], price[1], lower,
                                                   validated="1x2" in validated)})
        for line in odds.lines("totals"):
            if line % 1 != 0.5 or "totals" not in markets or str(line) not in markets["totals"]:
                continue
            tb = odds.books("totals", line)
            c = consensus(tb)
            fair_over = market_binary(c.get("over"), c.get("under")) if c else None
            for sel in ("over", "under"):
                price = best_price(tb, sel)
                if not price:
                    continue
                p = markets["totals"][str(line)][sel]
                if line == 2.5 and over_final is not None:
                    p = over_final if sel == "over" else 1 - over_final
                lower = None
                if line == 2.5 and intervals and "over_2.5" in intervals:
                    lo, hi = intervals["over_2.5"]
                    lower = lo if sel == "over" else 1 - hi
                fair_sel = None if fair_over is None else (fair_over if sel == "over" else 1 - fair_over)
                out.append({"market_group": f"totals_{line}", "line": line, "fair": fair_sel,
                            "candidate": Candidate(f"totals_{line}", sel, p, price[0], price[1], lower,
                                                   validated=f"totals_{line}" in validated)})
        for line in odds.lines("asian_handicap"):
            key = f"{line:+.2f}"
            ah = markets.get("asian_handicap", {}).get(key)
            if ah is None:
                continue
            tb = odds.books("asian_handicap", line)
            for side in ("home", "away"):
                price = best_price(tb, side)
                if not price:
                    continue
                o = ah[side]
                ev = asian_handicap_ev(o["win"], o["half_win"], o["push"], o["half_loss"], o["loss"], price[0])
                # equivalent single-outcome probability giving the same EV at these odds
                p_eq = (ev + 1) / price[0]
                out.append({"market_group": "asian_handicap", "line": line, "fair": None,
                            "candidate": Candidate("asian_handicap", f"{side} {key if side == 'home' else f'{(-line or 0.0):+.2f}'}",
                                                   p_eq, price[0], price[1], None,
                                                   validated="asian_handicap" in validated)})
        return out

    @staticmethod
    def _sel_dict(s: dict) -> dict:
        c: Candidate = s["candidate"]
        return {"market": c.market, "selection": c.selection, "line": s["line"], "probability": c.probability,
                "probability_lower": c.probability_lower, "odds": c.odds, "bookmaker": c.bookmaker,
                "implied": implied_probability(c.odds), "fair": s["fair"], "edge": c.edge, "ev": c.ev,
                "qualifies": not s["reasons"], "reasons": s["reasons"], "validated": c.validated}

    def _lineup_status(self, fixture: Fixture) -> str:
        rows = self.db.execute(select(Lineup.team_id, Lineup.status).where(Lineup.fixture_id == fixture.id)).all()
        confirmed = {t for t, s in rows if s == "confirmed"}
        if {fixture.home_team_id, fixture.away_team_id} <= confirmed:
            return "confirmed"
        return "projected" if rows else "unavailable"

    def _availability(self, fixture: Fixture, now: datetime) -> list[dict]:
        q = (select(AvailabilityReport, Team.name).join(Team, Team.id == AvailabilityReport.team_id)
             .where(AvailabilityReport.fixture_id == fixture.id, AvailabilityReport.retrieved_at <= now)
             .order_by(AvailabilityReport.retrieved_at.desc()))
        seen, out = set(), []
        for a, team in self.db.execute(q):
            if (a.team_id, a.player_name) in seen:
                continue
            seen.add((a.team_id, a.player_name))
            out.append({"player_name": a.player_name, "team": team, "kind": a.kind, "reason": a.reason,
                        "verification": a.verification, "retrieved_at": a.retrieved_at.isoformat()})
        return out

    def _conflicts(self, fixture: Fixture) -> list[dict]:
        rows = self.db.scalars(select(DataConflict).where(
            DataConflict.entity_id == fixture.id, DataConflict.entity_type.in_(("fixture", "match_result")),
            DataConflict.resolved.is_(False)))
        return [{"id": c.id, "field": c.field, "material": c.material, "resolution": c.resolution} for c in rows]

    def _stale_inputs(self, fixture: Fixture, now: datetime) -> list[str]:
        missing_results = self.db.scalar(select(func.count(Fixture.id)).where(
            Fixture.competition_id == fixture.competition_id, Fixture.status == "scheduled",
            Fixture.kickoff_utc < now - timedelta(hours=6), Fixture.kickoff_utc > now - timedelta(days=21)))
        return [f"{missing_results} recent match(es) in this competition have no stored result"] if missing_results else []

    def _context(self, fixture: Fixture, now: datetime) -> dict:
        if fixture.competition.format == "cup":
            return {}  # a cup has no league table
        table = standings(self.db, fixture.season_id, now)
        pos = {r["team_id"]: r for r in table}
        h, a = pos.get(fixture.home_team_id), pos.get(fixture.away_team_id)
        if not h or not a:
            return {}
        return {"home_position": h["position"], "home_points": h["points"], "away_position": a["position"],
                "away_points": a["points"], "teams_in_table": len(table), "played": h["played"]}

    @staticmethod
    def _changes(previous: Prediction, final: dict, lineup_status: str, odds_age: float | None,
                 classification: str, trigger: str) -> list[dict]:
        old = previous.markets.get("1x2", {})
        changes = [{"field": f"p_{k}", "before": old.get(k), "after": final[k],
                    "delta": final[k] - old.get(k, 0.0)} for k in final if old.get(k) is not None
                   and abs(final[k] - old[k]) >= 0.005]
        if previous.lineup_status != lineup_status:
            changes.append({"field": "lineup_status", "before": previous.lineup_status, "after": lineup_status})
        if previous.classification != classification:
            changes.append({"field": "classification", "before": previous.classification, "after": classification})
        changes.append({"field": "trigger", "after": trigger})
        return changes


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, float) and (obj != obj):  # NaN
        return None
    return obj

