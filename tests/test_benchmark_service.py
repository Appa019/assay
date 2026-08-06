from datetime import UTC, date, datetime
from decimal import Decimal

from sqlmodel import Session

from app.models.asset import AssetClass
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.trade import Trade, TradeSide
from app.services import benchmark_service


def _snapshot(session: Session, day: date, total: str) -> None:
    session.add(
        PortfolioSnapshot(
            snapshot_date=day,
            total_value=Decimal(total),
            fixed_income=Decimal(total),
            stocks=Decimal("0"),
            crypto=Decimal("0"),
        )
    )
    session.commit()


def test_portfolio_index_neutralizes_deposits(session: Session) -> None:
    """TWR core invariant: a R$ 5.000 deposit with zero market movement is 0%
    return, not +50% — raw total_value growth must never read as performance."""
    _snapshot(session, date(2026, 7, 1), "10000")
    _snapshot(session, date(2026, 7, 2), "15000")
    session.add(
        Trade(
            ticker="CDB-X",
            asset_class=AssetClass.FIXED_INCOME,
            side=TradeSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("5000"),
            total_brl=Decimal("5000"),
            executed_at=datetime(2026, 7, 2, 12, tzinfo=UTC),
        )
    )
    session.commit()

    index = benchmark_service._portfolio_index(session, days=30)
    assert [round(v, 2) for _d, v in index] == [100.0, 100.0]


def test_portfolio_index_sees_real_gains_on_top_of_flows(session: Session) -> None:
    """Deposit 5.000 AND the pool gains 1.000 → +6.67% on the 15.000 base."""
    _snapshot(session, date(2026, 7, 1), "10000")
    _snapshot(session, date(2026, 7, 2), "16000")
    session.add(
        Trade(
            ticker="CDB-X",
            asset_class=AssetClass.FIXED_INCOME,
            side=TradeSide.BUY,
            quantity=Decimal("1"),
            price=Decimal("5000"),
            total_brl=Decimal("5000"),
            executed_at=datetime(2026, 7, 2, 12, tzinfo=UTC),
        )
    )
    session.commit()

    index = benchmark_service._portfolio_index(session, days=30)
    assert round(index[-1][1], 2) == 106.67  # (16000 − 15000) / 15000


def test_ffill_and_rebase_forward_fill_weekends() -> None:
    series = {date(2026, 1, 1): 200.0, date(2026, 1, 3): 220.0}
    days = [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]
    raw = benchmark_service._ffill_at(series, days)
    assert raw == [200.0, 200.0, 220.0]
    assert benchmark_service._rebase(raw, 0) == [100.0, 100.0, 110.0]


def test_ffill_before_first_datapoint_is_none() -> None:
    series = {date(2026, 1, 3): 220.0}
    days = [date(2026, 1, 1), date(2026, 1, 3)]
    assert benchmark_service._ffill_at(series, days) == [None, 220.0]


def test_first_common_index_ignores_fully_missing_series() -> None:
    """All lines rebase at the first day EVERY available series covers; a
    series that failed outright (all None) must not block the others."""
    portfolio = [100.0, 101.0, 102.0]
    btc: list[float | None] = [None, 300.0, 310.0]
    dead: list[float | None] = [None, None, None]
    assert benchmark_service._first_common_index([portfolio, btc, dead]) == 1
    assert benchmark_service._first_common_index([portfolio]) == 0


def test_compound_cdi_rows_skips_malformed_row() -> None:
    """One bad BCB row costs one point — never the whole CDI line."""
    rows = [
        {"data": "01/07/2026", "valor": "0.05"},
        {"data": "corrompida", "valor": "0.05"},
        {"data": "03/07/2026", "valor": "0.05"},
    ]
    out = benchmark_service._compound_cdi_rows(rows)
    assert len(out) == 2
    assert round(out[date(2026, 7, 3)], 6) == round(100.0 * 1.0005 * 1.0005, 6)
