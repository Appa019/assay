from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CardCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    closing_day: int = Field(..., ge=1, le=31)
    due_day: int = Field(..., ge=1, le=31)
    is_default: bool = False


class CardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    closing_day: int | None = Field(default=None, ge=1, le=31)
    due_day: int | None = Field(default=None, ge=1, le=31)
    is_default: bool | None = None


# open: still accumulating · closed: waiting for the due date · past: due
# date gone (payment is not tracked, so "overdue" would be a lie).
InvoiceStatus = Literal["open", "closed", "past"]


class InvoiceRead(BaseModel):
    """One billing cycle, computed on read — never stored."""

    card_id: UUID
    period_start: date
    period_end: date
    closes_on: date
    due_on: date
    status: InvoiceStatus
    total_brl: float
    entries: int


class CardRead(BaseModel):
    id: UUID
    name: str
    closing_day: int
    due_day: int
    is_default: bool
    created_at: datetime
    open_invoice: InvoiceRead
    last_closed_invoice: InvoiceRead | None
