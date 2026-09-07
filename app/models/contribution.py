from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel


class ContributionStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class PromptKey(StrEnum):
    MACRO = "macro"
    SELECTION = "selection"
    EQUITY = "equity_diligence"
    CRYPTO = "crypto_diligence"
    DECISION = "decision"
    RESEARCH = "research"  # legacy: contributions created before the 5-stage split


def _now_utc() -> datetime:
    return datetime.now(UTC)


class Contribution(SQLModel, table=True):
    __tablename__ = "contribution"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    amount_brl: Decimal = Field(decimal_places=2, max_digits=18)
    status: ContributionStatus = Field(default=ContributionStatus.PENDING, index=True)

    macro_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    portfolio_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    final_summary: str | None = Field(default=None, sa_column=Column(Text))
    notes: str | None = Field(default=None, sa_column=Column(Text))

    # Claude Code session id of the chained analysis run. Persisted so an
    # interrupted run (limit/crash) can be resumed from where it stopped.
    claude_session_id: str | None = Field(default=None)
    # Consecutive failed automatic runs; caps the auto-resume retry loop so a
    # permanently broken analysis stops burning money. Reset to 0 on success.
    run_attempts: int = Field(default=0)
    # When the committee should start. Set when the client asks for an aporte
    # and the run is deferred to the small hours; cleared once it starts, so a
    # started-then-interrupted run belongs to resume_pending, not to the
    # scheduler. NULL means "not scheduled" (manual flow, or already running).
    scheduled_for: datetime | None = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=_now_utc, index=True)
    completed_at: datetime | None = Field(default=None)


class ContributionPrompt(SQLModel, table=True):
    __tablename__ = "contribution_prompt"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    contribution_id: UUID = Field(foreign_key="contribution.id", index=True)

    prompt_order: int = Field(index=True)
    prompt_key: PromptKey = Field(index=True)

    title: str = Field(max_length=200)
    description: str = Field(sa_column=Column(Text))
    content: str = Field(sa_column=Column(Text))

    response: str | None = Field(default=None, sa_column=Column(Text))
    responded_at: datetime | None = Field(default=None)

    # Per-step run telemetry, persisted as each step completes.
    cost_usd: float | None = Field(default=None)
    duration_s: float | None = Field(default=None)
    num_turns: int | None = Field(default=None)

    created_at: datetime = Field(default_factory=_now_utc)
