from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


class NotificationLevel(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class NotificationKind(StrEnum):
    """What produced this. Drives the icon and the deep link in the app."""

    ORDERS = "orders"  # a fresh order sheet is waiting
    REVIEW = "review"  # weekly / maturity / monthly committee output
    ALERT = "alert"  # a lot crossed its target or stop
    LEDGER = "ledger"  # personal finance: insights, digest
    SYSTEM = "system"  # a cron broke, a run was resumed, auth expired
    CHAT = "chat"  # the consultant finished a turn


def _now_utc() -> datetime:
    return datetime.now(UTC)


class Notification(SQLModel, table=True):
    """One message for the client, kept in the app.

    Everything the system used to fire at Telegram lands here first. The row is
    the durable copy: Web Push can fail silently (permission revoked, phone
    offline, VAPID rotated) and a dropped buzz must never mean a lost alert —
    the inbox still has it the next time the app is opened.
    """

    __tablename__ = "notification"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    kind: NotificationKind = Field(default=NotificationKind.SYSTEM, index=True)
    level: NotificationLevel = Field(default=NotificationLevel.INFO, index=True)

    title: str = Field(max_length=200)
    body: str = Field(sa_column=Column(Text))
    # Where tapping it should land in the app (e.g. "/investimentos?aba=carteira").
    url: str | None = Field(default=None, max_length=200)

    read_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=_now_utc, index=True)
