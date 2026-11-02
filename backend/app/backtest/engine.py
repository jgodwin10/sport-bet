"""Walk-forward backtest.

Timeline per step (default 7 days):
  1. Absorb every match that kicked off before the step start (and nothing else).
  2. Refit all models at the step start.
  3. Predict every match in [step start, step end) using only the refitted models,
     the pre-match odds snapshot (never closing odds) and ensemble weights learned
     from out-of-sample predictions of *earlier* steps.
  4. Settle against the result; closing odds are used only for CLV afterwards.

The model's information cutoff is the step start, which is earlier than the
odds snapshot, so the backtest is conservative rather than optimistic.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from app.engine.decision import Candidate, ReliabilityInputs, SelectionRules, assess_reliability, evaluate_candidate
from app.engine.ensemble import LinearPool, LogPool, brier, calibration_bins, calibration_test, log_loss
from app.engine.features import MatchRecord
from app.engine.pipeline import (
    COMPONENTS_1X2, ModelSuite, SuiteConfig, combine_1x2, market_1x2, market_binary, outcome_index, rake_matrix,
    stat_disagreement,
)
from app.engine.slip import SlipLeg, SlipRules, build_slip, combined_probability, core_checks, leg_passes

log = logging.getLogger(__name__)

INDIVIDUAL_BOOKS_EXCLUDED = {"avg", "max", "bfe"}  # pseudo-books and exchange (commission not modelled)
ODDS_BUCKETS = [(1.0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 1000.0)]


@dataclass
class BacktestMatch:
    record: MatchRecord
    competition: str
    pre_1x2: dict[str, dict[str, float]] = field(default_factory=dict)  # bookmaker -> {home, draw, away}
    close_1x2: dict[str, dict[str, float]] = field(default_factory=dict)
    pre_totals: dict[str, dict[str, float]] = field(default_factory=dict)  # bookmaker -> {over, under} @2.5
    close_totals: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class BacktestParams:
    evaluate_from: datetime
    evaluate_to: datetime
    step_days: int = 7
    price_source: str = "best"  # best (best individual bookmaker) | avg (market average)
    rules: SelectionRules = field(default_factory=SelectionRules)
    slip_rules: SlipRules = field(default_factory=SlipRules)
    min_oos_for_weights: int = 300
    suite: SuiteConfig = field(default_factory=lambda: SuiteConfig(compute_intervals=False))


def _price(books: dict[str, dict[str, float]], selection: str, source: str) -> tuple[float, str] | None:
    if source == "avg":
        p = books.get("avg", {}).get(selection)
        return (p, "avg") if p else None
    best = None
    for bk, prices in books.items():
        if bk in INDIVIDUAL_BOOKS_EXCLUDED or selection not in prices:
            continue
        if best is None or prices[selection] > best[0]:
            best = (prices[selection], bk)
    return best


def _consensus(books: dict[str, dict[str, float]]) -> dict[str, float] | None:
    if "avg" in books:
        return books["avg"]
    if "ps" in books:
        return books["ps"]
    return next(iter(books.values()), None)


def max_drawdown(pnl: list[float]) -> float:
    peak, worst, cum = 0.0, 0.0, 0.0
    for x in pnl:
        cum += x
        peak = max(peak, cum)
        worst = max(worst, peak - cum)
    return worst


def bootstrap_roi_interval(profits: list[float], level: float = 0.9, n: int = 2000, seed: int = 0) -> tuple[float, float] | None:
    if len(profits) < 20:
        return None
    rng = np.random.default_rng(seed)
    arr = np.array(profits)
    samples = rng.choice(arr, size=(n, len(arr)), replace=True).mean(axis=1)
    return float(np.percentile(samples, (1 - level) / 2 * 100)), float(np.percentile(samples, (1 + level) / 2 * 100))


def run_backtest(matches_by_comp: dict[str, list[BacktestMatch]], params: BacktestParams) -> dict:
    rows: list[dict] = []
    bets: list[dict] = []
    oos: dict[str, list[np.ndarray]] = defaultdict(list)  # component -> probs (rows with all components)
    oos_outcomes: list[int] = []
    oos_over: list[tuple[float, float, int]] = []  # (dc over, market over, hit)
    weights_history: list[dict] = []

    # Competitions advance through time together: the ensemble weights at a step are learned from
    # every competition's predictions of earlier steps only, never from another competition's future.
    ordered = {comp: sorted(ms, key=lambda m: m.record.kickoff)
               for comp, ms in sorted(matches_by_comp.items()) if ms}
    suites = {comp: ModelSuite(params.suite, pool=comp) for comp in ordered}
    cursors = dict.fromkeys(ordered, 0)
    step = params.evaluate_from
    while step < params.evaluate_to:
        end = min(step + timedelta(days=params.step_days), params.evaluate_to)
        weights = None
        if len(oos_outcomes) >= params.min_oos_for_weights:
            pool = LogPool(COMPONENTS_1X2).fit({c: np.array(oos[c]) for c in COMPONENTS_1X2},
                                               np.array(oos_outcomes))
            weights = pool.to_dict()
            if len(oos_over) >= params.min_oos_for_weights:
                weights["_totals_market"] = _totals_weight(oos_over)
            weights_history.append({"date": step.isoformat(), **weights})
        for comp, matches in ordered.items():
            suite, cursor = suites[comp], cursors[comp]
            while cursor < len(matches) and matches[cursor].record.kickoff < step:
                suite.absorb(matches[cursor].record)
                cursor += 1
            cursors[comp] = cursor
            window = [m for m in matches[cursor:] if step <= m.record.kickoff < end]
            if not window:
                continue
            suite.refit(step)
            for m in window:
                row = _predict_one(suite, m, comp, weights, params, bets)
                if row is None:
                    continue
                rows.append(row)
                if all(c in row["components"] for c in COMPONENTS_1X2):
                    for c in COMPONENTS_1X2:
                        oos[c].append(np.array(row["components"][c]))
                    oos_outcomes.append(row["outcome"])
                if row.get("dc_over") is not None and row.get("market_over") is not None:
                    oos_over.append((row["dc_over"], row["market_over"], row["over_hit"]))
        step = end

    return summarise(rows, bets, oos, oos_outcomes, oos_over, weights_history, params)


def _predict_one(suite: ModelSuite, m: BacktestMatch, comp: str, weights: dict | None, params: BacktestParams,
                 bets: list[dict]) -> dict | None:
    r = m.record
    out = suite.components(r.home, r.away, r.kickoff)
    if not out.one_x_two:
        return None
    probs = dict(out.one_x_two)
    consensus = _consensus(m.pre_1x2)
    mkt = market_1x2(consensus)
    if mkt is not None:
        probs["market"] = mkt
    final, used = combine_1x2(probs, weights)
    outcome = outcome_index(r.home_goals, r.away_goals)
    row: dict = {
        "date": r.kickoff.isoformat(), "competition": comp, "home": r.home, "away": r.away,
        "outcome": outcome, "final": final.tolist(),
        "components": {c: p.tolist() for c, p in probs.items()}, "weights": used,
    }

    over_final = None
    if out.matrix is not None:
        dc_over = out.matrix.totals(2.5)["over"]
        pre_tot = _consensus(m.pre_totals)
        mkt_over = market_binary(pre_tot.get("over"), pre_tot.get("under")) if pre_tot else None
        row.update(dc_over=dc_over, market_over=mkt_over, over_hit=int(r.home_goals + r.away_goals > 2.5))
        w_over = weights.get("_totals_market", 0.0) if weights else 0.0
        over_final = dc_over if mkt_over is None else (1 - w_over) * dc_over + w_over * mkt_over
        row["final_over"] = over_final

    rel = assess_reliability(ReliabilityInputs(
        min_team_matches=min(out.sample_sizes.values()), model_disagreement=stat_disagreement(probs),
        interval_width=None, odds_age_hours=0.0 if m.pre_1x2 else None, lineup_status="unavailable",
        unresolved_conflicts=0, stale_inputs=[], market_validated=True, ensemble_validated=weights is not None,
    ))
    row["reliability"] = rel.score
    disagreement = stat_disagreement(probs)

    candidates = []
    for idx, sel in enumerate(("home", "draw", "away")):
        price = _price(m.pre_1x2, sel, params.price_source)
        if price:
            candidates.append((Candidate("1x2", sel, float(final[idx]), price[0], price[1], validated=True),
                               idx == outcome, _closing(m.close_1x2, sel, price[1])))
    if over_final is not None:
        for sel, p in (("over", over_final), ("under", 1 - over_final)):
            price = _price(m.pre_totals, sel, params.price_source)
            if price:
                hit = (sel == "over") == bool(row["over_hit"])
                candidates.append((Candidate("totals_2.5", sel, p, price[0], price[1], validated=True), hit,
                                   _closing(m.close_totals, sel, price[1])))

    if mkt is not None:
        legs = _slip_legs(m, r, outcome, final, mkt, probs, rel.score, disagreement, min(out.sample_sizes.values()), params)
        if legs:
            row["slip_legs"] = legs

    # At most one bet per market per match: the qualifying selection with highest EV
    chosen: dict[str, tuple] = {}
    for cand, hit, closing in candidates:
        if not evaluate_candidate(cand, params.rules, rel, 0.0, disagreement):
            if cand.market not in chosen or cand.ev > chosen[cand.market][0].ev:
                chosen[cand.market] = (cand, hit, closing)
    for cand, hit, closing in chosen.values():
        profit = cand.odds - 1 if hit else -1.0
        bets.append({
            "date": r.kickoff.isoformat(), "competition": comp, "match": f"{r.home} v {r.away}",
            "market": cand.market, "selection": cand.selection, "odds": cand.odds, "bookmaker": cand.bookmaker,
            "probability": round(cand.probability, 4), "ev": round(cand.ev, 4), "profit": profit,
            "closing_odds": closing, "clv": (cand.odds / closing - 1) if closing else None,
        })
    return row


def _slip_legs(m: BacktestMatch, r: MatchRecord, outcome: int, final: np.ndarray, mkt: np.ndarray, probs: dict,
               reliability: float, disagreement: float | None, sample: int, params: BacktestParams) -> list[SlipLeg]:
    """Legs that pass the daily 2 odds checks. Context (form, news, ...) is not replayed."""
    legs = []
    for idx, sel in ((0, "home"), (2, "away")):
        price = _price(m.pre_1x2, sel, params.price_source)
        if not price:
            continue
        checks = core_checks(sel, float(final[idx]), float(mkt[idx]), price[0], reliability, disagreement, sample, 0.0,
                             probs, params.slip_rules)
        if leg_passes(checks, params.slip_rules):
            average = m.pre_1x2.get("avg", {}).get(sel, price[0])
            legs.append(SlipLeg(r.key, float(final[idx]), price[0], {"hit": idx == outcome, "average_odds": average}))
    return legs


def slip_summary(rows: list[dict], rules: SlipRules) -> dict:
    """One slip per calendar day with matches, staked at 1 unit."""
    by_day: dict[str, list[SlipLeg]] = defaultdict(list)
    days = set()
    for r in rows:
        day = r["date"][:10]
        days.add(day)
        by_day[day].extend(r.get("slip_legs", []))
    slips = [(day, slip) for day in sorted(by_day) if (slip := build_slip(by_day[day], rules))]
    if not slips:
        return {"slips": 0, "days_with_matches": len(days)}
    won, profits, at_average, odds_used, expected, run, worst = 0, [], [], [], [], 0, 0
    for _, slip in slips:
        hit = all(leg.payload["hit"] for leg in slip)
        won += hit
        price = math.prod(leg.odds for leg in slip)
        average = math.prod(leg.payload["average_odds"] for leg in slip)
        profits.append(price - 1 if hit else -1.0)
        at_average.append(average - 1 if hit else -1.0)
        odds_used.append(price)
        expected.append(combined_probability(slip))
        run = 0 if hit else run + 1
        worst = max(worst, run)
    n = len(slips)
    rate = won / n
    margin = 1.645 * math.sqrt(rate * (1 - rate) / n)
    return {
        "slips": n, "days_with_matches": len(days), "won": won, "hit_rate": rate,
        "hit_rate_interval_90": [max(0.0, rate - margin), min(1.0, rate + margin)],
        "expected_hit_rate": float(np.mean(expected)), "avg_odds": float(np.mean(odds_used)),
        "avg_legs": float(np.mean([len(s) for _, s in slips])), "roi": sum(profits) / n,
        "roi_interval_90": bootstrap_roi_interval(profits), "roi_at_average_odds": sum(at_average) / n,
        "longest_losing_run": worst, "max_drawdown": round(max_drawdown(profits), 3),
    }


def _totals_weight(oos_over: list[tuple[float, float, int]]) -> float:
    """Learned weight on the market in the over/under 2.5 blend (DC vs market)."""
    tot = LinearPool(["dixon_coles", "market"]).fit(
        {"dixon_coles": np.array([[d, 1 - d] for d, _, _ in oos_over]),
         "market": np.array([[mk, 1 - mk] for _, mk, _ in oos_over])},
        np.array([1 - h for _, _, h in oos_over]))
    return float(tot.weights[1])


def _closing(books: dict[str, dict[str, float]], selection: str, bookmaker: str) -> float | None:
    if bookmaker in books and selection in books[bookmaker]:
        return books[bookmaker][selection]
    return books.get("avg", {}).get(selection)


def _metrics(probs: np.ndarray, outcomes: np.ndarray) -> dict[str, float]:
    return {"log_loss": log_loss(probs, outcomes), "brier": brier(probs, outcomes),
            "accuracy": float((probs.argmax(axis=1) == outcomes).mean()), "n": int(len(outcomes))}


def _ece(bins: list[dict]) -> float:
    total = sum(b["count"] for b in bins)
    return sum(b["count"] * abs(b["predicted"] - b["observed"]) for b in bins) / total if total else math.nan


def _bet_summary(bets: list[dict]) -> dict:
    if not bets:
        return {"bets": 0, "profit": 0.0, "roi": None, "hit_rate": None, "max_drawdown": 0.0,
                "edge_demonstrated": False}
    profits = [b["profit"] for b in bets]
    clvs = [b["clv"] for b in bets if b["clv"] is not None]
    return {
        "bets": len(bets), "profit": round(sum(profits), 3), "roi": sum(profits) / len(bets),
        "hit_rate": sum(p > 0 for p in profits) / len(bets),
        "avg_odds": float(np.mean([b["odds"] for b in bets])),
        "max_drawdown": round(max_drawdown(profits), 3),
        "roi_interval_90": bootstrap_roi_interval(profits),
        "clv_mean": float(np.mean(clvs)) if clvs else None,
        "clv_positive_rate": float(np.mean([c > 0 for c in clvs])) if clvs else None,
        "clv_n": len(clvs),
        # An edge counts as demonstrated only if the whole 90% ROI interval is above
        # zero AND bets on average beat the closing line. Small positive ROI alone is not evidence.
        "edge_demonstrated": bool(
            len(bets) >= 100 and (ci := bootstrap_roi_interval(profits)) is not None and ci[0] > 0
            and clvs and float(np.mean(clvs)) > 0
        ),
    }


def summarise(rows, bets, oos, oos_outcomes, oos_over, weights_history, params: BacktestParams) -> dict:
    if not rows:
        return {"matches": 0, "message": "no matches in evaluation window"}
    outcomes = np.array([r["outcome"] for r in rows])
    final = np.array([r["final"] for r in rows])
    result: dict = {"matches": len(rows), "date_from": params.evaluate_from.isoformat(),
                    "date_to": params.evaluate_to.isoformat(), "price_source": params.price_source,
                    "step_days": params.step_days}

    # Component comparison on the subset where every component and the market exist
    full = [i for i, r in enumerate(rows) if all(c in r["components"] for c in COMPONENTS_1X2)]
    comparison = {}
    if full:
        sub_out = outcomes[full]
        for c in COMPONENTS_1X2:
            comparison[c] = _metrics(np.array([rows[i]["components"][c] for i in full]), sub_out)
        comparison["ensemble"] = _metrics(final[full], sub_out)
        base = np.bincount(outcomes, minlength=3) / len(outcomes)
        comparison["base_rates"] = _metrics(np.tile(base, (len(full), 1)), sub_out)
        comparison["base_rates"]["note"] = "in-sample class frequencies (optimistic baseline)"
    result["one_x_two"] = {"all": _metrics(final, outcomes), "comparison_common_subset": comparison}

    calib = {}
    for idx, name in enumerate(("home", "draw", "away")):
        calib[name] = calibration_bins(final[:, idx], (outcomes == idx).astype(int))
    result["calibration"] = calib
    result["calibration_ece"] = {k: _ece(v) for k, v in calib.items()}
    result["calibration_tests"] = {name: calibration_test(final[:, idx], (outcomes == idx).astype(int))
                                   for idx, name in enumerate(("home", "draw", "away"))}

    over_rows = [r for r in rows if r.get("final_over") is not None]
    if over_rows:
        p = np.array([r["final_over"] for r in over_rows])
        hit = np.array([r["over_hit"] for r in over_rows])
        two = np.column_stack([p, 1 - p])
        result["totals_2.5"] = {
            "model": {"log_loss": log_loss(two, 1 - hit), "brier": float(((p - hit) ** 2).mean()), "n": len(hit)},
            "calibration": calibration_bins(p, hit),
        }
        mo = [(r["market_over"], r["over_hit"]) for r in over_rows if r.get("market_over") is not None]
        if mo:
            mp, mh = np.array([x for x, _ in mo]), np.array([h for _, h in mo])
            result["totals_2.5"]["market"] = {"log_loss": log_loss(np.column_stack([mp, 1 - mp]), 1 - mh),
                                              "brier": float(((mp - mh) ** 2).mean()), "n": len(mh)}
        result["totals_2.5"]["ece"] = _ece(result["totals_2.5"]["calibration"])
        result["totals_2.5"]["calibration_test"] = calibration_test(p, hit)

    # Final learned weights from *all* out-of-sample predictions: used for deployment
    learned = {}
    if len(oos_outcomes) >= params.min_oos_for_weights:
        learned = LogPool(COMPONENTS_1X2).fit({c: np.array(oos[c]) for c in COMPONENTS_1X2},
                                               np.array(oos_outcomes)).to_dict()
    if len(oos_over) >= params.min_oos_for_weights:
        learned["_totals_market"] = _totals_weight(oos_over)
    result["learned_weights"] = learned
    result["weights_history"] = weights_history[-60:]

    result["betting"] = {"overall": _bet_summary(bets)}
    by_market, by_comp, by_bucket = defaultdict(list), defaultdict(list), defaultdict(list)
    for b in bets:
        by_market[b["market"]].append(b)
        by_comp[b["competition"]].append(b)
        for lo, hi in ODDS_BUCKETS:
            if lo <= b["odds"] < hi:
                by_bucket[f"{lo:.1f}-{hi:.1f}" if hi < 1000 else f"{lo:.1f}+"].append(b)
    result["betting"]["by_market"] = {k: _bet_summary(v) for k, v in by_market.items()}
    result["betting"]["by_competition"] = {k: _bet_summary(v) for k, v in by_comp.items()}
    result["betting"]["by_odds_range"] = {k: _bet_summary(v) for k, v in by_bucket.items()}
    cum, curve = 0.0, []
    for b in sorted(bets, key=lambda b: b["date"]):
        cum += b["profit"]
        curve.append({"date": b["date"][:10], "cumulative_profit": round(cum, 3)})
    result["betting"]["equity_curve"] = curve
    result["bets"] = sorted(bets, key=lambda b: b["date"])
    result["two_odds"] = slip_summary(rows, params.slip_rules)
    by_comp_acc = defaultdict(list)
    for i, r in enumerate(rows):
        by_comp_acc[r["competition"]].append(i)
    result["one_x_two"]["by_competition"] = {
        c: _metrics(final[idx], outcomes[idx]) for c, idx in by_comp_acc.items()
    }

    # "Validated" = enough out-of-sample predictions AND no statistically significant
    # miscalibration (p >= 0.05 for every outcome, Bonferroni-free so slightly strict).
    # It says nothing about profitability; see betting.*.edge_demonstrated for that.
    validated = []
    if result["one_x_two"]["all"]["n"] >= 300 and min(
            t["p_value"] for t in result["calibration_tests"].values()) >= 0.05:
        validated += ["1x2", "double_chance", "draw_no_bet"]
    if over_rows and len(over_rows) >= 300 and result["totals_2.5"]["calibration_test"]["p_value"] >= 0.05:
        validated.append("totals_2.5")
    result["validated_markets"] = validated
    return result
