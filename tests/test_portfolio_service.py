from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from app.config import settings
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


def test_partial_sell_keeps_the_rest_of_the_lot(session: Session, stock_unlocked: Asset) -> None:
    """Selling part of a lot books P&L on the sold slice only; the remainder
    keeps its entry_date and avg_price (same 30d clock, same cost basis)."""
    original_entry = stock_unlocked.entry_date
    result = portfolio_service.sell_asset(
        session, stock_unlocked.id, price=Decimal("70.00"), quantity=Decimal("20")
    )
    assert result.quantity == Decimal("20")
    assert result.sale_value == Decimal("1400.00")  # 20 × 70

    remaining = session.get(Asset, stock_unlocked.id)
    assert remaining is not None
    assert remaining.quantity == Decimal("30")
    assert remaining.avg_price == Decimal("60.00")
    assert remaining.entry_date == original_entry

    sell = session.exec(select(Trade).where(Trade.side == TradeSide.SELL)).one()
    assert sell.quantity == Decimal("20")
    assert sell.price == Decimal("70.00")
    assert sell.realized_pnl_brl == Decimal("200.00")  # 20 × (70 − 60)


def test_sell_uses_real_execution_price_over_marked(
    session: Session, stock_unlocked: Asset
) -> None:
    """Regression: the endpoint used to silently ignore the caller's price and
    book P&L at the stale marked price."""
    result = portfolio_service.sell_asset(session, stock_unlocked.id, price=Decimal("64.50"))
    assert result.price == Decimal("64.50")
    sell = session.exec(select(Trade).where(Trade.side == TradeSide.SELL)).one()
    assert sell.realized_pnl_brl == Decimal("225.00")  # 50 × (64.50 − 60)


def test_sell_rejects_quantity_above_lot(session: Session, stock_unlocked: Asset) -> None:
    with pytest.raises(ValueError):
        portfolio_service.sell_asset(session, stock_unlocked.id, quantity=Decimal("999"))
    assert session.get(Asset, stock_unlocked.id) is not None


def test_cdb_sells_anytime(session: Session, cdb: Asset) -> None:
    result = portfolio_service.sell_asset(session, cdb.id)
    assert result.ticker == "CDB-ITAU"
    assert session.get(Asset, cdb.id) is None


def test_sell_lock_days_left(stock_locked: Asset, stock_unlocked: Asset, cdb: Asset) -> None:
    assert portfolio_service.sell_lock_days_left(stock_locked) == 25
    assert portfolio_service.sell_lock_days_left(stock_unlocked) == 0
    assert portfolio_service.sell_lock_days_left(cdb) == 0  # daily liquidity


def test_holding_lock_is_per_class(
    crypto_locked: Asset, crypto_unlocked: Asset, cdb: Asset
) -> None:
    """Crypto carries the short lock; the 30-day hold is a stock-only rule."""
    assert portfolio_service.holding_lock_days(AssetClass.STOCKS) == settings.min_holding_days
    assert (
        portfolio_service.holding_lock_days(AssetClass.CRYPTO) == settings.min_holding_days_crypto
    )
    assert portfolio_service.holding_lock_days(AssetClass.FIXED_INCOME) == 0
    assert portfolio_service.sell_lock_days_left(crypto_locked) == 2  # 7 − 5
    # 20 days old: free as crypto, would still be locked as a stock.
    assert portfolio_service.sell_lock_days_left(crypto_unlocked) == 0


def test_sell_locked_crypto_lot_raises(session: Session, crypto_locked: Asset) -> None:
    with pytest.raises(portfolio_service.SellLockedError):
        portfolio_service.sell_asset(session, crypto_locked.id)
    assert session.get(Asset, crypto_locked.id) is not None


def test_sell_crypto_lot_past_its_shorter_lock(session: Session, crypto_unlocked: Asset) -> None:
    result = portfolio_service.sell_asset(session, crypto_unlocked.id)
    assert result.sale_value == Decimal("11000.00")
    assert session.get(Asset, crypto_unlocked.id) is None


def test_asset_read_carries_the_lock(crypto_locked: Asset, cdb: Asset) -> None:
    """Clients render the lock from the API instead of re-deriving the rule."""
    crypto = portfolio_service.to_asset_read(crypto_locked)
    assert crypto.lock_days_total == settings.min_holding_days_crypto
    assert crypto.lock_days_left == 2
    fixed = portfolio_service.to_asset_read(cdb)
    assert fixed.lock_days_total == 0 and fixed.lock_days_left == 0


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


def test_delete_undoes_a_fresh_lot_with_its_buy_trade(session: Session) -> None:
    asset = portfolio_service.create_asset(
        session,
        AssetCreate(
            ticker="ITUB4",
            asset_class=AssetClass.STOCKS,
            quantity=Decimal("10"),
            avg_price=Decimal("30"),
        ),
    )
    assert len(session.exec(select(Trade)).all()) == 1
    portfolio_service.delete_asset(session, asset.id)
    assert session.exec(select(Trade)).all() == []


def test_delete_refuses_an_old_lot_so_the_ledger_keeps_it(
    session: Session, stock_unlocked: Asset
) -> None:
    """A41: deleting a held lot left no SELL trade and skipped the lock."""
    stock_unlocked.created_at = datetime.now(UTC) - timedelta(days=2)
    session.add(stock_unlocked)
    session.commit()
    with pytest.raises(portfolio_service.DeleteRefusedError):
        portfolio_service.delete_asset(session, stock_unlocked.id)
    assert session.get(Asset, stock_unlocked.id) is not None
