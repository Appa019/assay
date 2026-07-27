from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel


class ReportKind(StrEnum):
    WEEKLY = "weekly"
    MATURITY = "maturity"
    MONTHLY = "monthly"


def _now_utc() -> datetime:
    return datetime.now(UTC)


class Report(SQLModel, table=True):
    """An autonomous committee review (weekly macro+holdings, or asset maturity).

    Stored for the Telegram push, the dashboard history, and as consult context
    for future contribution runs. ``steps`` keeps each chained step's output so
    the whole run is auditable.
    """

    __tablename__ = "report"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    kind: ReportKind = Field(index=True)
    title: str = Field(max_length=200)
    content: str = Field(sa_column=Column(Text))  # final executive report (sent to Telegram)

    cost_usd: float = Field(default=0.0)
    session_id: str | None = Field(default=None, max_length=64)

    macro_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    portfolio_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    steps: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=_now_utc, index=True)
