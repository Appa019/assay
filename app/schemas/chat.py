from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.chat import ChatChannel, ChatRole, ChatTurnStatus


class ChatSend(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)


class ChatMessageRead(BaseModel):
    id: UUID
    role: ChatRole
    content: str
    channel: ChatChannel
    status: ChatTurnStatus
    # Which model answered. Recorded on every assistant row so the routing
    # decision is visible instead of buried in the database.
    model: str | None = None
    tier: str | None = None
    created_at: datetime


class ChatState(BaseModel):
    """Everything the chat screen needs in one poll."""

    busy: bool
    messages: list[ChatMessageRead]
