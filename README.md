# Football Analytics & Prediction Platform

Evidence-based football match probabilities, value assessment against bookmaker
prices, and walk-forward model evaluation. It is decision support, not a tipster:
it says **"No suitable bet identified"** whenever the evidence is inadequate, and it
never places bets.

> **Current evidence (see "What the backtests show"):** on real data the ensemble
> does **not** beat the bookmaker market; only over/under 2.5 passes validation, and
> its simulated betting has an ROI interval that spans zero. No betting edge has been
> demonstrated. The platform reports this rather than hiding it.

## What the backtests show (real data, run 2026-10-29)

Walk-forward over **16,330 matches** in all 22 tracked leagues, from 2024-07-01 to 2026-10-29 (2023-24 as the
first training season), with weekly refits and pre-match odds from football-data.co.uk. All leagues advance
through time together, so the ensemble weights at each step come only from earlier predictions:

| 1X2 model | Log loss | Accuracy |
|---|---|---|
| Market (Shin, margin removed) | **0.9983** | 50.9% |
| Ensemble | 1.0004 | 50.7% |
| Dixon-Coles | 1.0221 | 49.0% |
| Elo | 1.0224 | 49.1% |
| Logistic feature model | 1.0300 | 48.8% |
| Base rates | 1.0750 | 43.4% |

- Learned ensemble weights: **market 0.90**, about 0.03 each for Dixon-Coles, Elo and the feature model. The
  statistical models add very little information beyond bookmaker prices.
- Calibration: O/U 2.5 passes (p = 0.30) and is **validated**, so over/under 2.5 selections can qualify. 1X2
  shows a small but detectable draw miscalibration (p = 0.04), so 1X2 is not validated and no 1X2 selection can
  qualify. That is the right call: simulated 1X2 bets lost money (446 bets, ROI −13.4%, 90% CI [−25.1%, −1.5%]).
- O/U 2.5 bets under the default rules: 185 bets, ROI +6.1%, 90% CI [−5.4%, +17.5%], mean CLV +1.5%. Positive but
  not significant: `edge_demonstrated = false`.

Run it with **Actions → Backtest and deploy** (or `python -m app.cli backtest --competitions leagues --from ...
--to ... --deploy`). Deploying sets the weights and validated markets that live predictions use; cups have no
historical odds, so they are not backtested and their selections stay on the watchlist.

The tooling is there to find an edge if one exists, for example with better features or lineup data via
API-Football. With these inputs there is none, and the platform shows "no bet" accordingly.

## Architecture

```
frontend (React/Vite/TS) ──/api──► FastAPI (backend/app/api)
                                        │
          Celery worker + beat ◄──Redis─┤
                                        ▼
                                   PostgreSQL
backend/app/
  providers/   adapters: football-data.co.uk, football-data.org, The Odds API, API-Football
  ingestion/   normalisation, team identity resolution, provenance & conflict rules
  engine/      pure maths: Dixon-Coles, scorelines/markets, Elo, features, ensemble, odds, decision rules
  backtest/    walk-forward engine (same ModelSuite as live predictions)
  services/    DB-facing use cases: predictions, settlement, backtests, analytics, explanations
  api/v1/      REST routes      worker/  Celery tasks + job bodies      cli.py  operations CLI
```

Key design decisions:

| Decision | Why |
|---|---|
| One `ModelSuite` for live and backtest | The backtest measures exactly the code that makes live predictions. `refit()` refuses to run if any absorbed match is at/after the cutoff. |
| Dixon-Coles with time decay + ridge shrinkage | Standard, interpretable goal model; ridge (instead of sum-to-zero) shrinks low-sample (promoted) teams to average. Parameter uncertainty via Laplace approximation → 90% intervals. |
| All goal markets from one score matrix, raked to the ensemble 1X2 / O2.5 | Markets stay mutually consistent (1X2 sums to 1; AH, BTTS, correct score agree with the headline numbers). |
| Ensemble = linear pool of Dixon-Coles, Elo (ordered logit), logistic feature model, margin-free market | Weights are learned **only from out-of-sample walk-forward predictions**. The market is a component, so the ensemble learns how much to trust it. Features never include market data (no double counting). |
| Logistic regression, not gradient boosting, by default | ~1,500 matches/league and six features: GBMs don't beat a regularised linear model here and are harder to calibrate/explain. |
| Shin margin removal | Corrects part of favourite–longshot bias; proportional normalisation is also implemented and tested. |
| Reliability ≠ probability | A transparent penalty-based score (sample size, model disagreement, interval width, odds freshness, lineup status, conflicts, validation status). It gates recommendations. It never changes probabilities. |
| "Validated" market = statistical calibration test, not profit | A market is validated if ≥300 OOS predictions show no significant miscalibration (simulated-null ECE test). Profitability is reported separately as `edge_demonstrated`: the 90% ROI CI must be above 0 **and** mean CLV > 0. |
| Append-only snapshots | Predictions, explanations, selections and odds are immutable (ORM guard + PostgreSQL trigger). Updates create a new snapshot that `supersedes` the previous one, with a change summary. |
| Injuries/lineups affect reliability, not probabilities | There is no validated player-impact model; inventing an adjustment would be unvalidated. |

## Data providers

| Provider | Key | Cost | Used for | Verified limitations |
|---|---|---|---|---|
| [football-data.co.uk](https://www.football-data.co.uk) | none | free | History: results, shots, SoT, corners, cards, **xG (2026/27 on)**; pre-match **and closing** odds (1X2, O/U 2.5, AH) from several bookmakers; weekly upcoming-fixtures file with odds | Kickoff times are UK local (converted to UTC); pre-match odds snapshot time is not published (stored as kickoff−24h, flagged); upcoming file covers only the next round; no injuries/lineups |
| [football-data.org](https://www.football-data.org) | yes | free tier (12 competitions, 10 req/min) | Authoritative UTC kickoff, status (postponed/cancelled) | No odds or injuries on free tier |
| [The Odds API](https://the-odds-api.com) | yes | free 500 credits/month; paid tiers | Live 1X2 + totals from many bookmakers, timestamped | Costs `markets × regions` credits per call; no results |
| [API-Football](https://www.api-football.com) | yes | free 100 req/day | Injuries/suspensions (stored as *reported*), official lineups (*confirmed*) | No projected lineups → status stays `unavailable` until official |

| [TheSportsDB](https://www.thesportsdb.com) | free test key `123` | free (premium from ~$9/mo) | Club crests only | Free key: ~30 req/min and 10 teams per league listing, so crests are looked up per team once and cached. Matching requires the same country and a strong name match; misses fall back to initials instead of guessing |

Crests are downloaded once in 100px/200px renditions, stored in PostgreSQL (`team_crests`) and served from
`/api/v1/teams/{id}/crest` with a week-long cache header. Visitors' browsers never contact a third party,
and the CSP stays `img-src 'self'`. Club crests are trademarks of their clubs and are shown for identification only.
Refresh them with `python -m app.cli ingest-logos` (it also runs daily).

### AI analysis (OpenAI or Gemini)

With `OPENAI_API_KEYS` and/or `GEMINI_API_KEYS` set (one or more comma-separated keys each), each upcoming
match gets an **AI analysis** card on its Summary tab. Providers are tried in `AI_PROVIDERS` order
(default `openai,gemini`): one without keys is skipped, and one whose keys are all rate-limited or out of
quota hands the request to the next. The model receives the platform's own evidence (model probabilities, expected goals,
the explanation list, form, table, head-to-head). It also searches the web (OpenAI's web search tool or Gemini's Google Search grounding) to look for things
the model cannot see: injuries, expected lineups, manager changes, motivation, congestion and weather. It
returns a structured write-up: summary, key factors, team news labelled confirmed/reported/rumour, risks,
whether the news changes the model's picture, and its own 1X2 view. The sources it cites are listed.

- **Key rotation:** requests start at the next key in round-robin order. A key that gets a 429 is skipped
  for the server-suggested delay (60 s by default, or 1 h when the daily quota is exhausted). An invalid or
  forbidden key is skipped for 6 h, and a 5xx or network error for 30 s. An OpenAI key out of billing quota
  is skipped for 1 h. Keys go only in request headers and are never logged. `/system/health` and Settings show each key's status by slot number.
- **Model fallback:** `OPENAI_MODELS` and `GEMINI_MODELS` are tried in order, and a model the account cannot
  use (404, or no web search support on OpenAI) falls through to the next.
- **When it runs:** on demand from the match page (signed-in users), from `python -m app.cli ai-analysis
  [--fixtures ID ...]` or the admin "AI analysis" button, and on a schedule for fixtures within
  `GEMINI_AUTO_HOURS`, at most `GEMINI_AUTO_MAX_PER_RUN` per run. A fixture is re-analysed once its
  analysis is older than `GEMINI_REFRESH_HOURS` or lineups become confirmed. An analysis of an unchanged
  prediction snapshot is reused instead of spending quota.
- **Advisory only:** the AI view never changes probabilities, selections or reliability. An LLM with web
  search cannot be walk-forward backtested, because the search would see the results. The AI view is
  stored in `ai_analyses` so it can be scored against outcomes going forward. Analysis is refused after
  kickoff.

The keyless source alone runs the full pipeline. The keyed adapters are written against each
provider's documented v4/v3 response formats and are unit-tested with sample payloads. They have
**not** been exercised against the live keyed APIs in this environment, because no keys were available.

## Quick start (Docker)

```bash
cp .env.example .env            # set JWT_SECRET, optionally provider keys and BOOTSTRAP_ADMIN_*
docker compose up --build       # db, redis, migrate, api, worker, scheduler, frontend
docker compose exec api python -m app.cli ingest-history --seasons 5
docker compose exec api python -m app.cli backtest --competitions ENG-1 GER-1 ESP-1 ITA-1 FRA-1 ENG-2 \
    --from 2023-08-01 --to $(date +%F) --deploy
docker compose exec api python -m app.cli ingest-upcoming
docker compose exec api python -m app.cli predict
```

Frontend: http://localhost:5173 · API docs (OpenAPI): http://localhost:8000/api/docs

After that the scheduler runs the cycle on its own: fixtures, then odds, then settlement, then predictions every `ODDS_REFRESH_MINUTES`.
Team news runs every `LINEUP_CHECK_MINUTES`, and history refreshes daily.

## Quick start (without Docker)

```bash
# backend (needs PostgreSQL + optionally Redis)
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp ../.env.example .env   # set DATABASE_URL, TASK_MODE=inline
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli create-admin you@example.com
.venv/bin/python -m app.cli ingest-history --seasons 5
.venv/bin/python -m app.cli backtest --competitions ENG-1 --from 2023-08-01 --to 2026-10-25 --deploy
.venv/bin/python -m app.cli ingest-upcoming && .venv/bin/python -m app.cli predict
.venv/bin/python -m app.cli ingest-logos   # club crests (rate-limited: ~10 min for 160 teams)
.venv/bin/uvicorn app.main:app --reload

# frontend (Node ≥ 18)
cd frontend && npm install && npm run dev      # proxies /api to :8000
```

## Tests

```bash
cd backend && .venv/bin/python -m pytest                       # SQLite
TEST_DATABASE_URL=postgresql+psycopg://user@host/footy_test \
  .venv/bin/python -m pytest                                    # PostgreSQL (runs migrations, trigger test)
cd frontend && npm test && npm run build
```

The tests cover: odds/overround/Shin/EV maths, score-matrix markets (1X2 sums, totals, BTTS, AH quarter
lines, DNB), Dixon-Coles parameter recovery and cutoff handling, Elo, time-correct features, calibration
test, decision rules, provider parsing, HTTP retries and key redaction, idempotent ingestion, team
identity, kickoff/result conflicts, postponement handling, leakage guards (backtest refit spy, odds observed
after kickoff), immutability, settlement including disputed results, API validation, auth roles, rate
limiting, stake limits, and frontend loading, empty and error states.

## API

Versioned under `/api/v1` and documented at `/api/docs`. Main endpoints:
`GET /fixtures`, `/fixtures/{id}`, `/fixtures/{id}/analysis`, `/fixtures/{id}/predictions`, `/fixtures/{id}/lineups`,
`/fixtures/{id}/odds`, `/teams`, `/teams/{id}/statistics`, `/predictions`, `/predictions/{id}`,
`/performance/summary`, `/performance/markets`, `/models`, `/backtests`, `/data-quality`, `/system/health`,
`/settings`; admin: `POST /backtests`, `PUT /settings`, `POST /admin/refresh-fixture/{id}`, `POST /admin/ingest`,
`POST /admin/models/{id}/deploy`, `GET /admin/jobs`, `GET /admin/audit`; auth: `POST /auth/login`, `GET /auth/me`;
stake tracking: `POST/GET /stakes`.

See [docs/OPERATIONS.md](docs/OPERATIONS.md) for production deployment, backups, monitoring and security.

## Feature status

**Fully functional with no keys:** real ingestion of history and upcoming fixtures with odds for 18 supported
leagues; Dixon-Coles, Elo, the logistic model and market model; the ensemble; intervals; reliability;
no-bet logic; explanations; immutable snapshots with change tracking; walk-forward backtests with
CLV, a calibration test, a model registry and deployment; settlement; all six UI pages; auth/roles; rate
limiting; audit log; stake tracking with limits.

**Needs credentials:** authoritative kickoff/status updates (football-data.org); intraday odds refreshes from
many bookmakers (The Odds API); injuries, suspensions and confirmed lineups, and the before/after lineup
comparison (API-Football).

**Not implemented / limitations:**
- No numeric adjustment for absences or lineups. There is no validated player-impact data, so these only reduce reliability.
- Motivation, weather, referee, travel and tactics are not modelled. League position is shown as context.
- Half-time, corners and cards markets are disabled: there is no validated model.
- Promoted teams have little in-league history. Ridge shrinkage plus the Elo entry offset are the only priors, and their reliability is penalised.
- News ingestion: the table exists, but no news provider is integrated, because there is no licensed source with an API.
- Frontend live updates use 60s polling, not push.
- The pre-match odds timestamp for history is approximate (kickoff − 24h), because the provider does not publish it.

## Responsible use

Outputs are statistical estimates with uncertainty. Expected value is an estimate and is not guaranteed.
Performance pages include every losing selection. Betting notifications are opt-in. Stake limits never
escalate automatically. Help: https://www.begambleaware.org
