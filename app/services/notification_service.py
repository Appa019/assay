"""Detect 30-day milestones (idempotent state) for the daily cadence job.

Two triggers:
- A purchase LOT crosses ``min_holding_days`` since its entry → now sellable,
  fires a committee maturity review.
- The contribution cadence is due → a Telegram nudge to make a new aporte.

State is persisted so a milestone is never handled twice. Keys are only marked
done AFTER the action succeeds, so a failed run is retried next day.
"""

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import structlog
from sqlmodel import Session, select

from app.config import settings
from app.models.asset import Asset, AssetClass
from app.models.contribution import Contribution
from app.services import telegram_service

logger = structlog.get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE_PATH = _PROJECT_ROOT / "storage" / "notifications_state.json"


def _load_state() -> dict[str, Any]:
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("notifications_state_corrupt_reset")
    return {"asset_unlocks": [], "contribution_due": []}


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


def notify_contribution_due(session: Session, *, today: date | None = None) -> str | None:
    """Send the cadence nudge if a new aporte is due. Returns the message sent."""
    today = today or date.today()
    interval = settings.contribution_interval_days
    state = _load_state()
    dues = set(state.get("contribution_due", []))

    last = session.exec(
        select(Contribution).order_by(Contribution.created_at.desc()).limit(1)
    ).first()
    next_date = (last.created_at.date() + timedelta(days=interval)) if last else today
    if next_date > today or next_date.isoformat() in dues:
        return None

    last_str = last.created_at.date().isoformat() if last else "—"
    msg = (
        f"📅 Já se passaram {interval} dias desde o último aporte ({last_str}). "
        "Hora de um novo aporte — me mande o valor com /aporte <valor> ou use o app, "
        "que eu rodo o comitê inteiro e te devolvo onde investir e quanto."
    )
    if telegram_service.notify(msg):
        dues.add(next_date.isoformat())
        state["contribution_due"] = sorted(dues)
        _save_state(state)
        return msg
    return None
