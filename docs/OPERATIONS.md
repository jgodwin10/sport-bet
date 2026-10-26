# Operations guide

## Production deployment

1. **Secrets.** Set `ENVIRONMENT=production` and a random `JWT_SECRET` (≥ 48 bytes). Keep provider keys in
   a secret manager or in environment variables. Never put them in the database or the frontend build. The
   frontend only calls `/api` on its own origin.
2. **Database.** Use managed PostgreSQL 16 with TLS and a dedicated least-privilege role. Run
   `alembic upgrade head` as a one-off release step (the `migrate` service in compose).
3. **Processes.** Run 2+ `api` replicas behind TLS (nginx or a load balancer), one or more `worker`s, and
   **exactly one** `scheduler` (Celery beat). Redis backs the queue, the shared rate limiter and the
   single-flight job locks.
4. **CORS.** Set `CORS_ORIGINS` to the real frontend origin. The bundled nginx config sets a CSP and other
   security headers. The API adds HSTS in production.
5. **Admin.** Run `python -m app.cli create-admin admin@yourdomain` once. Viewers can read. Only admins can
   change settings, trigger ingestion, run backtests or deploy models. Every admin action goes to `audit_logs`.

## Scheduling & provider budgets

| Job | Default | Provider cost |
|---|---|---|
| update cycle (fixtures → odds → settle → predict) | 60 min | The Odds API: competitions × 2 markets × regions credits per run; size `ODDS_REFRESH_MINUTES` to your plan (free 500/month ≈ one EPL refresh/day) |
| team news (injuries; lineups within 90 min of kickoff) | 15 min | API-Football: ~2 calls per fixture in the window; free plan is 100/day |
| history | daily | football-data.co.uk: one CSV per competition per season (cached, deduplicated by payload hash) |

Jobs are idempotent: each run records an `ingestion_jobs` row under a time-bucketed key, identical payloads
are skipped by hash, and Redis locks prevent overlapping runs. Provider failures retry with exponential
backoff. A failing optional provider never blocks the others, and the last good snapshot stays visible
with its age.

## Model lifecycle

1. Ingest ≥ 3 seasons of history per competition.
2. `POST /backtests` (or `cli backtest ... --deploy`) runs a walk-forward evaluation, learns ensemble
   weights from out-of-sample predictions only, and registers a `model_versions` row.
3. Deploy a version only after reviewing: log loss vs market, calibration tests, ROI CI, CLV and sample
   size. A version applies only to competitions it was backtested on. Other competitions use unvalidated
   equal weights, and nothing in them can qualify as a recommendation.
4. Re-run monthly, and after any model code change.

## Monitoring

- `GET /api/v1/system/health`: DB/Redis status, provider configuration, recent jobs, last stored result.
- Structured JSON logs on stdout, with request IDs, durations and job errors. Ship them to your log stack
  and alert on `level=ERROR` and on failed `ingestion_jobs`.
- `GET /api/v1/data-quality`: unresolved conflicts (team mappings, kickoff/result disagreements) and past
  fixtures without results.

## Backups & recovery

- Nightly `pg_dump -Fc footy > footy-$(date +%F).dump`, plus WAL archiving or managed PITR. Keep 30 days.
  The tables that matter for reproducibility are `predictions*`, `selections`, `odds_snapshots`,
  `model_versions`, `backtests` and `source_records`.
- Restore: `createdb footy && pg_restore -d footy footy-YYYY-MM-DD.dump`, then `alembic upgrade head`.
- Redis holds only queue/cache/rate-limit state. It needs no backup.
- Test a restore quarterly.

## Retention

Odds snapshots grow fastest: about 60 rows per match for history, more with The Odds API. Predictions and odds
are protected by an immutability trigger. To archive, a DBA can export old partitions/rows and remove
them inside a maintenance transaction that temporarily disables `odds_snapshots_immutable`. Never
archive odds referenced by unsettled selections.

## Security checklist

- [x] Passwords hashed with bcrypt (cost 12); JWT HS256 with expiry
- [x] Role-based authorisation on admin endpoints
- [x] Input validation on every request (Pydantic); predictable 4xx errors; 500s never leak internals
- [x] ORM-parameterised SQL only
- [x] Per-IP rate limiting (Redis-backed)
- [x] Security headers and CSP
- [x] Provider errors never echo request params (API keys)
- [ ] Put the API behind TLS; consider a WAF; rotate `JWT_SECRET` to invalidate sessions
