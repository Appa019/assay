from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from sqlmodel import Session, select

from app.config import settings
from app.models.asset import Asset, AssetClass
from app.schemas.asset import (
    AllocationBreakdown,
    AssetCreate,
    AssetRead,
    AssetUpdate,
    PortfolioSummary,
    SaleResult,
)

logger = structlog.get_logger()


def list_assets(session: Session) -> list[Asset]:
    statement = select(Asset).order_by(Asset.asset_class, Asset.ticker)
    return list(session.exec(statement).all())


def get_asset(session: Session, asset_id: UUID) -> Asset:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise LookupError(f"Asset {asset_id} not found")
    return asset


def create_asset(session: Session, payload: AssetCreate) -> Asset:
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


def sell_asset(session: Session, asset_id: UUID) -> SaleResult:
    asset = get_asset(session, asset_id)
    price = asset.current_price if asset.current_price is not None else asset.avg_price
    sale_value = asset.quantity * price

    result = SaleResult(
        ticker=asset.ticker,
        quantity=asset.quantity,
        price=price,
        sale_value=sale_value,
        asset_class=asset.asset_class,
        message=f"{asset.ticker} vendido por R$ {sale_value:,.2f}",
    )

    session.delete(asset)
    session.commit()
    logger.info("asset_sold", ticker=asset.ticker, value=str(sale_value))
    return result


def _calculate_allocation(assets: list[Asset]) -> AllocationBreakdown:
    buckets = {
        AssetClass.FIXED_INCOME: Decimal("0"),
        AssetClass.STOCKS: Decimal("0"),
        AssetClass.CRYPTO: Decimal("0"),
    }
    for asset in assets:
        price = asset.current_price if asset.current_price is not None else asset.avg_price
        buckets[asset.asset_class] += asset.quantity * price

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
    asset_reads = [AssetRead.model_validate(a, from_attributes=True) for a in assets]
    return PortfolioSummary(
        total_value=allocation.total_value,
        allocation=allocation,
        target_allocation=target,
        deviation=deviation,
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
            }
        )
    return rows
