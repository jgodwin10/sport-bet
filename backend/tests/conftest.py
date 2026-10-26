"""Test configuration.

Tests run against SQLite by default. Set TEST_DATABASE_URL to a PostgreSQL URL to
run the same suite (plus Postgres-only checks) against a real database.

All team names, results and odds produced by `synthetic_league` are SYNTHETIC
and exist only to exercise the code paths.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

_tmp = tempfile.mkdtemp(prefix="footy-test-")
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["TASK_MODE"] = "inline"
os.environ["JWT_SECRET"] = "test-secret-not-for-production-0123456789"
os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["FOOTBALL_DATA_CO_UK_ENABLED"] = "false"
for key in ("FOOTBALL_DATA_ORG_API_KEY", "THE_ODDS_API_KEY", "API_FOOTBALL_KEY", "BOOTSTRAP_ADMIN_EMAIL",
            "GEMINI_API_KEYS"):
    os.environ.pop(key, None)

from app.db.models import Base  # noqa: E402
from app.db.session import get_engine, session_factory  # noqa: E402
from app.providers.base import NormalizedFixture, NormalizedOdds, ProviderBatch, TeamStats  # noqa: E402

IS_POSTGRES = os.environ["DATABASE_URL"].startswith("postgresql")


@pytest.fixture()
def db():
    engine = get_engine()
    if IS_POSTGRES:
        from alembic import command
        from alembic.config import Config

        cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
        cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    else:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
    session = session_factory()()
    yield session
    session.close()


def make_batch(fixtures: list[NormalizedFixture], provider: str = "football_data_co_uk", trust: int = 70,
               resource: str = "/synthetic.csv", retrieved_at: datetime | None = None) -> ProviderBatch:
    digest = hashlib.sha256(repr([(f.home_name, f.away_name, f.kickoff_utc, f.home_goals, f.status,
                                   len(f.odds)) for f in fixtures]).encode()).hexdigest()
    return ProviderBatch(provider, resource, retrieved_at or datetime.now(timezone.utc), digest, trust, fixtures)


def synthetic_league(start: datetime, seasons: int = 2, teams: int = 10, seed: int = 11,
                     upcoming_after: datetime | None = None, competition: str = "ENG-1") -> list[NormalizedFixture]:
    """SYNTHETIC double round-robin league(s) with Poisson scores and fair-ish odds.

    Matches with kickoff >= `upcoming_after` are emitted as scheduled (no result).
    """
    rng = np.random.default_rng(seed)
    names = [f"Synthetic Town {i:02d}" for i in range(teams)]
    attack = np.linspace(-0.35, 0.35, teams)
    out: list[NormalizedFixture] = []
    for season in range(seasons):
        day = start + timedelta(days=365 * season)  # one season per year so season labels differ
        pairs = [(h, a) for h in range(teams) for a in range(teams) if h != a]
        rng.shuffle(pairs)
        for i, (h, a) in enumerate(pairs):
            kickoff = day + timedelta(days=3 * (i // (teams // 2)), hours=15)
            lam, mu = np.exp(0.15 + 0.2 + attack[h] - attack[a] * 0.6), np.exp(0.15 + attack[a] - attack[h] * 0.6)
            # crude 1X2 "true" probabilities for odds generation
            ph = float(np.clip(0.45 + (attack[h] - attack[a]) * 0.6, 0.1, 0.8))
            pd_ = 0.26
            pa = max(0.05, 1 - ph - pd_)
            odds = []
            future = upcoming_after is not None and kickoff >= upcoming_after
            # Prices must be observable before the prediction time to be used at all
            observed = min(kickoff - timedelta(hours=24), upcoming_after - timedelta(hours=1)) if future \
                else kickoff - timedelta(hours=24)
            for bk in ("avg", "b365", "ps"):
                margin = 1.05 if bk != "ps" else 1.025
                noise = rng.normal(1, 0.02, 3)
                for sel, p, n in (("home", ph, noise[0]), ("draw", pd_, noise[1]), ("away", pa, noise[2])):
                    odds.append(NormalizedOdds(bk, bk.upper(), "1x2", sel, round(1 / (p * margin) * n, 2),
                                               "pre_match", observed))
                    if not future:
                        odds.append(NormalizedOdds(bk, bk.upper(), "1x2", sel, round(1 / (p * margin), 2),
                                                   "closing", kickoff))
                odds.append(NormalizedOdds(bk, bk.upper(), "totals", "over", 1.9, "pre_match", observed, 2.5))
                odds.append(NormalizedOdds(bk, bk.upper(), "totals", "under", 1.95, "pre_match", observed, 2.5))
            fx = NormalizedFixture(
                provider="football_data_co_uk", provider_fixture_id=None, competition_code=competition,
                season_label=f"{kickoff.year if kickoff.month >= 7 else kickoff.year - 1}-"
                             f"{(kickoff.year if kickoff.month >= 7 else kickoff.year - 1) + 1}",
                home_name=names[h], away_name=names[a], kickoff_utc=kickoff,
                status="scheduled" if future else "finished", odds=odds,
            )
            if not future:
                fx.home_goals, fx.away_goals = int(rng.poisson(lam)), int(rng.poisson(mu))
                fx.home_stats = TeamStats(shots=12, shots_on_target=int(rng.poisson(4.5)), xg=round(lam, 2))
                fx.away_stats = TeamStats(shots=10, shots_on_target=int(rng.poisson(3.8)), xg=round(mu, 2))
            out.append(fx)
    return out
