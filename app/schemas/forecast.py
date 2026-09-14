from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.cashflow import CashflowKind

# Where a forecast line came from. The screen renders the three differently:
# a committed row reads as fact, a recurring one as expectation.
ForecastOrigin = Literal["realized", "installment", "recurring"]


class ForecastLine(BaseModel):
    """One component of a month's total, with its provenance."""

    origin: ForecastOrigin
    kind: CashflowKind
    label: str
    category: str
    amount_brl: float
    # Calendar day the money moves. Always set: the ledger row has a date and
    # a recurrence has its (clamped) day of month.
    day: int
    card_name: str | None = None
    installment_no: int | None = None
    installment_count: int | None = None
    recurrence_id: UUID | None = None


class ForecastInvoice(BaseModel):
    """A card invoice falling due in this month.

    Shown as a legend, NEVER added to the month's outflow: its purchases
    already count on the day they happened (competência), so adding the
    invoice would book the same money twice.
    """

    card_id: UUID
    card_name: str
    closes_on: date
    due_on: date
    total_brl: float


class ForecastMonth(BaseModel):
    month: str  # YYYY-MM
    is_current: bool
    income_brl: float
    expense_brl: float
    net_brl: float
    # Already moved (occurred_on <= today) vs still to move. In a future month
    # everything is pending.
    realized_income_brl: float
    realized_expense_brl: float
    pending_income_brl: float
    pending_expense_brl: float
    lines: list[ForecastLine] = Field(default_factory=list)
    invoices: list[ForecastInvoice] = Field(default_factory=list)


class Forecast(BaseModel):
    """The next N months of committed money, current month first."""

    generated_on: date
    months: list[ForecastMonth]
    # Sum over the horizon — the "sobra prevista" headline.
    total_income_brl: float
    total_expense_brl: float
    total_net_brl: float
    # False when nothing is registered yet: the screen shows an empty state
    # telling the client to register commitments with the consultant instead
    # of a wall of zeros that looks broken.
    has_commitments: bool
