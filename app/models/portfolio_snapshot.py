from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _now_utc() -> datetime:
    return datetime.now(UTC)


class PortfolioSnapshot(SQLModel, table=True):
    """Daily end-of-day portfolio valuation.

    One row per calendar day (upserted), powering the equity curve and the
    benchmark comparison. ``assets`` keeps the full per-asset breakdown so a
    day can be audited later.
    """

    __tablename__ = "portfolio_snapshot"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    snapshot_date: date = Field(index=True, unique=True)

    total_value: Decimal = Field(default=Decimal("0"), decimal_places=2, max_digits=18)
    fixed_income: Decimal = Field(default=Decimal("0"), decimal_places=2, max_digits=18)
    stocks: Decimal = Field(default=Decimal("0"), decimal_places=2, max_digits=18)
    crypto: Decimal = Field(default=Decimal("0"), decimal_places=2, max_digits=18)

    assets: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=_now_utc)
