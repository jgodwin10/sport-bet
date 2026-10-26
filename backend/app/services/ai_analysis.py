"""AI match analysis: Gemini reads the platform's own evidence for a fixture, searches
the web for current team news, and writes a structured narrative.

The output is advisory. It is stored and shown next to the model, but it never
changes probabilities, selections or reliability: an LLM's numbers have no
walk-forward validation (and cannot have one, since web search would see results).
Its 1X2 view is stored so it can be compared against outcomes going forward.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import AiAnalysis, Fixture, Prediction
from app.providers.gemini import GeminiClient, GeminiError, GeminiUnavailable, get_gemini
from app.services.analytics import head_to_head, standings, summarise_form, team_recent

log = logging.getLogger(__name__)

FAVOURS = {"home", "away", "draw", "neither"}
WEIGHTS = {"low", "medium", "high"}
BASIS = {"model", "news", "both"}
NEWS_STATUS = {"confirmed", "reported", "rumour"}
CONFIDENCE = {"low", "medium", "high"}

SYSTEM = (
    "You are a careful football analyst supporting a statistical prediction platform. "
    "You receive the platform's model output and evidence for one upcoming match. Use Google Search to find "
    "current, relevant information the model cannot see: injuries, suspensions, expected lineups, manager "
    "changes, fixture congestion, motivation (title race, relegation, cup priorities), travel and weather. "
    "Rules: only report news you actually found and say how solid it is; never invent players, quotes or "
    "statistics; prefer sources from the last 14 days; say plainly when you found nothing relevant. "
    "Do not recommend bets or stakes. Respond with a single JSON object and nothing else."
)

SCHEMA_HINT = """{
  "summary": "3-5 sentence overview of how the match is likely to play out and why",
  "key_factors": [{"title": "short label", "detail": "1-2 sentences", "favours": "home|away|draw|neither",
                   "weight": "low|medium|high", "basis": "model|news|both"}],
  "team_news": [{"team": "team name", "detail": "what was reported, with date if known",
                 "status": "confirmed|reported|rumour"}],
  "risks": ["things that could make the forecast wrong"],
  "model_assessment": "does the news support, weaken or not affect the model's view? be specific",
  "probability_view": {"home": 0.0, "draw": 0.0, "away": 0.0},
  "confidence": "low|medium|high"
}"""


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def build_prompt(db: Session, fixture: Fixture, prediction: Prediction, now: datetime) -> str:
    home, away = fixture.home_team.name, fixture.away_team.name
    m = prediction.markets or {}
    one = m.get("1x2", {})
    lines = [
        f"Today (UTC): {now:%Y-%m-%d %H:%M}",
        f"Match: {home} (home) vs {away} (away)",
        f"Competition: {fixture.competition.name} ({fixture.competition.country})",
        f"Kickoff (UTC): {fixture.kickoff_utc:%Y-%m-%d %H:%M}" + (f", venue {fixture.venue}" if fixture.venue else ""),
        "",
        "PLATFORM MODEL OUTPUT (statistical ensemble of Dixon-Coles, Elo, a logistic model and margin-free "
        "bookmaker prices; validated by walk-forward backtests)",
        f"1X2: home {_pct(one.get('home'))}, draw {_pct(one.get('draw'))}, away {_pct(one.get('away'))}",
    ]
    if xg := m.get("expected_goals"):
        lines.append(f"Expected goals: {home} {xg['home']:.2f}, {away} {xg['away']:.2f}")
    if (t := (m.get("totals") or {}).get("2.5")) is not None:
        lines.append(f"Over 2.5 goals: {_pct(t.get('over'))}")
    if b := m.get("btts"):
        lines.append(f"Both teams score: {_pct(b.get('yes'))}")
    rel = prediction.reliability or {}
    lines.append(f"Data reliability: {rel.get('label')} ({rel.get('score')}/100); lineups: {prediction.lineup_status}; "
                 f"platform verdict: {prediction.classification}")
    lines += ["", "EVIDENCE THE MODEL USED"]
    lines += [f"- [{e.category}] {e.text}" for e in prediction.explanations]

    cutoff = min(now, fixture.kickoff_utc)
    for label, team_id, name in (("home", fixture.home_team_id, home), ("away", fixture.away_team_id, away)):
        form = summarise_form(team_recent(db, team_id, cutoff))
        last10 = form.get("last_10")
        if last10:
            lines.append(f"- [form] {name} last 10 (newest first): {form['sequence']}, "
                         f"{last10['goals_for']}-{last10['goals_against']} goals, {last10['points_per_game']} pts/game")
    table = {r["team_id"]: r for r in standings(db, fixture.season_id, cutoff)}
    for team_id, name in ((fixture.home_team_id, home), (fixture.away_team_id, away)):
        if r := table.get(team_id):
            lines.append(f"- [table] {name}: position {r.get('position')} of {len(table)}, {r.get('points')} pts "
                         f"from {r.get('played')} games")
    for h in head_to_head(db, fixture.home_team_id, fixture.away_team_id, cutoff)[:5]:
        lines.append(f"- [h2h] {h['date'][:10]}:{h['home']} {h['home_goals']}-{h['away_goals']} {h['away']}")

    lines += [
        "",
        "TASK",
        "1. Search for the latest team news and context for both teams before this kickoff.",
        "2. Weigh that news against the model output above. The model does not adjust for injuries, lineups, "
        "motivation or weather, so say where those matter and how much.",
        "3. Give your own home/draw/away probabilities (they must sum to 1). Stay close to the model unless "
        "the news gives a concrete reason to move, and explain any move in model_assessment.",
        "",
        "Return JSON exactly in this shape:",
        SCHEMA_HINT,
    ]
    return "\n".join(lines)


def _extract_json(text: str) -> dict | None:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _s(value: object, limit: int) -> str:
    return str(value).strip()[:limit] if value is not None else ""


def _choice(value: object, allowed: set[str], default: str) -> str:
    v = str(value).strip().lower() if value is not None else ""
    return v if v in allowed else default


def normalise(text: str) -> dict:
    """Validate Gemini's JSON into the stored shape. Unparseable answers are kept as plain text."""
    data = _extract_json(text)
    if data is None:
        return {"summary": _s(text, 4000), "structured": False, "key_factors": [], "team_news": [], "risks": [],
                "model_assessment": "", "probability_view": None, "confidence": "low"}
    factors = [{"title": _s(f.get("title"), 120), "detail": _s(f.get("detail"), 600),
                "favours": _choice(f.get("favours"), FAVOURS, "neither"),
                "weight": _choice(f.get("weight"), WEIGHTS, "medium"),
                "basis": _choice(f.get("basis"), BASIS, "model")}
               for f in (data.get("key_factors") or []) if isinstance(f, dict) and f.get("title")][:10]
    news = [{"team": _s(n.get("team"), 120), "detail": _s(n.get("detail"), 600),
             "status": _choice(n.get("status"), NEWS_STATUS, "reported")}
            for n in (data.get("team_news") or []) if isinstance(n, dict) and n.get("detail")][:16]
    risks = [_s(r, 300) for r in (data.get("risks") or []) if isinstance(r, str) and r.strip()][:8]

    view = None
    pv = data.get("probability_view")
    if isinstance(pv, dict):
        try:
            vals = {k: float(pv[k]) for k in ("home", "draw", "away")}
        except (KeyError, TypeError, ValueError):
            vals = None
        if vals:
            if max(vals.values()) > 1.0:  # answered in percent
                vals = {k: v / 100 for k, v in vals.items()}
            total = sum(vals.values())
            if all(v >= 0 for v in vals.values()) and 0.5 < total < 1.5:
                view = {k: round(v / total, 4) for k, v in vals.items()}
    return {"summary": _s(data.get("summary"), 2000), "structured": True, "key_factors": factors,
            "team_news": news, "risks": risks, "model_assessment": _s(data.get("model_assessment"), 1500),
            "probability_view": view, "confidence": _choice(data.get("confidence"), CONFIDENCE, "low")}


def analysis_out(a: AiAnalysis) -> dict:
    return {"id": a.id, "fixture_id": a.fixture_id, "prediction_id": a.prediction_id, "created_at": a.created_at,
            "status": a.status, "provider": a.provider, "model": a.model, "trigger": a.trigger,
            "content": a.content, "sources": a.sources, "search_queries": a.search_queries, "error": a.error}


class AiAnalysisService:
    def __init__(self, db: Session, settings: Settings, client: GeminiClient | None = None) -> None:
        self.db = db
        self.settings = settings
        self.client = client or get_gemini()

    @property
    def configured(self) -> bool:
        return self.client.configured

    def latest(self, fixture_id: int, ok_only: bool = False) -> AiAnalysis | None:
        q = select(AiAnalysis).where(AiAnalysis.fixture_id == fixture_id)
        if ok_only:
            q = q.where(AiAnalysis.status == "ok")
        return self.db.scalar(q.order_by(AiAnalysis.created_at.desc(), AiAnalysis.id.desc()).limit(1))

    def analyse(self, fixture: Fixture, trigger: str = "manual", requested_by: str | None = None,
                now: datetime | None = None) -> AiAnalysis:
        """Analyse the fixture's latest prediction. Reuses a successful analysis of the same
        prediction snapshot instead of spending quota on an identical request.

        Raises ValueError if the fixture cannot be analysed and GeminiUnavailable when no key can serve it.
        """
        now = now or datetime.now(timezone.utc)
        if fixture.kickoff_utc <= now or fixture.status != "scheduled":
            # After kickoff, web search would see the live score or result.
            raise ValueError("AI analysis is only available before kickoff")
        prediction = self.db.scalar(select(Prediction).where(Prediction.fixture_id == fixture.id)
                                    .order_by(Prediction.created_at.desc(), Prediction.id.desc()).limit(1))
        if prediction is None:
            raise ValueError("this match has no model prediction yet")
        existing = self.latest(fixture.id, ok_only=True)
        if existing is not None and existing.prediction_id == prediction.id:
            return existing

        prompt = build_prompt(self.db, fixture, prediction, now)
        row = AiAnalysis(fixture_id=fixture.id, prediction_id=prediction.id, created_at=now, trigger=trigger,
                         requested_by=requested_by, provider="gemini", sources=[], search_queries=[])
        try:
            result = self.client.generate(prompt, system=SYSTEM, search=self.settings.gemini_search_grounding)
        except GeminiUnavailable:
            raise  # nothing was attempted successfully; keep quota problems out of the history
        except GeminiError as exc:
            row.status, row.error = "failed", str(exc)[:1000]
        else:
            content = normalise(result.text)
            content["basis"] = {"prediction_id": prediction.id, "lineup_status": prediction.lineup_status,
                                "model_1x2": (prediction.markets or {}).get("1x2")}
            row.status, row.model, row.key_slot = "ok", result.model, result.key_slot
            row.content, row.sources, row.search_queries = content, result.sources[:20], result.search_queries[:10]
        self.db.add(row)
        self.db.commit()
        return row

    def due(self, fixture: Fixture, prediction: Prediction, now: datetime) -> bool:
        last = self.latest(fixture.id, ok_only=True)
        if last is None:
            return True
        if prediction.lineup_status == "confirmed" and (last.content or {}).get("basis", {}).get(
                "lineup_status") != "confirmed":
            return True
        return now - last.created_at >= timedelta(hours=self.settings.gemini_refresh_hours)

    def analyse_upcoming(self, now: datetime | None = None) -> dict:
        """Scheduled run: fixtures kicking off soon whose analysis is missing or stale, soonest first."""
        now = now or datetime.now(timezone.utc)
        s = self.settings
        summary: dict = {"analysed": 0, "failed": 0, "skipped": 0}
        if not self.configured or s.gemini_auto_hours <= 0:
            return {**summary, "note": "Gemini not configured or scheduled analysis disabled"}
        fixtures = list(self.db.scalars(select(Fixture).where(
            Fixture.status == "scheduled", Fixture.kickoff_utc > now,
            Fixture.kickoff_utc < now + timedelta(hours=s.gemini_auto_hours)).order_by(Fixture.kickoff_utc)))
        for f in fixtures:
            if summary["analysed"] + summary["failed"] >= s.gemini_auto_max_per_run:
                break
            prediction = self.db.scalar(select(Prediction).where(Prediction.fixture_id == f.id)
                                        .order_by(Prediction.created_at.desc(), Prediction.id.desc()).limit(1))
            if prediction is None or not self.due(f, prediction, now):
                summary["skipped"] += 1
                continue
            try:
                row = self.analyse(f, trigger="scheduled", now=now)
            except GeminiUnavailable as exc:
                summary["stopped"] = str(exc)  # every key is cooling down; try again next cycle
                break
            except Exception:  # noqa: BLE001 - one fixture must not stop the batch
                log.exception("AI analysis failed for fixture %s", f.id)
                self.db.rollback()
                summary["failed"] += 1
                continue
            summary["analysed" if row.status == "ok" else "failed"] += 1
        return summary
