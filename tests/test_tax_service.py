from datetime import UTC, date, datetime
from decimal import Decimal

from sqlmodel import Session

from app.models.asset import AssetClass
from app.models.trade import Trade, TradeSide
from app.services import tax_service


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
