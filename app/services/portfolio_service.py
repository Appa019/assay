from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from sqlmodel import Session, select

from app.config import settings
from app.models.asset import Asset, AssetClass
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.trade import Trade, TradeSide
from app.schemas.asset import (
    AllocationBreakdown,
    AssetCreate,
    AssetRead,
    AssetUpdate,
    PortfolioSummary,
    SaleResult,
)

logger = structlog.get_logger()


class SellLockedError(RuntimeError):
    """The lot is still inside the per-lot holding lock (stocks/crypto only)."""


def list_assets(session: Session) -> list[Asset]:
    statement = select(Asset).order_by(Asset.asset_class, Asset.ticker)
    return list(session.exec(statement).all())


def get_asset(session: Session, asset_id: UUID) -> Asset:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise LookupError(f"Asset {asset_id} not found")
    return asset


def build_asset_with_trade(session: Session, payload: AssetCreate) -> Asset:
    """Stage a new lot + its BUY trade on the session WITHOUT committing.

    Callers that compose this with other writes (e.g. order execution) commit
    once at the end, so a crash can never leave the lot persisted while the
    composing operation is still pending.
    """
    asset = Asset(
        ticker=payload.ticker,
        name=payload.name,
        asset_class=payload.asset_class,
        quantity=payload.quantity,
        avg_price=payload.avg_price,
        current_price=payload.current_price or payload.avg_price,
        entry_date=payload.entry_date or date.today(),
    )
    session.add(asset)
    session.add(
        Trade(
            asset_id=asset.id,
            ticker=asset.ticker,
            name=asset.name,
            asset_class=asset.asset_class,
            side=TradeSide.BUY,
            quantity=asset.quantity,
            price=asset.avg_price,
            total_brl=(asset.quantity * asset.avg_price).quantize(Decimal("0.01")),
            lot_entry_date=asset.entry_date,
        )
    )
    return asset


def create_asset(session: Session, payload: AssetCreate) -> Asset:
    asset = build_asset_with_trade(session, payload)
    session.commit()
    session.refresh(asset)
    logger.info("asset_created", ticker=asset.ticker, asset_class=str(asset.asset_class))
    return asset


def update_asset(session: Session, asset_id: UUID, payload: AssetUpdate) -> Asset:
    asset = get_asset(session, asset_id)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(asset, key, value)
    asset.updated_at = datetime.now(UTC)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def delete_asset(session: Session, asset_id: UUID) -> Asset:
    asset = get_asset(session, asset_id)
    session.delete(asset)
    session.commit()
    logger.info("asset_deleted", ticker=asset.ticker)
    return asset


def holding_lock_days(asset_class: AssetClass | str) -> int:
    """How many days a lot of this class must be held before it can be sold.

    The lock is PER CLASS and this is its single source of truth — every
    surface (API, reviews, prompts, front-end) reads the rule from here.
    Stocks carry the client's 30-day compliance hold; crypto has no such legal
    requirement and uses a shorter one; CDB has daily liquidity and never
    locks. An unknown class falls back to the strictest lock on purpose.
    """
    if asset_class == AssetClass.FIXED_INCOME:
        return 0
    if asset_class == AssetClass.CRYPTO:
        return settings.min_holding_days_crypto
    return settings.min_holding_days


def sell_lock_days_left(asset: Asset, *, today: date | None = None) -> int:
    """Days until this lot unlocks. 0 = sellable. CDB never locks."""
    lock_days = holding_lock_days(asset.asset_class)
    if lock_days <= 0:
        return 0
    today = today or date.today()
    held = (today - asset.entry_date).days
    return max(0, lock_days - held)


def to_asset_read(asset: Asset, *, today: date | None = None) -> AssetRead:
    """Serialize a lot WITH its lock state, so no client re-implements the rule."""
    read = AssetRead.model_validate(asset, from_attributes=True)
    read.lock_days_total = holding_lock_days(asset.asset_class)
    read.lock_days_left = sell_lock_days_left(asset, today=today)
    return read


def sell_asset(
    session: Session,
    asset_id: UUID,
    *,
    price: Decimal | None = None,
    quantity: Decimal | None = None,
) -> SaleResult:
    """Sell a lot (whole or partial), enforcing the per-lot holding lock here.

    The lock lives HERE (not in each caller) so the API and any
    future surface all obey the same rule. ``price`` is the REAL execution
    price when the caller knows it; without it the mark-to-market price is
    used. ``quantity`` sells part of the lot (the remainder keeps its
    entry_date and avg_price); omitted, the whole lot goes. Records a sell
    Trade with realized P&L — the ledger is the permanent history.
    """
    asset = get_asset(session, asset_id)
    days_left = sell_lock_days_left(asset)
    if days_left > 0:
        raise SellLockedError(
            f"{asset.ticker} ainda travado: lote de {asset.entry_date.isoformat()} "
            f"libera em {days_left} dia(s) (trava de "
            f"{holding_lock_days(asset.asset_class)}d por lote para "
            f"{'crypto' if asset.asset_class == AssetClass.CRYPTO else 'ações'})."
        )

    if price is None:
        price = asset.current_price if asset.current_price is not None else asset.avg_price
    sell_qty = asset.quantity if quantity is None else quantity
    if sell_qty <= 0 or sell_qty > asset.quantity:
        raise ValueError(
            f"Quantidade inválida: {sell_qty} (o lote {asset.ticker} tem {asset.quantity})."
        )
    partial = sell_qty < asset.quantity

    sale_value = sell_qty * price
    cost_basis = sell_qty * asset.avg_price
    realized_brl = (sale_value - cost_basis).quantize(Decimal("0.01"))
    realized_pct = (
        float((price - asset.avg_price) / asset.avg_price * 100) if asset.avg_price > 0 else None
    )

    session.add(
        Trade(
            asset_id=asset.id,
            ticker=asset.ticker,
            name=asset.name,
            asset_class=asset.asset_class,
            side=TradeSide.SELL,
            quantity=sell_qty,
            price=price,
            total_brl=sale_value.quantize(Decimal("0.01")),
            realized_pnl_brl=realized_brl,
            realized_pnl_pct=round(realized_pct, 2) if realized_pct is not None else None,
            lot_entry_date=asset.entry_date,
        )
    )

    remainder_note = ""
    if partial:
        asset.quantity = asset.quantity - sell_qty
        asset.updated_at = datetime.now(UTC)
        session.add(asset)
        remainder_note = f" — restam {asset.quantity} no lote"
    else:
        session.delete(asset)

    result = SaleResult(
        ticker=asset.ticker,
        quantity=sell_qty,
        price=price,
        sale_value=sale_value,
        asset_class=asset.asset_class,
        message=(
            f"{asset.ticker} vendido por R$ {sale_value:,.2f} "
            f"(P&L realizado R$ {realized_brl:,.2f}){remainder_note}"
        ),
    )

    session.commit()
    logger.info(
        "asset_sold",
        ticker=result.ticker,
        value=str(sale_value),
        realized=str(realized_brl),
        partial=partial,
    )
    return result


def list_trades(session: Session, *, limit: int = 200) -> list[Trade]:
    statement = select(Trade).order_by(Trade.executed_at.desc()).limit(limit)
    return list(session.exec(statement).all())


def _class_totals(assets: list[Asset]) -> dict[AssetClass, Decimal]:
    buckets = {
        AssetClass.FIXED_INCOME: Decimal("0"),
        AssetClass.STOCKS: Decimal("0"),
        AssetClass.CRYPTO: Decimal("0"),
    }
    for asset in assets:
        price = asset.current_price if asset.current_price is not None else asset.avg_price
        buckets[asset.asset_class] += asset.quantity * price
    return buckets


def _calculate_allocation(assets: list[Asset]) -> AllocationBreakdown:
    buckets = _class_totals(assets)
    total = sum(buckets.values(), Decimal("0"))

    def pct(value: Decimal) -> float:
        if total == 0:
            return 0.0
        return float(value / total * 100)

    return AllocationBreakdown(
        total_value=total,
        fixed_income=buckets[AssetClass.FIXED_INCOME],
        stocks=buckets[AssetClass.STOCKS],
        crypto=buckets[AssetClass.CRYPTO],
        fixed_income_pct=pct(buckets[AssetClass.FIXED_INCOME]),
        stocks_pct=pct(buckets[AssetClass.STOCKS]),
        crypto_pct=pct(buckets[AssetClass.CRYPTO]),
    )


def _target_allocation() -> dict[str, float]:
    return {
        "fixed_income": settings.target_fixed_income * 100,
        "stocks": settings.target_stocks * 100,
        "crypto": settings.target_crypto * 100,
    }


def get_portfolio_summary(session: Session) -> PortfolioSummary:
    assets = list_assets(session)
    allocation = _calculate_allocation(assets)
    target = _target_allocation()
    deviation = {
        "fixed_income": allocation.fixed_income_pct - target["fixed_income"],
        "stocks": allocation.stocks_pct - target["stocks"],
        "crypto": allocation.crypto_pct - target["crypto"],
    }
    asset_reads = [to_asset_read(a) for a in assets]
    return PortfolioSummary(
        total_value=allocation.total_value,
        allocation=allocation,
        target_allocation=target,
        deviation=deviation,
        holding_lock_days={
            "fixed_income": holding_lock_days(AssetClass.FIXED_INCOME),
            "stocks": holding_lock_days(AssetClass.STOCKS),
            "crypto": holding_lock_days(AssetClass.CRYPTO),
        },
        assets=asset_reads,
    )


def build_portfolio_snapshot(session: Session) -> list[dict[str, Any]]:
    """Snapshot of every asset, normalized for prompt injection."""
    assets = list_assets(session)
    today = date.today()
    rows: list[dict[str, Any]] = []
    for asset in assets:
        price = asset.current_price if asset.current_price is not None else asset.avg_price
        total_value = float(asset.quantity * price)
        pnl_pct: float | None = None
        if asset.avg_price > 0:
            pnl_pct = float((price - asset.avg_price) / asset.avg_price * 100)
        rows.append(
            {
                "ticker": asset.ticker,
                "name": asset.name,
                "asset_class": str(asset.asset_class),
                "quantity": float(asset.quantity),
                "avg_price": float(asset.avg_price),
                "current_price": float(price) if price is not None else None,
                "total_value": round(total_value, 2),
                "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
                "days_in_portfolio": (today - asset.entry_date).days,
                "lock_days_total": holding_lock_days(asset.asset_class),
                "lock_days_left": sell_lock_days_left(asset, today=today),
                "entry_date": asset.entry_date.isoformat(),
                "thesis": asset.thesis,
                "target_price": float(asset.target_price) if asset.target_price else None,
                "stop_price": float(asset.stop_price) if asset.stop_price else None,
            }
        )
    return rows


def record_daily_snapshot(session: Session) -> PortfolioSnapshot:
    """Upsert today's portfolio valuation (idempotent — safe to cron daily)."""
    assets = list_assets(session)
    buckets = _class_totals(assets)
    total = sum(buckets.values(), Decimal("0"))
    today = date.today()
    existing = session.exec(
        select(PortfolioSnapshot).where(PortfolioSnapshot.snapshot_date == today)
    ).first()
    snapshot = existing or PortfolioSnapshot(snapshot_date=today)
    snapshot.total_value = total.quantize(Decimal("0.01"))
    snapshot.fixed_income = buckets[AssetClass.FIXED_INCOME].quantize(Decimal("0.01"))
    snapshot.stocks = buckets[AssetClass.STOCKS].quantize(Decimal("0.01"))
    snapshot.crypto = buckets[AssetClass.CRYPTO].quantize(Decimal("0.01"))
    snapshot.assets = build_portfolio_snapshot(session)
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    logger.info("portfolio_snapshot_recorded", date=today.isoformat())
    return snapshot


def get_portfolio_history(session: Session, *, days: int = 365) -> list[PortfolioSnapshot]:
    statement = (
        select(PortfolioSnapshot)
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .limit(max(1, min(days, 3650)))
    )
    rows = list(session.exec(statement).all())
    rows.reverse()  # chronological for charting
    return rows
