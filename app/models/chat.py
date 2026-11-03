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
    # Waiting its turn: the client may send while the consultant is still
    # answering, and a turn the usage limit knocked down goes back to QUEUED
    # instead of dying, so it resumes by itself once credit returns.
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


def _now_utc() -> datetime:
    return datetime.now(UTC)


class ChatMessage(SQLModel, table=True):
    """One line of the consultant conversation, whichever door it came through.

    The Claude session already carries the model's own context; this table
    exists so a HUMAN can read the history (rows with channel=telegram are
    from the removed bot). Rotating the underlying
    Claude session (every ``chat_max_turns``) does not erase it.
    """

    __tablename__ = "chat_message"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    role: ChatRole = Field(index=True)
    content: str
    channel: ChatChannel = Field(default=ChatChannel.WEB)
    # QUEUED then RUNNING on the assistant row while the turn is pending, so
    # the web UI renders the queue instead of guessing from another endpoint.
    status: ChatTurnStatus = Field(default=ChatTurnStatus.DONE, index=True)
    # The queue lives in this table: a pending assistant row IS the job. The
    # prompt is kept apart from `content` because what the model receives is
    # not what the client reads — an attachment turn shows "📎 cupom.jpg" and
    # sends a paragraph of instructions naming the file on disk.
    prompt: str | None = Field(default=None)
    attempts: int = Field(default=0)
    # Set while a retry waits for the usage window to reopen; the worker will
    # not touch the job before this instant.
    run_after: datetime | None = Field(default=None)
    # Why it is waiting ("limit" or "transient") — the two get very different
    # patience, and mixing their budgets would either give up on a limit after
    # three tries or hammer a broken CLI for a day.
    retry_kind: str | None = Field(default=None)
    # Which model actually answered, and which tier the router picked. Kept on
    # the row so the choice is visible and auditable after the fact.
    model: str | None = Field(default=None)
    tier: str | None = Field(default=None)
    cost_usd: float | None = Field(default=None)
    duration_s: float | None = Field(default=None)
    created_at: datetime = Field(default_factory=_now_utc, index=True)
