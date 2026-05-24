"""Detect per-lot 30-day maturity milestones (idempotent state).

When a stock/crypto LOT crosses ``min_holding_days`` since its entry it becomes
sellable, which fires a committee maturity review. Contributions are ad-hoc
(no fixed cycle), so there is NO scheduled "time to invest" nag — the recurring
touchpoint is the weekly review.

State is persisted so a milestone is never handled twice. Keys are only marked
done AFTER the action succeeds, so a failed run is retried next day.
"""

import json
from datetime import date
from pathlib import Path
from typing import Any

import structlog
from sqlmodel import Session, select

from app.config import settings
from app.models.asset import Asset, AssetClass

logger = structlog.get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE_PATH = _PROJECT_ROOT / "storage" / "notifications_state.json"


def _load_state() -> dict[str, Any]:
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("notifications_state_corrupt_reset")
    return {"asset_unlocks": []}


def _save_state(state: dict[str, Any]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _lot_key(asset: Asset) -> str:
    return f"{asset.id}:{asset.entry_date.isoformat()}"


def _row(asset: Asset, days: int) -> dict[str, Any]:
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
        "entry_date": asset.entry_date.isoformat(),
    }


def pending_maturities(
    session: Session, *, today: date | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """Lots that just crossed the lock and were never handled. (rows, keys)."""
    today = today or date.today()
    min_days = settings.min_holding_days
    done = set(_load_state().get("asset_unlocks", []))
    rows: list[dict[str, Any]] = []
    keys: list[str] = []
    for asset in session.exec(select(Asset).order_by(Asset.entry_date)).all():
        # CDB / fixed income has daily liquidity — it never "unlocks", skip it.
        if asset.asset_class == AssetClass.FIXED_INCOME:
            continue
        days = (today - asset.entry_date).days
        if days < min_days:
            continue
        key = _lot_key(asset)
        if key in done:
            continue
        rows.append(_row(asset, days))
        keys.append(key)
    return rows, keys


def mark_maturities(keys: list[str]) -> None:
    state = _load_state()
    existing = set(state.get("asset_unlocks", []))
    existing.update(keys)
    state["asset_unlocks"] = sorted(existing)
    _save_state(state)
