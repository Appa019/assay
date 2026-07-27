from decimal import Decimal

import pytest
from sqlmodel import Session, select

from app.models.asset import Asset, AssetClass
from app.models.trade import Trade, TradeSide
from app.schemas.asset import AssetCreate
from app.services import portfolio_service


def test_create_asset_records_buy_trade(session: Session) -> None:
    asset = portfolio_service.create_asset(
        session,
        AssetCreate(
            ticker="weGe3",
            asset_class=AssetClass.STOCKS,
            quantity=Decimal("10"),
            avg_price=Decimal("50.00"),
        ),
    )
    assert asset.ticker == "WEGE3"  # normalized upper
    trades = list(session.exec(select(Trade)).all())
    assert len(trades) == 1
    assert trades[0].side == TradeSide.BUY
    assert trades[0].total_brl == Decimal("500.00")


def test_sell_locked_lot_raises(session: Session, stock_locked: Asset) -> None:
    with pytest.raises(portfolio_service.SellLockedError):
        portfolio_service.sell_asset(session, stock_locked.id)
    # Position untouched, no sell trade recorded.
    assert session.get(Asset, stock_locked.id) is not None
    assert session.exec(select(Trade).where(Trade.side == TradeSide.SELL)).first() is None


def test_sell_unlocked_lot_records_realized_pnl(session: Session, stock_unlocked: Asset) -> None:
    result = portfolio_service.sell_asset(session, stock_unlocked.id)
    assert result.sale_value == Decimal("3300.00")  # 50 × 66
    assert session.get(Asset, stock_unlocked.id) is None
    sell = session.exec(select(Trade).where(Trade.side == TradeSide.SELL)).one()
    assert sell.realized_pnl_brl == Decimal("300.00")  # 50 × (66 − 60)
    assert sell.realized_pnl_pct == 10.0
    assert sell.lot_entry_date == stock_unlocked.entry_date


def test_cdb_sells_anytime(session: Session, cdb: Asset) -> None:
    result = portfolio_service.sell_asset(session, cdb.id)
    assert result.ticker == "CDB-ITAU"
    assert session.get(Asset, cdb.id) is None


def test_sell_lock_days_left(stock_locked: Asset, stock_unlocked: Asset, cdb: Asset) -> None:
    assert portfolio_service.sell_lock_days_left(stock_locked) == 25
    assert portfolio_service.sell_lock_days_left(stock_unlocked) == 0
    assert portfolio_service.sell_lock_days_left(cdb) == 0  # daily liquidity


def test_daily_snapshot_upserts(session: Session, stock_unlocked: Asset) -> None:
    first = portfolio_service.record_daily_snapshot(session)
    assert first.total_value == Decimal("3300.00")
    stock_unlocked.current_price = Decimal("70.00")
    session.add(stock_unlocked)
    session.commit()
    second = portfolio_service.record_daily_snapshot(session)
    assert second.id == first.id  # same calendar day → updated, not duplicated
    assert second.total_value == Decimal("3500.00")
    assert len(portfolio_service.get_portfolio_history(session)) == 1


def test_allocation_percentages(session: Session, stock_unlocked: Asset, cdb: Asset) -> None:
    summary = portfolio_service.get_portfolio_summary(session)
    total = summary.allocation.total_value
    assert total == pytest.approx(3300.0 + 5010.0)
    assert summary.allocation.stocks_pct == pytest.approx(3300.0 / total * 100)
    assert summary.allocation.fixed_income_pct == pytest.approx(5010.0 / total * 100)
