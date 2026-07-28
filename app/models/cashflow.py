from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


class CashflowKind(StrEnum):
    EXPENSE = "expense"
    INCOME = "income"


class CashflowSource(StrEnum):
    CHAT = "chat"  # registered by the Telegram consultant (Claude)
    BOT = "bot"  # quick /gasto and /ganho bot commands
    API = "api"  # direct API/frontend entry


def _now_utc() -> datetime:
    return datetime.now(UTC)


class CashflowEntry(SQLModel, table=True):
    """Personal cashflow ledger: every expense and income the user reports.

    Separate from the ``Trade`` ledger on purpose — trades are portfolio
    operations; this is day-to-day personal finance (groceries, salary,
    freelance income) that the Telegram consultant tracks over chat.
    """

    __tablename__ = "cashflow_entry"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    kind: CashflowKind = Field(index=True)
    amount_brl: Decimal = Field(decimal_places=2, max_digits=18)
    category: str = Field(default="outros", max_length=64, index=True)
    description: str | None = Field(default=None, max_length=512)
    occurred_on: date = Field(default_factory=date.today, index=True)
    source: CashflowSource = Field(default=CashflowSource.API)
    created_at: datetime = Field(default_factory=_now_utc)
