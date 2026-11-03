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
    held_abroad: bool = False,
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
            held_abroad=held_abroad,
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


# ── Crypto: national (ganho de capital mensal) × abroad (Lei 14.754) ──────


def _crypto(session: Session, total: str, pnl: str, when: datetime, abroad: bool = False) -> None:
    _sell(
        session,
        ticker="BTC",
        asset_class=AssetClass.CRYPTO,
        total=total,
        pnl=pnl,
        when=when,
        held_abroad=abroad,
    )


def test_crypto_exactly_35k_in_the_month_is_exempt(session: Session) -> None:
    # Two sales adding up to exactly R$ 35.000,00: "igual ou inferior" (P&R 653).
    _crypto(session, "20000", "5000", datetime(2026, 5, 4, 15, tzinfo=UTC))
    _crypto(session, "15000", "4000", datetime(2026, 5, 20, 15, tzinfo=UTC))
    month = tax_service.build_year_report(session, 2026)["months"][0]["crypto"]
    assert month["sales_brl"] == 35000.0
    assert month["exempt"] is True
    assert month["tax_due_brl"] == 0.0


def test_crypto_one_cent_above_35k_taxes_every_gaining_sale(session: Session) -> None:
    _crypto(session, "20000", "5000", datetime(2026, 5, 4, 15, tzinfo=UTC))
    _crypto(session, "15000.01", "4000", datetime(2026, 5, 20, 15, tzinfo=UTC))
    report = tax_service.build_year_report(session, 2026)
    month = report["months"][0]["crypto"]
    assert month["exempt"] is False
    assert month["tax_due_brl"] == 1350.0  # (5000 + 4000) × 15%
    assert report["total_darf_brl"] == 1350.0


def test_crypto_loss_offsets_nothing_in_the_month(session: Session) -> None:
    # P&R 583: distinct sales are never netted. Net is −1000, tax is still due.
    _crypto(session, "30000", "4000", datetime(2026, 6, 3, 15, tzinfo=UTC))
    _crypto(session, "10000", "-5000", datetime(2026, 6, 10, 15, tzinfo=UTC))
    month = tax_service.build_year_report(session, 2026)["months"][0]["crypto"]
    assert month["net_gain_brl"] == -1000.0
    assert month["tax_due_brl"] == 600.0


def test_crypto_loss_then_gain_does_not_carry_forward(session: Session) -> None:
    _crypto(session, "40000", "-8000", datetime(2026, 2, 3, 15, tzinfo=UTC))
    _crypto(session, "40000", "6000", datetime(2026, 3, 3, 15, tzinfo=UTC))
    report = tax_service.build_year_report(session, 2026)
    february, march = (m["crypto"] for m in report["months"])
    assert february["tax_due_brl"] == 0.0
    assert march["loss_carry_used_brl"] == 0.0
    assert march["tax_due_brl"] == 900.0  # full 6000 × 15%, the Feb loss is lost
    assert "crypto" not in report["loss_carryforward_brl"]


def test_progressive_brackets_apply_per_slice() -> None:
    tax = tax_service.progressive_capital_gains_tax
    assert tax(Decimal("1000")) == Decimal("150.00")
    assert tax(Decimal("5000000")) == Decimal("750000.00")
    # 5M × 15% + 1M × 17,5%
    assert tax(Decimal("6000000")) == Decimal("925000.00")
    # 5M×15% + 5M×17,5% + 20M×20% + 10M×22,5%
    assert tax(Decimal("40000000")) == Decimal("7875000.00")


def test_abroad_sales_leave_the_35k_test_and_pay_yearly(session: Session) -> None:
    # Same month: 30k national (exempt alone) + 20k abroad. Mixing them would
    # cross 35k; the abroad sale belongs to Lei 14.754 since 2024.
    _crypto(session, "30000", "3000", datetime(2026, 7, 8, 15, tzinfo=UTC))
    _crypto(session, "20000", "2000", datetime(2026, 7, 9, 15, tzinfo=UTC), abroad=True)
    report = tax_service.build_year_report(session, 2026)
    national = report["months"][0]["crypto"]
    assert national["sales_brl"] == 30000.0
    assert national["exempt"] is True
    assert report["total_darf_brl"] == 0.0  # abroad is never a monthly DARF
    abroad = report["crypto_abroad"]
    assert abroad["sales_brl"] == 20000.0
    assert abroad["tax_due_brl"] == 300.0
    assert abroad["paid_in"] == "Declaração de Ajuste Anual 2027"


def test_abroad_losses_offset_within_the_year_and_carry_to_the_next(session: Session) -> None:
    _crypto(session, "9000", "-4000", datetime(2025, 3, 3, 15, tzinfo=UTC), abroad=True)
    _crypto(session, "9000", "1000", datetime(2025, 9, 3, 15, tzinfo=UTC), abroad=True)
    _crypto(session, "9000", "5000", datetime(2026, 4, 3, 15, tzinfo=UTC), abroad=True)
    y2025 = tax_service.build_year_report(session, 2025)["crypto_abroad"]
    assert y2025["net_gain_brl"] == -3000.0
    assert y2025["tax_due_brl"] == 0.0
    assert y2025["loss_carryforward_brl"] == 3000.0
    y2026 = tax_service.build_year_report(session, 2026)["crypto_abroad"]
    assert y2026["loss_carry_used_brl"] == 3000.0
    assert y2026["tax_due_brl"] == 300.0  # (5000 − 3000) × 15%
    assert y2026["loss_carryforward_brl"] == 0.0


def test_abroad_before_2024_follows_the_national_regime(session: Session) -> None:
    _crypto(session, "20000", "1000", datetime(2023, 8, 1, 15, tzinfo=UTC))
    _crypto(session, "20000", "2000", datetime(2023, 8, 2, 15, tzinfo=UTC), abroad=True)
    report = tax_service.build_year_report(session, 2023)
    month = report["months"][0]["crypto"]
    assert month["sales_brl"] == 40000.0  # both count toward the old 35k test
    assert month["tax_due_brl"] == 450.0
    assert report["crypto_abroad"]["tax_due_brl"] == 0.0
