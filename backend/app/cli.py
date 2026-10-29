"""Operations CLI.

    python -m app.cli create-admin admin@example.com
    python -m app.cli ingest-history --competitions ENG-1 GER-1 --seasons 4
    python -m app.cli ingest-upcoming
    python -m app.cli ingest-logos
    python -m app.cli predict
    python -m app.cli ai-analysis [--fixtures 123 456]
    python -m app.cli backtest --competitions ENG-1 --from 2023-08-01 --to 2026-06-30 --deploy
    python -m app.cli backtest --competitions leagues --from 2024-07-01 --to 2026-10-29 --deploy
    python -m app.cli settle
    python -m app.cli update-cycle
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from datetime import date

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.security import hash_password
from app.db.models import Backtest, ModelVersion, User
from app.db.session import session_factory
from app.ingestion.competitions import COMPETITIONS
from app.worker import jobs


def main(argv: list[str] | None = None) -> int:
    configure_logging(get_settings().log_level)
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-admin")
    a.add_argument("email")
    h = sub.add_parser("ingest-history")
    h.add_argument("--competitions", nargs="*")
    h.add_argument("--seasons", type=int)
    lg = sub.add_parser("ingest-logos")
    lg.add_argument("--force", action="store_true")
    sub.add_parser("ingest-upcoming")
    sub.add_parser("refresh-odds")
    sub.add_parser("team-news")
    sub.add_parser("predict")
    ai = sub.add_parser("ai-analysis")
    ai.add_argument("--fixtures", nargs="*", type=int)
    sub.add_parser("settle")
    sub.add_parser("update-cycle")
    b = sub.add_parser("backtest")
    b.add_argument("--competitions", nargs="+", required=True,
                   help='codes, or "leagues" for every tracked league (cups have no historical odds)')
    b.add_argument("--from", dest="date_from", required=True, type=date.fromisoformat)
    b.add_argument("--to", dest="date_to", required=True, type=date.fromisoformat)
    b.add_argument("--step-days", type=int, default=7)
    b.add_argument("--price-source", choices=["best", "avg"], default="best")
    b.add_argument("--deploy", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "create-admin":
        password = getpass.getpass("Password (min 12 chars): ")
        if len(password) < 12:
            print("password too short", file=sys.stderr)
            return 1
        with session_factory()() as db:
            email = args.email.lower()
            user = db.scalar(select(User).where(User.email == email))
            if user:
                user.password_hash, user.role = hash_password(password), "admin"
            else:
                db.add(User(email=email, password_hash=hash_password(password), role="admin"))
            db.commit()
        print(f"admin {email} saved")
        return 0
    if args.cmd == "backtest":
        competitions = [c for code in args.competitions for c in (
            [t for t in get_settings().competitions if COMPETITIONS[t].format == "league"]
            if code == "leagues" else [code])]
        params = {"competitions": competitions, "date_from": args.date_from.isoformat(),
                  "date_to": args.date_to.isoformat(), "step_days": args.step_days,
                  "price_source": args.price_source, "rules": {}, "deploy": args.deploy}
        with session_factory()() as db:
            bt = Backtest(params=params, status="queued", requested_by="cli")
            db.add(bt)
            db.commit()
            bt_id = bt.id
        result = jobs.run_backtest(bt_id)
        with session_factory()() as db:
            bt = db.get(Backtest, bt_id)
            if bt.status != "completed":
                print(json.dumps({"status": bt.status, "error": bt.error}, indent=2))
                return 1
            m = bt.metrics
            if not m.get("matches"):
                print(json.dumps({"backtest_id": bt_id, "error": m.get("message", "no matches evaluated")}, indent=2))
                return 1
            version = db.scalar(select(ModelVersion).where(ModelVersion.backtest_id == bt_id))
            print(json.dumps({"backtest_id": bt_id, **result, "matches": m["matches"],
                              "one_x_two": m["one_x_two"]["comparison_common_subset"],
                              "calibration_ece": m["calibration_ece"], "learned_weights": m["learned_weights"],
                              "validated_markets": m["validated_markets"],
                              "betting": m["betting"]["overall"],
                              "model_version": {"id": version.id, "version": version.version, "status": version.status}
                              if version else None}, indent=2, default=str))
            if args.deploy and (version is None or version.status != "deployed"):
                print("not deployed: too few out-of-sample matches to learn ensemble weights", file=sys.stderr)
                return 1
        return 0

    fn = {"ingest-history": lambda: jobs.ingest_history(args.competitions, args.seasons, force=True),
          "ingest-logos": lambda: jobs.ingest_logos(args.force), "ingest-upcoming": jobs.ingest_upcoming, "refresh-odds": jobs.refresh_odds,
          "team-news": jobs.refresh_team_news, "predict": lambda: jobs.run_predictions("manual"),
          "ai-analysis": lambda: jobs.ai_analysis(args.fixtures),
          "settle": jobs.settle, "update-cycle": jobs.update_cycle}[args.cmd]
    print(json.dumps(fn(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
