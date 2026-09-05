from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.asset import AssetClass
from app.models.order import OrderStatus


class TicketLineRead(BaseModel):
    """One line of the broker ticket, ready to type."""

    ticker: str
    quantity: float
    price: float
    book: str
    total_brl: float


class OrderRead(BaseModel):
    id: UUID
    contribution_id: UUID
    ticker: str
    asset_class: AssetClass
    amount_brl: float
    pct_of_contribution: float | None
    target_price: float | None
    stop_price: float | None
    thesis: str | None
    status: OrderStatus
    suggested_quantity: float | None = None
    reference_price: float | None = None
    priced_at: datetime | None = None
    # Derived, not stored: the B3 round-lot/odd-lot split the ticket needs.
    ticket: list[TicketLineRead] = []
    executed_quantity: float | None
    executed_price: float | None
    executed_at: datetime | None
    created_at: datetime


class OrderExecute(BaseModel):
    quantity: Decimal = Field(..., gt=0)
    price: Decimal = Field(..., gt=0)


class OrderSkip(BaseModel):
    reason: str | None = Field(default=None, max_length=200)
