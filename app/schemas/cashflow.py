from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.cashflow import CashflowKind, CashflowSource, CashflowWallet


class CashflowCreate(BaseModel):
    kind: CashflowKind
    amount_brl: Decimal = Field(..., gt=0)
    category: str = Field(default="outros", max_length=64)
    description: str | None = Field(default=None, max_length=512)
    occurred_on: date | None = None
    source: CashflowSource = CashflowSource.API
    # Free-form on purpose: the consultant and the classifier may send "VR" or
    # "vale refeição" — the service folds it onto the closed vocabulary.
    wallet: str = Field(default="conta", max_length=32)


class CashflowRead(BaseModel):
    id: UUID
    kind: CashflowKind
    amount_brl: float
    category: str
    description: str | None
    occurred_on: date
    source: CashflowSource
    wallet: CashflowWallet
    created_at: datetime


class CategoryTotal(BaseModel):
    kind: CashflowKind
    category: str
    total_brl: float
    count: int


class WalletTotal(BaseModel):
    """One wallet's movement inside a single month."""

    wallet: CashflowWallet
    income_brl: float
    expense_brl: float
    net_brl: float
    entries: int


class WalletBalance(BaseModel):
    """All-time balance of one wallet (credits minus spending) — how much
    VR/VA credit is still unspent since tracking began."""

    wallet: CashflowWallet
    income_brl: float
    expense_brl: float
    balance_brl: float
    entries: int


class CashflowSummary(BaseModel):
    month: str  # YYYY-MM
    income_brl: float
    expense_brl: float
    net_brl: float
    entries: int
    by_category: list[CategoryTotal]
    by_wallet: list[WalletTotal] = Field(default_factory=list)


class MonthTotals(BaseModel):
    """One month collapsed to four numbers, for trend comparison."""

    month: str  # YYYY-MM
    income_brl: float
    expense_brl: float
    net_brl: float
    entries: int
