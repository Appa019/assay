from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlmodel import Session

from app.models.asset import Asset, AssetClass
from app.services import notification_service


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(notification_service, "_STATE_PATH", tmp_path / "state.json")


def _asset(session: Session, *, ticker: str, asset_class: AssetClass, days_ago: int) -> Asset:
    asset = Asset(
        ticker=ticker,
        asset_class=asset_class,
        quantity=Decimal("1"),
        avg_price=Decimal("100"),
        current_price=Decimal("110"),
        entry_date=date.today() - timedelta(days=days_ago),
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def test_pending_maturities_excludes_cdb_and_locked_lots(session: Session) -> None:
    """D6: CDB has daily liquidity and never 'unlocks' — it must not summon a
    maturity review no matter how old the lot is."""
    _asset(session, ticker="CDB-ITAU", asset_class=AssetClass.FIXED_INCOME, days_ago=200)
    _asset(session, ticker="PETR4", asset_class=AssetClass.STOCKS, days_ago=5)
    matured = _asset(session, ticker="VALE3", asset_class=AssetClass.STOCKS, days_ago=35)

    rows, keys = notification_service.pending_maturities(session)
    assert [r["ticker"] for r in rows] == ["VALE3"]
    assert keys == [notification_service._lot_key(matured)]


def test_mark_maturities_makes_the_milestone_idempotent(session: Session) -> None:
    _asset(session, ticker="VALE3", asset_class=AssetClass.STOCKS, days_ago=35)
    rows, keys = notification_service.pending_maturities(session)
    assert len(rows) == 1

    notification_service.mark_maturities(keys)
    rows_again, keys_again = notification_service.pending_maturities(session)
    assert rows_again == [] and keys_again == []
