"""Detect per-lot maturity milestones (idempotent state).

When a stock/crypto LOT crosses its own holding lock (30d for stocks, 7d for
crypto — ``portfolio_service.holding_lock_days``) it becomes sellable, which
fires a committee maturity review. Contributions are ad-hoc
(no fixed cycle), so there is NO scheduled "time to invest" nag — the recurring
touchpoint is the weekly review.

State is persisted so a milestone is never handled twice. Keys are only marked
done AFTER the action succeeds, so a failed run is retried next day.
"""

from datetime import date
from pathlib import Path
from typing import Any

import structlog
from sqlmodel import Session, select

from app.core.json_state import load_json_state, save_json_state
from app.models.asset import Asset, AssetClass
from app.services import portfolio_service

logger = structlog.get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE_PATH = _PROJECT_ROOT / "storage" / "notifications_state.json"


def _load_state() -> dict[str, Any]:
    return load_json_state(_STATE_PATH) or {"asset_unlocks": []}


def _save_state(state: dict[str, Any]) -> None:
    save_json_state(_STATE_PATH, state)


def _lot_key(asset: Asset) -> str:
    return f"{asset.id}:{asset.entry_date.isoformat()}"


def _row(asset: Asset, days: int, lock_days: int) -> dict[str, Any]:
    price = asset.current_price if asset.current_price is not None else asset.avg_price
    return {
        "ticker": asset.ticker,
        "asset_class": str(asset.asset_class),
        "quantity": float(asset.quantity),
        "avg_price": float(asset.avg_price),
        "current_price": float(price) if price is not None else None,
        "total_value": round(float(asset.quantity * price), 2),
        "pnl_pct": (
            round(float((price - asset.avg_price) / asset.avg_price * 100), 2)
            if asset.avg_price > 0
            else None
        ),
        "days_in_portfolio": days,
        "lock_days_total": lock_days,
        "lock_days_left": 0,
        "entry_date": asset.entry_date.isoformat(),
    }


def pending_maturities(
    session: Session, *, today: date | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """Lots that just crossed the lock and were never handled. (rows, keys)."""
    today = today or date.today()
    done = set(_load_state().get("asset_unlocks", []))
    rows: list[dict[str, Any]] = []
    keys: list[str] = []
    for asset in session.exec(select(Asset).order_by(Asset.entry_date)).all():
        # CDB / fixed income has daily liquidity — it never "unlocks", skip it.
        if asset.asset_class == AssetClass.FIXED_INCOME:
            continue
        # Each class has its own lock (stocks 30d, crypto 7d).
        lock_days = portfolio_service.holding_lock_days(asset.asset_class)
        days = (today - asset.entry_date).days
        if days < lock_days:
            continue
        key = _lot_key(asset)
        if key in done:
            continue
        rows.append(_row(asset, days, lock_days))
        keys.append(key)
    return rows, keys


def mark_maturities(keys: list[str]) -> None:
    state = _load_state()
    existing = set(state.get("asset_unlocks", []))
    existing.update(keys)
    state["asset_unlocks"] = sorted(existing)
    _save_state(state)
