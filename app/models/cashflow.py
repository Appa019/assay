from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel


class CashflowKind(StrEnum):
    EXPENSE = "expense"
    INCOME = "income"


class CashflowSource(StrEnum):
    CHAT = "chat"  # registered by the Telegram consultant (Claude)
    BOT = "bot"  # quick /gasto and /ganho bot commands
    API = "api"  # direct API/frontend entry


class CashflowWallet(StrEnum):
    """Which pot of money moved. VR/VA are meal/food benefit cards — separate
    balances that can only buy food, so they must never be mistaken for
    investable account money."""

    CONTA = "conta"  # bank account / pix / card — real, investable money
    VR = "vr"  # vale-refeição (meal voucher)
    VA = "va"  # vale-alimentação (grocery voucher)


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
    # Stored by VALUE ('conta'/'vr'/'va'), not by enum NAME as SQLModel would
    # default to: rows added on old databases get the ALTER TABLE default
    # 'conta', and the ORM must read that raw string back as an enum member.
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
    # Credit card the purchase went on; NULL = pix/debit/cash/benefit card.
    card_id: UUID | None = Field(default=None, foreign_key="credit_card.id", index=True)
    # Installment bookkeeping: one row per installment, all sharing a group.
    # All three stay NULL on a single-payment purchase.
    installment_no: int | None = Field(default=None)
    installment_count: int | None = Field(default=None)
    installment_group: UUID | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=_now_utc)
