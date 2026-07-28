from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.cashflow import CashflowKind, CashflowSource


class CashflowCreate(BaseModel):
    kind: CashflowKind
    amount_brl: Decimal = Field(..., gt=0)
    category: str = Field(default="outros", max_length=64)
    description: str | None = Field(default=None, max_length=512)
    occurred_on: date | None = None
    source: CashflowSource = CashflowSource.API


class CashflowRead(BaseModel):
    id: UUID
    kind: CashflowKind
    amount_brl: float
    category: str
    description: str | None
    occurred_on: date
    source: CashflowSource
    created_at: datetime


class CategoryTotal(BaseModel):
    kind: CashflowKind
    category: str
    total_brl: float
    count: int


class CashflowSummary(BaseModel):
    month: str  # YYYY-MM
    income_brl: float
    expense_brl: float
    net_brl: float
    entries: int
    by_category: list[CategoryTotal]
