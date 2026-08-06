import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.config import settings
from app.models.asset import Asset, AssetClass
from app.services import market_data_service, price_refresh_service


def _cdb(avg_price: str) -> Asset:
    return Asset(
        ticker="CDB-BTG",
        asset_class=AssetClass.FIXED_INCOME,
        quantity=Decimal("1"),
        avg_price=Decimal(avg_price),
        entry_date=date.today() - timedelta(days=90),
    )


def test_cdb_accrues_by_cdi_factor(monkeypatch: pytest.MonkeyPatch) -> None:
    """avg_price 1000 × CDI accumulated 10% at 100% of CDI → 1100."""

    async def fake_factor(_entry: date) -> float:
        return 1.10

    monkeypatch.setattr(market_data_service, "get_cdi_accumulated_factor", fake_factor)
    monkeypatch.setattr(settings, "cdb_pct_cdi", 100.0)
    price = asyncio.run(price_refresh_service._cdb_price(_cdb("1000"), {}))
    assert price == pytest.approx(1100.0)


def test_cdb_pct_cdi_scales_the_accrual(monkeypatch: pytest.MonkeyPatch) -> None:
    """At 110% of CDI the same 10% CDI window accrues 11%."""

    async def fake_factor(_entry: date) -> float:
        return 1.10

    monkeypatch.setattr(market_data_service, "get_cdi_accumulated_factor", fake_factor)
    monkeypatch.setattr(settings, "cdb_pct_cdi", 110.0)
    price = asyncio.run(price_refresh_service._cdb_price(_cdb("1000"), {}))
    assert price == pytest.approx(1110.0)


def test_cdb_price_none_when_series_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_factor(_entry: date) -> None:
        return None

    monkeypatch.setattr(market_data_service, "get_cdi_accumulated_factor", fake_factor)
    price = asyncio.run(price_refresh_service._cdb_price(_cdb("1000"), {}))
    assert price is None  # caller keeps the previous price + warns
