"""Admin-editable application settings stored in `app_settings` (never secrets)."""

from __future__ import annotations

from dataclasses import asdict, fields

from sqlalchemy.orm import Session

from app.db.models import AppSetting
from app.engine.decision import SelectionRules

RULES_KEY = "selection_rules"
OPTIONS_KEY = "app_options"

DEFAULT_OPTIONS: dict = {
    "preferred_competitions": [],
    "enabled_markets": ["1x2", "totals_2.5", "asian_handicap"],
    "timezone": "UTC",
    "notifications_enabled": False,  # betting-oriented notifications are opt-in
    "stake_tracking_enabled": False,
    "max_stake_per_selection": 1.0,
    "max_daily_stake": 5.0,
}


def get_rules(db: Session) -> SelectionRules:
    row = db.get(AppSetting, RULES_KEY)
    rules = SelectionRules()
    if row:
        valid = {f.name for f in fields(SelectionRules)}
        for k, v in row.value.items():
            if k in valid:
                setattr(rules, k, v)
    return rules


def set_rules(db: Session, values: dict, actor: str) -> SelectionRules:
    rules = get_rules(db)
    for k, v in values.items():
        setattr(rules, k, v)
    _put(db, RULES_KEY, asdict(rules), actor)
    return rules


def get_app_options(db: Session) -> dict:
    row = db.get(AppSetting, OPTIONS_KEY)
    return {**DEFAULT_OPTIONS, **(row.value if row else {})}


def set_app_options(db: Session, values: dict, actor: str) -> dict:
    merged = {**get_app_options(db), **values}
    _put(db, OPTIONS_KEY, merged, actor)
    return merged


def _put(db: Session, key: str, value: dict, actor: str) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value, updated_by=actor))
    else:
        row.value = value
        row.updated_by = actor
    db.commit()
