from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from app.models.asset import AssetClass


class TradeSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


def _now_utc() -> datetime:
    return datetime.now(UTC)


class Trade(SQLModel, table=True):
    """Immutable ledger of every buy/sell.

    Assets are deleted from the portfolio when fully sold; this ledger is the
    permanent audit trail that makes realized P&L, track record and tax
    reporting possible.
    """

    __tablename__ = "trade"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    asset_id: UUID | None = Field(default=None, index=True)
    ticker: str = Field(index=True, max_length=32)
    name: str | None = Field(default=None, max_length=128)
    asset_class: AssetClass = Field(index=True)
    side: TradeSide = Field(index=True)

    quantity: Decimal = Field(decimal_places=8, max_digits=24)
    price: Decimal = Field(decimal_places=8, max_digits=24)
    total_brl: Decimal = Field(decimal_places=2, max_digits=18)

    # Filled on sells only: P&L against the lot's average entry price.
    realized_pnl_brl: Decimal | None = Field(default=None, decimal_places=2, max_digits=18)
    realized_pnl_pct: float | None = Field(default=None)
    # Entry date of the lot this sell closed (per-lot holding accounting).
    lot_entry_date: date | None = Field(default=None)

    executed_at: datetime = Field(default_factory=_now_utc, index=True)
    note: str | None = Field(default=None, max_length=512)
