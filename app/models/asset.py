from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


class AssetClass(StrEnum):
    FIXED_INCOME = "fixed_income"
    STOCKS = "stocks"
    CRYPTO = "crypto"


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _today() -> date:
    return date.today()


class Asset(SQLModel, table=True):
    __tablename__ = "asset"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    ticker: str = Field(index=True, max_length=32)
    name: str | None = Field(default=None, max_length=128)
    asset_class: AssetClass = Field(index=True)
    quantity: Decimal = Field(default=Decimal("0"), decimal_places=8, max_digits=24)
    avg_price: Decimal = Field(default=Decimal("0"), decimal_places=8, max_digits=24)
    current_price: Decimal | None = Field(default=None, decimal_places=8, max_digits=24)
    entry_date: date = Field(default_factory=_today)
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)
