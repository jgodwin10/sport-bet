"""Prediction reliability and bet-selection rules.

Two deliberately separate concepts:
* outcome probability - the model's estimate that an event happens;
* prediction reliability - how much the system trusts the quality/stability of
  that estimate. A 75% outcome probability can have *low* reliability.

Reliability starts at 100 and each factor subtracts a transparent, recorded
penalty. The penalties are configuration, not learned values; their purpose is
to gate recommendations, not to modify the probabilities.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.engine.odds import edge as calc_edge
from app.engine.odds import expected_value, implied_probability


@dataclass
class ReliabilityInputs:
    min_team_matches: int  # fewer of the two teams' matches in the training window
    model_disagreement: float | None  # max pairwise TV distance between components
    interval_width: float | None  # width of 90% interval for the selected/1X2 probability
    odds_age_hours: float | None  # None = no odds at all
    lineup_status: str  # "confirmed" | "projected" | "unavailable"
    unresolved_conflicts: int
    stale_inputs: list[str]
    market_validated: bool
    ensemble_validated: bool
    missing_optional: list[str] = field(default_factory=list)


@dataclass
class ReliabilityFactor:
    factor: str
    penalty: float
    detail: str


@dataclass
class Reliability:
    score: float
    label: str
    factors: list[ReliabilityFactor]

    def to_dict(self) -> dict[str, object]:
        return {"score": round(self.score, 1), "label": self.label, "factors": [asdict(f) for f in self.factors]}


def assess_reliability(r: ReliabilityInputs) -> Reliability:
    factors: list[ReliabilityFactor] = []

    def add(name: str, penalty: float, detail: str) -> None:
        if penalty > 0:
            factors.append(ReliabilityFactor(name, round(penalty, 1), detail))

    if r.min_team_matches < 10:
        add("sample_size", 30, f"one team has only {r.min_team_matches} matches in the training window")
    elif r.min_team_matches < 25:
        add("sample_size", 12, f"one team has only {r.min_team_matches} matches in the training window")

    if r.model_disagreement is None:
        add("single_model", 10, "only one model component available; disagreement cannot be checked")
    elif r.model_disagreement > 0.15:
        add("model_disagreement", 25, f"component models disagree materially (TV distance {r.model_disagreement:.2f})")
    elif r.model_disagreement > 0.08:
        add("model_disagreement", 10, f"component models disagree moderately (TV distance {r.model_disagreement:.2f})")

    if r.interval_width is not None and r.interval_width > 0.15:
        add("parameter_uncertainty", min(20, (r.interval_width - 0.15) * 100 + 8),
            f"90% interval for the main probability is {r.interval_width:.0%} wide")

    if r.odds_age_hours is None:
        add("no_odds", 15, "no bookmaker odds available; value cannot be assessed")
    elif r.odds_age_hours > 24:
        add("stale_odds", 15, f"latest odds are {r.odds_age_hours:.0f}h old")
    elif r.odds_age_hours > 6:
        add("stale_odds", 5, f"latest odds are {r.odds_age_hours:.0f}h old")

    if r.lineup_status == "unavailable":
        add("pre_lineup", 10, "pre-lineup prediction; no lineup or availability data")
    elif r.lineup_status == "projected":
        add("pre_lineup", 5, "lineups are projected, not confirmed")

    if r.unresolved_conflicts:
        add("source_conflicts", 15 * r.unresolved_conflicts, f"{r.unresolved_conflicts} unresolved source conflict(s)")
    if r.stale_inputs:
        add("stale_inputs", 10, "stale inputs: " + ", ".join(r.stale_inputs))
    if not r.ensemble_validated:
        add("unvalidated_ensemble", 15, "ensemble weights not yet validated by a walk-forward backtest")
    if not r.market_validated:
        add("unvalidated_market", 10, "market has no walk-forward validation")

    score = max(0.0, 100.0 - sum(f.penalty for f in factors))
    label = "high" if score >= 75 else "moderate" if score >= 55 else "low"
    return Reliability(score=score, label=label, factors=factors)


@dataclass
class SelectionRules:
    min_probability: float = 0.20
    min_edge: float = 0.02
    min_ev: float = 0.03
    min_odds: float = 1.30
    max_odds: float = 6.0
    min_reliability: float = 60.0
    max_odds_age_hours: float = 12.0
    require_lower_bound_ev_positive: bool = True
    max_disagreement: float = 0.12


@dataclass
class Candidate:
    market: str
    selection: str
    probability: float
    odds: float
    bookmaker: str | None
    probability_lower: float | None = None
    validated: bool = False

    @property
    def implied(self) -> float:
        return implied_probability(self.odds)

    @property
    def ev(self) -> float:
        return expected_value(self.probability, self.odds)

    @property
    def edge(self) -> float:
        return calc_edge(self.probability, self.odds)


def evaluate_candidate(
    c: Candidate, rules: SelectionRules, reliability: Reliability, odds_age_hours: float | None,
    disagreement: float | None,
) -> list[str]:
    """Return the reasons this candidate fails the rules (empty list = qualifies)."""
    reasons = []
    if not c.validated:
        reasons.append("market not validated by backtest")
    if c.probability < rules.min_probability:
        reasons.append(f"probability {c.probability:.1%} below minimum {rules.min_probability:.0%}")
    if c.edge < rules.min_edge:
        reasons.append(f"edge {c.edge:+.1%} below minimum {rules.min_edge:.0%}")
    if c.ev < rules.min_ev:
        reasons.append(f"expected value {c.ev:+.1%} below minimum {rules.min_ev:.0%}")
    if not rules.min_odds <= c.odds <= rules.max_odds:
        reasons.append(f"odds {c.odds:.2f} outside [{rules.min_odds}, {rules.max_odds}]")
    if reliability.score < rules.min_reliability:
        reasons.append(f"reliability {reliability.score:.0f} below minimum {rules.min_reliability:.0f}")
    if odds_age_hours is None or odds_age_hours > rules.max_odds_age_hours:
        reasons.append("odds missing or stale")
    if disagreement is not None and disagreement > rules.max_disagreement:
        reasons.append(f"model disagreement {disagreement:.2f} exceeds {rules.max_disagreement}")
    if rules.require_lower_bound_ev_positive and c.probability_lower is not None:
        if expected_value(c.probability_lower, c.odds) <= 0:
            reasons.append("EV is not positive at the lower end of the probability interval")
    return reasons


def classify(qualifying: list[Candidate], reliability: Reliability) -> str:
    """Overall match classification shown to users."""
    if qualifying:
        return "consider"
    if reliability.label == "low":
        return "high_uncertainty"
    return "no_bet"
