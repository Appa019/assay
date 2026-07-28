from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatChannel(StrEnum):
    """Where the message was typed. The conversation itself is shared."""

    TELEGRAM = "telegram"
    WEB = "web"


class ChatTurnStatus(StrEnum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


def _now_utc() -> datetime:
    return datetime.now(UTC)


class ChatMessage(SQLModel, table=True):
    """One line of the consultant conversation, whichever door it came through.

    The Claude session already carries the model's own context; this table
    exists so a HUMAN can read the history — and so a conversation started on
    Telegram shows up on the website and vice versa. Rotating the underlying
    Claude session (every ``chat_max_turns``) does not erase it.
    """

    __tablename__ = "chat_message"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    role: ChatRole = Field(index=True)
    content: str
    channel: ChatChannel = Field(default=ChatChannel.WEB)
    # RUNNING on the assistant row while the turn is in flight, so the web UI
    # can render a pending bubble instead of guessing from a separate endpoint.
    status: ChatTurnStatus = Field(default=ChatTurnStatus.DONE, index=True)
    # Which model actually answered, and which tier the router picked. Kept on
    # the row so the choice is visible and auditable after the fact.
    model: str | None = Field(default=None)
    tier: str | None = Field(default=None)
    cost_usd: float | None = Field(default=None)
    duration_s: float | None = Field(default=None)
    created_at: datetime = Field(default_factory=_now_utc, index=True)
