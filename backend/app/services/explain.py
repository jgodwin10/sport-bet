"""Explanations generated strictly from model inputs and outputs.

Each item carries the exact evidence values it was built from. Nothing here is
free text written after the fact: if an input is missing, the corresponding
explanation says so instead of filling the gap.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Explanation:
    category: str
    text: str
    evidence: dict


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _rel(x: float) -> str:
    """Multiplicative rating relative to league average, e.g. 1.18 -> '18% above'."""
    d = (x - 1) * 100
    return f"{abs(d):.0f}% {'above' if d >= 0 else 'below'} league average"


def build_explanations(
    *, home: str, away: str, final: dict[str, float], components: dict[str, list[float]],
    weights: dict[str, float], dc_params: dict | None, expected_goals: dict | None, elo: dict,
    raw_features: dict, market: dict[str, float] | None, h2h: list[dict], context: dict,
    missing: list[str], reliability: dict, lineup_status: str, availability: list[dict],
    selections: list[dict], classification: str,
) -> list[Explanation]:
    out: list[Explanation] = []
    add = lambda cat, text, ev: out.append(Explanation(cat, text, ev))  # noqa: E731

    fav = max(final, key=final.get)
    label = {"home": f"{home} win", "draw": "a draw", "away": f"{away} win"}[fav]
    add("summary", f"Most likely outcome: {label} ({_pct(final[fav])}). Home {_pct(final['home'])}, "
                   f"draw {_pct(final['draw'])}, away {_pct(final['away'])}.", {"final_1x2": final})

    if expected_goals and dc_params:
        add("goal_model",
            f"Dixon-Coles expects {expected_goals['home']:.2f} goals for {home} and {expected_goals['away']:.2f} "
            f"for {away}. {home} attack is {_rel(dc_params['home_attack'])}; {away} defence concedes "
            f"{_rel(dc_params['away_defence'])}. Home advantage multiplies home scoring by "
            f"{dc_params['home_advantage']:.2f}.",
            {"expected_goals": expected_goals, **{k: round(v, 3) for k, v in dc_params.items()}})
    add("ratings", f"Elo: {home} {elo['home']:.0f}, {away} {elo['away']:.0f}; difference including home "
                   f"advantage {elo['diff']:+.0f}.", elo)

    hgf, hga, agf, aga = (raw_features.get(k) for k in ("home_gf", "home_ga", "away_gf", "away_ga"))
    if None not in (hgf, hga, agf, aga):
        add("form", f"Recency-weighted last-10 form: {home} scores {hgf:.2f} / concedes {hga:.2f} per game; "
                    f"{away} scores {agf:.2f} / concedes {aga:.2f}.",
            {k: raw_features.get(k) for k in ("home_gf", "home_ga", "away_gf", "away_ga", "home_n", "away_n")})
    else:
        add("data_gap", "Recent-form features are incomplete for at least one team (too few prior matches); "
                        "league-average values were used and reliability reduced.",
            {"home_n": raw_features.get("home_n"), "away_n": raw_features.get("away_n")})
    if raw_features.get("home_xgf") is not None and raw_features.get("away_xgf") is not None:
        add("xg", f"Recent xG per game: {home} {raw_features['home_xgf']:.2f} for / "
                  f"{raw_features['home_xga']:.2f} against; {away} {raw_features['away_xgf']:.2f} for / "
                  f"{raw_features['away_xga']:.2f} against. (Shown as context; the goal model is fitted on goals.)",
            {k: raw_features.get(k) for k in ("home_xgf", "home_xga", "away_xgf", "away_xga")})
    rh, ra = raw_features.get("home_rest_days"), raw_features.get("away_rest_days")
    if rh is not None and ra is not None and abs(rh - ra) >= 2:
        add("schedule", f"Rest: {home} {rh:.0f} days, {away} {ra:.0f} days since their last recorded match.",
            {"home_rest_days": rh, "away_rest_days": ra})

    comp_txt = "; ".join(f"{name.replace('_', ' ')}: {_pct(p[0])}/{_pct(p[1])}/{_pct(p[2])}"
                         for name, p in components.items())
    add("models", f"Component estimates (home/draw/away) - {comp_txt}. Ensemble weights: "
                  + ", ".join(f"{k.replace('_', ' ')} {v:.2f}" for k, v in weights.items()) + ".",
        {"components": components, "weights": weights})

    if market:
        diff = {k: final[k] - market[k] for k in final}
        biggest = max(diff, key=lambda k: abs(diff[k]))
        add("market", f"Bookmakers (margin removed, Shin method) imply home {_pct(market['home'])}, draw "
                      f"{_pct(market['draw'])}, away {_pct(market['away'])}. Largest difference from the model: "
                      f"{biggest} {diff[biggest]:+.1%}.", {"market_1x2": market, "difference": diff})
    else:
        add("data_gap", "No bookmaker 1X2 odds available, so value cannot be assessed.", {})

    if h2h:
        recent = [m for m in h2h if m["age_days"] <= 3 * 365]
        add("head_to_head", f"{len(h2h)} previous meetings stored ({len(recent)} within 3 years). Head-to-head "
                            "is shown as context only and is not a model input; older meetings with different "
                            "squads carry little information.", {"meetings": h2h[:5]})

    if context.get("home_position") and context.get("away_position"):
        add("context", f"League position (computed from stored results): {home} {context['home_position']} "
                       f"({context['home_points']} pts), {away} {context['away_position']} "
                       f"({context['away_points']} pts). Motivation is not modelled numerically.", context)

    if lineup_status != "confirmed":
        add("lineups", "Pre-lineup prediction: official lineups are not yet available."
            if lineup_status == "unavailable" else "Lineups are projected, not confirmed.",
            {"lineup_status": lineup_status})
    if availability:
        add("availability", f"{len(availability)} reported absence(s)/doubt(s): "
            + ", ".join(f"{a['player_name']} ({a['team']}, {a['kind']}, {a['verification']})" for a in availability[:8])
            + ". Absences reduce reliability but do not adjust probabilities (no validated player-impact model).",
            {"availability": availability})
    for m in missing:
        add("data_gap", f"Model component unavailable - {m}.", {"missing": m})

    for f in reliability.get("factors", []):
        add("reliability", f"Reliability -{f['penalty']:.0f}: {f['detail']}.", f)

    qualifying = [s for s in selections if s["qualifies"]]
    if classification == "consider" and qualifying:
        for s in qualifying:
            add("selection", f"{s['market']} {s['selection']} at {s['odds']:.2f} ({s['bookmaker']}): model "
                             f"{_pct(s['probability'])} vs implied {_pct(s['implied'])}, EV {s['ev']:+.1%}. "
                             "Expected value is an estimate, not a guaranteed return.", s)
    else:
        best = max(selections, key=lambda s: s["ev"], default=None)
        reason = ("; ".join(best["reasons"][:3]) if best else "no priced selections")
        add("no_bet", "No suitable bet identified" + (f" - best candidate {best['market']} {best['selection']}: {reason}."
                                                     if best else f" ({reason})."),
            {"best_candidate": best})
    return out
