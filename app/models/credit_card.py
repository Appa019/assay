from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


def _now_utc() -> datetime:
    return datetime.now(UTC)


class CreditCard(SQLModel, table=True):
    """A credit card the client pays with.

    Invoices are never stored: they are computed from ``closing_day`` and the
    ledger entries that reference the card, so changing the closing day
    regroups the whole history instantly. Exactly one card is the default
    while any exists — ``card_service`` enforces it.
    """

    __tablename__ = "credit_card"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=40, index=True)
    # 1-31; a month shorter than the day falls back to its last day.
    closing_day: int
    due_day: int
    is_default: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=_now_utc)
