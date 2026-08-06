import os
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlmodel import Session

from app.models.asset import AssetClass
from app.models.trade import Trade, TradeSide
from app.services import tax_service


@pytest.fixture()
def brt_tz() -> Iterator[None]:
    """Pin the process timezone so night-boundary assertions hold on UTC CI."""
    old = os.environ.get("TZ")
    os.environ["TZ"] = "America/Sao_Paulo"
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


def _sell(
    session: Session,
    *,
    ticker: str,
    asset_class: AssetClass,
    total: str,
    pnl: str,
    when: datetime,
) -> None:
    session.add(
        Trade(
            ticker=ticker,
            asset_class=asset_class,
            side=TradeSide.SELL,
            quantity=Decimal("1"),
            price=Decimal(total),
            total_brl=Decimal(total),
            realized_pnl_brl=Decimal(pnl),
            lot_entry_date=date(2026, 1, 2),
            executed_at=when,
        )
    )
    session.commit()


def test_stocks_below_20k_are_exempt(session: Session) -> None:
    _sell(
        session,
        ticker="PETR4",
        asset_class=AssetClass.STOCKS,
        total="15000",
        pnl="2000",
        when=datetime(2026, 3, 10, 12, tzinfo=UTC),
    )
    report = tax_service.build_year_report(session, 2026)
    month = report["months"][0]["stocks"]
    assert month["exempt"] is True
    assert month["tax_due_brl"] == 0.0
    assert report["total_darf_brl"] == 0.0


def test_stocks_above_20k_taxed_with_loss_carryforward(session: Session) -> None:
    # Feb: loss of 3k on a small (exempt-size) sale — still accumulates.
    _sell(
        session,
        ticker="VALE3",
        asset_class=AssetClass.STOCKS,
        total="10000",
        pnl="-3000",
        when=datetime(2026, 2, 5, 12, tzinfo=UTC),
    )
    # Apr: 30k sold (above 20k) with 8k gain → taxable 8k − 3k carry = 5k → 15%.
    _sell(
        session,
        ticker="PETR4",
        asset_class=AssetClass.STOCKS,
        total="30000",
        pnl="8000",
        when=datetime(2026, 4, 15, 12, tzinfo=UTC),
    )
    report = tax_service.build_year_report(session, 2026)
    april = next(m for m in report["months"] if m["month"] == "2026-04")["stocks"]
    assert april["exempt"] is False
    assert april["loss_carry_used_brl"] == 3000.0
    assert april["tax_due_brl"] == 750.0  # (8000 − 3000) × 15%
    assert report["total_darf_brl"] == 750.0


def test_crypto_exemption_uses_35k_limit(session: Session) -> None:
    _sell(
        session,
        ticker="BTC",
        asset_class=AssetClass.CRYPTO,
        total="30000",
        pnl="12000",
        when=datetime(2026, 6, 20, 12, tzinfo=UTC),
    )
    report = tax_service.build_year_report(session, 2026)
    month = report["months"][0]["crypto"]
    assert month["exempt"] is True  # 30k < 35k crypto limit (would tax as stocks)
    assert month["tax_due_brl"] == 0.0


def test_cdb_reported_as_withheld_info(session: Session) -> None:
    _sell(
        session,
        ticker="CDB-ITAU",
        asset_class=AssetClass.FIXED_INCOME,
        total="5100",
        pnl="100",
        when=datetime(2026, 5, 4, 12, tzinfo=UTC),
    )
    report = tax_service.build_year_report(session, 2026)
    info = report["months"][0]["fixed_income_info"][0]
    assert info["withheld_rate_pct"] == 22.5  # held ~4 months → top bracket
    assert report["total_darf_brl"] == 0.0


def test_late_night_utc_sale_lands_in_local_month(session: Session, brt_tz: None) -> None:
    """Regression for the documented UTC/local pattern: a sale at 22:30 BRT on
    March 31st is April 1st in UTC — it must be reported in MARCH."""
    _sell(
        session,
        ticker="PETR4",
        asset_class=AssetClass.STOCKS,
        total="25000",
        pnl="1000",
        when=datetime(2026, 4, 1, 1, 30),  # naive UTC = 2026-03-31 22:30 BRT
    )
    report = tax_service.build_year_report(session, 2026)
    assert report["months"][0]["month"] == "2026-03"


def test_cdb_days_held_uses_local_date_at_bracket_boundary(session: Session, brt_tz: None) -> None:
    """The lot entered 2026-01-02 and was sold at 22:30 BRT exactly 180 local
    days later. The UTC date says 181 days (20% bracket) — the local date says
    180 (22.5%). The rate shown must follow the LOCAL day."""
    _sell(
        session,
        ticker="CDB-BTG",
        asset_class=AssetClass.FIXED_INCOME,
        total="10100",
        pnl="100",
        when=datetime(2026, 7, 2, 1, 30),  # naive UTC = 2026-07-01 22:30 BRT
    )
    report = tax_service.build_year_report(session, 2026)
    info = report["months"][0]["fixed_income_info"][0]
    assert info["days_held"] == 180
    assert info["withheld_rate_pct"] == 22.5


def test_darf_below_minimum_flag(session: Session) -> None:
    """A due amount under R$ 10 is not paid that month — the flag must mark it
    (and only it) so the report can say 'accumulate to next month'."""
    _sell(  # taxable month, tax due = 15% × 60 = R$ 9.00 → below minimum
        session,
        ticker="VALE3",
        asset_class=AssetClass.STOCKS,
        total="25000",
        pnl="60",
        when=datetime(2026, 2, 10, 12, tzinfo=UTC),
    )
    _sell(  # taxable month, tax due = 15% × 200 = R$ 30.00 → normal DARF
        session,
        ticker="VALE3",
        asset_class=AssetClass.STOCKS,
        total="25000",
        pnl="200",
        when=datetime(2026, 3, 10, 12, tzinfo=UTC),
    )
    report = tax_service.build_year_report(session, 2026)
    feb, mar = report["months"][0]["stocks"], report["months"][1]["stocks"]
    assert feb["tax_due_brl"] == 9.0
    assert feb["darf_below_minimum"] is True
    assert mar["tax_due_brl"] == 30.0
    assert mar["darf_below_minimum"] is False
