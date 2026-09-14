from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.models.cashflow import CashflowKind, CashflowWallet


def _now_utc() -> datetime:
    return datetime.now(UTC)


class Recurrence(SQLModel, table=True):
    """A commitment that repeats every month — salary, rent, a subscription.

    Configuration, never a ledger line. The forecast recomputes from these on
    every read, exactly like ``card_service`` does with invoices: changing the
    rent fixes every month at once. Writing six future rows into
    ``cashflow_entry`` instead would double-count the day the real expense
    lands and would make ``/extrato`` — which shows only what actually
    happened — display money that never moved.
    """

    __tablename__ = "recurrence"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    kind: CashflowKind = Field(index=True)
    amount_brl: Decimal = Field(decimal_places=2, max_digits=18)
    category: str = Field(default="outros", max_length=64, index=True)
    description: str | None = Field(default=None, max_length=512)
    # 1-31; a month shorter than the day falls back to its last day.
    day_of_month: int = Field(default=1)
    # Stored by VALUE like CashflowEntry.wallet — same reasoning: the ORM must
    # read the raw string back as an enum member.
    wallet: CashflowWallet = Field(
        default=CashflowWallet.CONTA,
        sa_column=Column(
            SAEnum(
                CashflowWallet,
                values_callable=lambda e: [m.value for m in e],
                native_enum=False,
                length=8,
            ),
            nullable=False,
            server_default=CashflowWallet.CONTA.value,
            index=True,
        ),
    )
    card_id: UUID | None = Field(default=None, foreign_key="credit_card.id", index=True)
    starts_on: date = Field(default_factory=date.today, index=True)
    # NULL = indefinite. Setting it is what makes "the financing ends in March"
    # show up in the forecast as relief instead of running forever.
    ends_on: date | None = Field(default=None, index=True)
    active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=_now_utc)
