from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from app.models.asset import AssetClass


class OrderStatus(StrEnum):
    PENDING = "pending"
    EXECUTED = "executed"
    SKIPPED = "skipped"


def _now_utc() -> datetime:
    return datetime.now(UTC)


class Order(SQLModel, table=True):
    """One recommended buy from a contribution's final order sheet.

    Parsed from the closing step's machine-readable ``{"orders": [...]}``
    block. Executing an order (bot ``/executei`` or the API) creates the
    Asset lot — inheriting the committee's thesis/target/stop — and links
    back here, which is what makes recommendation-vs-reality tracking
    (did we follow it? at what price?) possible.
    """

    __tablename__ = "order"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    contribution_id: UUID = Field(foreign_key="contribution.id", index=True)

    ticker: str = Field(index=True, max_length=32)
    asset_class: AssetClass = Field(index=True)
    amount_brl: Decimal = Field(decimal_places=2, max_digits=18)
    pct_of_contribution: float | None = Field(default=None)
    target_price: Decimal | None = Field(default=None, decimal_places=8, max_digits=24)
    stop_price: Decimal | None = Field(default=None, decimal_places=8, max_digits=24)
    thesis: str | None = Field(default=None, max_length=512)

    status: OrderStatus = Field(default=OrderStatus.PENDING, index=True)
    # Filled on execution: what actually happened at the broker/exchange.
    executed_quantity: Decimal | None = Field(default=None, decimal_places=8, max_digits=24)
    executed_price: Decimal | None = Field(default=None, decimal_places=8, max_digits=24)
    executed_asset_id: UUID | None = Field(default=None)
    executed_at: datetime | None = Field(default=None)

    created_at: datetime = Field(default_factory=_now_utc, index=True)
