from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.asset import AssetClass
from app.models.order import OrderStatus


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
    executed_quantity: float | None
    executed_price: float | None
    executed_at: datetime | None
    created_at: datetime


class OrderExecute(BaseModel):
    quantity: Decimal = Field(..., gt=0)
    price: Decimal = Field(..., gt=0)


class OrderSkip(BaseModel):
    reason: str | None = Field(default=None, max_length=200)
