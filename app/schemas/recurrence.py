from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.cashflow import CashflowKind, CashflowWallet


class RecurrenceCreate(BaseModel):
    kind: CashflowKind
    amount_brl: Decimal = Field(..., gt=0)
    category: str = Field(default="outros", max_length=64)
    description: str | None = Field(default=None, max_length=512)
    day_of_month: int = Field(default=1, ge=1, le=31)
    # Free-form like CashflowCreate.wallet — the service folds it.
    wallet: str = Field(default="conta", max_length=32)
    card: str | None = Field(default=None, max_length=40)
    # Defaults to today: a commitment registered now starts counting now.
    starts_on: date | None = None
    ends_on: date | None = None


class RecurrenceUpdate(BaseModel):
    amount_brl: Decimal | None = Field(default=None, gt=0)
    category: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=512)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    wallet: str | None = Field(default=None, max_length=32)
    card: str | None = Field(default=None, max_length=40)
    starts_on: date | None = None
    ends_on: date | None = None
    active: bool | None = None


class RecurrenceRead(BaseModel):
    id: UUID
    kind: CashflowKind
    amount_brl: float
    category: str
    description: str | None
    day_of_month: int
    wallet: CashflowWallet
    card_id: UUID | None = None
    card_name: str | None = None  # filled by the router (one lookup, no N+1)
    starts_on: date
    ends_on: date | None
    active: bool
    created_at: datetime
