from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.contribution import ContributionStatus, PromptKey


class ContributionCreate(BaseModel):
    amount_brl: Decimal = Field(..., gt=0)
    notes: str | None = None


class PromptRead(BaseModel):
    id: UUID
    prompt_order: int
    prompt_key: PromptKey
    title: str
    description: str
    content: str
    response: str | None
    responded_at: datetime | None
    cost_usd: float | None = None
    duration_s: float | None = None
    num_turns: int | None = None
    context_tokens: int | None = None


class ContributionRead(BaseModel):
    id: UUID
    amount_brl: float
    status: ContributionStatus
    macro_snapshot: dict[str, Any] | None
    portfolio_snapshot: dict[str, Any] | None
    final_summary: str | None
    notes: str | None
    created_at: datetime
    completed_at: datetime | None
    # UTC-aware (unlike created_at/completed_at, which SQLite returns naive).
    # Clients must convert to local before showing the hour to the client.
    scheduled_for: datetime | None = None
    prompts: list[PromptRead] = []


class ContributionListItem(BaseModel):
    id: UUID
    amount_brl: float
    status: ContributionStatus
    created_at: datetime
    completed_at: datetime | None
    prompts_total: int
    prompts_answered: int


class PromptResponseCreate(BaseModel):
    response: str = Field(..., min_length=1)


class ContributionFinalize(BaseModel):
    final_summary: str | None = None
