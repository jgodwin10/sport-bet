"""Daily 2 odds slip: pure leg checks and the search for the best combination.

A slip multiplies bookmaker margins, so it wins less often than its odds suggest, and at
combined odds of about 2 no honest estimate can be far above 50%. Nothing here makes a slip
safe. It only narrows the choice to legs where the model, the market and the data agree, then
takes the combination most likely to win.

Legs are 1X2 favourites because they held up best on real prices: over 2022-2026, adding over/under
2.5 lowered the slip hit rate from 51% to 48%, and raising the leg minimum above 60% halved the
number of days with a slip without a measurable gain in hit rate. The walk-forward backtest runs
the same checks and search, so `two_odds` in its metrics measures this code.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

PASS, NOTE, FAIL, UNCHECKED = "pass", "note", "fail", "unchecked"
OUTCOME_INDEX = {"home": 0, "draw": 1, "away": 2}


@dataclass
class SlipRules:
    min_leg_probability: float = 0.60
    min_component_probability: float = 0.45  # every statistical model must broadly agree
    max_market_gap: float = 0.05  # model vs margin-free market, either direction
    min_reliability: float = 60.0
    min_team_matches: int = 25
    max_disagreement: float = 0.12
    max_odds_age_hours: float = 24.0
    min_leg_odds: float = 1.10
    min_combined_odds: float = 2.0
    max_combined_odds: float = 2.4
    max_legs: int = 5
    pool_size: int = 14  # strongest legs searched; keeps the exhaustive search small
    max_notes: int = 1  # context checks that may point against a leg before it is dropped


@dataclass
class Check:
    key: str
    label: str
    status: str  # pass | note | fail | unchecked
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class SlipLeg:
    fixture: Hashable  # one leg per fixture
    probability: float
    odds: float
    payload: Any = None


def core_checks(selection: str, probability: float, fair: float | None, odds: float, reliability: float,
                disagreement: float | None, min_team_matches: int, odds_age_hours: float | None,
                components: Mapping[str, Sequence[float]], rules: SlipRules) -> list[Check]:
    """Checks shared by live slips and the backtest. Any failure rules the leg out."""
    checks = [Check("probability", "Chance of winning",
                    PASS if probability >= rules.min_leg_probability else FAIL,
                    f"{probability:.0%} estimated; the minimum is {rules.min_leg_probability:.0%}")]

    if fair is None:
        checks.append(Check("market", "Bookmakers agree", FAIL, "no complete bookmaker prices to compare against"))
    else:
        gap = probability - fair
        checks.append(Check("market", "Bookmakers agree", PASS if abs(gap) <= rules.max_market_gap else FAIL,
                            f"bookmakers imply {fair:.0%} without their margin, {abs(gap):.0%} from our estimate"))

    idx = OUTCOME_INDEX[selection]
    stats = {name: p[idx] for name, p in components.items() if name != "market"}
    if not stats:
        checks.append(Check("models", "Models agree", FAIL, "no statistical model scored this match"))
    else:
        low_name, low = min(stats.items(), key=lambda kv: kv[1])
        spread = "" if disagreement is None else f"; overall disagreement {disagreement:.2f}"
        ok = low >= rules.min_component_probability and (disagreement is None or disagreement <= rules.max_disagreement)
        checks.append(Check("models", "Models agree", PASS if ok else FAIL,
                            f"{len(stats)} models; the lowest ({low_name.replace('_', ' ')}) gives {low:.0%}{spread}"))

    checks.append(Check("data", "Enough match history", PASS if min_team_matches >= rules.min_team_matches else FAIL,
                        f"{min_team_matches} recent matches for the team with fewer; "
                        f"the minimum is {rules.min_team_matches}"))
    checks.append(Check("reliability", "Data quality", PASS if reliability >= rules.min_reliability else FAIL,
                        f"reliability {reliability:.0f}/100; the minimum is {rules.min_reliability:.0f}"))
    if odds_age_hours is None:
        checks.append(Check("odds", "Fresh price", FAIL, "no bookmaker price"))
    else:
        fresh = odds_age_hours <= rules.max_odds_age_hours and odds >= rules.min_leg_odds
        checks.append(Check("odds", "Fresh price", PASS if fresh else FAIL,
                            f"{odds:.2f}, last seen {odds_age_hours:.0f}h ago"))
    return checks


def leg_passes(checks: Sequence[Check], rules: SlipRules) -> bool:
    return (not any(c.status == FAIL for c in checks)
            and sum(c.status == NOTE for c in checks) <= rules.max_notes)


def in_range(odds: float, rules: SlipRules) -> bool:
    return rules.min_combined_odds <= odds <= rules.max_combined_odds


def build_slip(legs: Sequence[SlipLeg], rules: SlipRules) -> list[SlipLeg] | None:
    """The combination with the highest chance of winning whose odds are in range, at most one
    leg per fixture. Legs are treated as independent. Ties go to the shorter slip."""
    pool = sorted(legs, key=lambda leg: -leg.probability)[:rules.pool_size]
    best, best_p = None, -1.0
    for n in range(1, rules.max_legs + 1):
        for combo in itertools.combinations(pool, n):
            if len({leg.fixture for leg in combo}) < n or not in_range(combined_odds(combo), rules):
                continue
            p = combined_probability(combo)
            if p > best_p:
                best, best_p = list(combo), p
    return best


def combined_odds(legs: Sequence[SlipLeg]) -> float:
    return math.prod(leg.odds for leg in legs)


def combined_probability(legs: Sequence[SlipLeg]) -> float:
    return math.prod(leg.probability for leg in legs)
