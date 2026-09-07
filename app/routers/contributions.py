from datetime import UTC, datetime
from uuid import UUID

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import case, func
from sqlmodel import Session, select

from app.config import settings
from app.core.database import engine, get_session
from app.models.contribution import (
    Contribution,
    ContributionPrompt,
    ContributionStatus,
    PromptKey,
)
from app.models.order import Order, OrderStatus
from app.schemas.contribution import (
    ContributionCreate,
    ContributionFinalize,
    ContributionListItem,
    ContributionRead,
    PromptRead,
    PromptResponseCreate,
)
from app.services import analysis_runner, contribution_service

logger = structlog.get_logger()

router = APIRouter(prefix="/api/contributions", tags=["contributions"])


def _utc_aware(value: datetime | None) -> datetime | None:
    """Stamp UTC on a timestamp SQLite handed back naive.

    Without this the JSON carries "2026-09-07T04:00:00" with no zone, and every
    client reads it as LOCAL time — the consultant would tell the client his
    aporte runs at 4am when it runs at 1am. Only ``scheduled_for`` goes through
    here: it is new, so making it correct breaks nobody, while re-stamping the
    older fields would move dates the front end already renders.
    """
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _to_read(contribution: Contribution, prompts: list[ContributionPrompt]) -> ContributionRead:
    return ContributionRead(
        id=contribution.id,
        amount_brl=contribution.amount_brl,
        status=contribution.status,
        macro_snapshot=contribution.macro_snapshot,
        portfolio_snapshot=contribution.portfolio_snapshot,
        final_summary=contribution.final_summary,
        notes=contribution.notes,
        created_at=contribution.created_at,
        completed_at=contribution.completed_at,
        scheduled_for=_utc_aware(contribution.scheduled_for),
        prompts=[
            PromptRead.model_validate(p, from_attributes=True)
            for p in sorted(prompts, key=lambda x: x.prompt_order)
        ],
    )


@router.get("", response_model=list[ContributionListItem])
async def list_contributions(
    session: Session = Depends(get_session),
) -> list[ContributionListItem]:
    answered_expr = func.sum(case((ContributionPrompt.response.is_not(None), 1), else_=0)).label(
        "answered"
    )
    total_expr = func.count(ContributionPrompt.id).label("total")

    stmt = (
        select(Contribution, total_expr, answered_expr)
        .outerjoin(
            ContributionPrompt,
            ContributionPrompt.contribution_id == Contribution.id,
        )
        .group_by(Contribution.id)
        .order_by(Contribution.created_at.desc())
    )

    return [
        ContributionListItem(
            id=contrib.id,
            amount_brl=contrib.amount_brl,
            status=contrib.status,
            created_at=contrib.created_at,
            completed_at=contrib.completed_at,
            prompts_total=int(total or 0),
            prompts_answered=int(answered or 0),
        )
        for contrib, total, answered in session.exec(stmt).all()
    ]


def _run_analysis_bg(contribution_id: UUID) -> None:
    """Background entrypoint: run the full analysis on its own DB session."""
    with Session(engine) as bg_session:
        try:
            analysis_runner.run_analysis(bg_session, contribution_id)
        except analysis_runner.AnalysisError as exc:
            logger.error(
                "background_analysis_failed", contribution_id=str(contribution_id), error=str(exc)
            )


@router.post("", response_model=ContributionRead, status_code=201)
async def create_contribution(
    payload: ContributionCreate,
    background_tasks: BackgroundTasks,
    run: bool = False,
    now: bool = False,
    session: Session = Depends(get_session),
) -> ContributionRead:
    """Create the contribution and its prompts.

    ``run=true`` asks for the committee. By default that SCHEDULES it for the
    next night slot instead of starting it here: the run is ~90 minutes of the
    plan's usage window, and burning that window in the middle of the client's
    day is what made the consultant answer "bati no limite" when he needed it.
    ``now=true`` (or CONTRIBUTION_NIGHT_RUN=false) runs immediately.
    The response carries ``scheduled_for`` so the caller can say when.
    """
    contribution, prompt_rows = await contribution_service.create_contribution_with_prompts(
        session, amount_brl=payload.amount_brl, notes=payload.notes
    )

    if run and settings.contribution_night_run and not now:
        contribution.scheduled_for = contribution_service.next_night_run()
        session.add(contribution)
        session.commit()
        session.refresh(contribution)
        logger.info(
            "contribution_scheduled",
            contribution_id=str(contribution.id),
            scheduled_for=contribution.scheduled_for.isoformat(),
        )
    elif run:
        background_tasks.add_task(_run_analysis_bg, contribution.id)

    return _to_read(contribution, prompt_rows)


@router.post("/{contribution_id}/run", response_model=ContributionRead, status_code=202)
async def run_contribution_analysis(
    contribution_id: UUID,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> ContributionRead:
    """Trigger the headless Claude analysis in the background.

    Poll ``GET /{id}`` to watch progress: prompt responses fill in one by one
    and ``final_summary`` is set when the run completes.
    """
    contribution = session.get(Contribution, contribution_id)
    if contribution is None:
        raise HTTPException(status_code=404, detail="Contribution not found")
    # 409 only when a LIVE process holds the run lock. A stale IN_PROGRESS row
    # (crash mid-run) must stay re-runnable, or the contribution bricks forever.
    if analysis_runner.is_run_active(contribution_id):
        raise HTTPException(status_code=409, detail="Analysis already running")

    background_tasks.add_task(_run_analysis_bg, contribution_id)

    prompts = list(
        session.exec(
            select(ContributionPrompt).where(ContributionPrompt.contribution_id == contribution_id)
        ).all()
    )
    return _to_read(contribution, prompts)


@router.get("/{contribution_id}", response_model=ContributionRead)
async def get_contribution(
    contribution_id: UUID, session: Session = Depends(get_session)
) -> ContributionRead:
    contribution = session.get(Contribution, contribution_id)
    if contribution is None:
        raise HTTPException(status_code=404, detail="Contribution not found")
    prompts = list(
        session.exec(
            select(ContributionPrompt).where(ContributionPrompt.contribution_id == contribution_id)
        ).all()
    )
    return _to_read(contribution, prompts)


@router.post("/{contribution_id}/prompts/{prompt_key}/response", response_model=PromptRead)
async def save_prompt_response(
    contribution_id: UUID,
    prompt_key: PromptKey,
    payload: PromptResponseCreate,
    session: Session = Depends(get_session),
) -> PromptRead:
    contribution = session.get(Contribution, contribution_id)
    if contribution is None:
        raise HTTPException(status_code=404, detail="Contribution not found")

    prompt = session.exec(
        select(ContributionPrompt)
        .where(ContributionPrompt.contribution_id == contribution_id)
        .where(ContributionPrompt.prompt_key == prompt_key)
    ).first()
    if prompt is None:
        raise HTTPException(status_code=404, detail="Prompt not found")

    prompt.response = payload.response
    prompt.responded_at = datetime.now(UTC)
    session.add(prompt)

    if contribution.status == ContributionStatus.READY:
        contribution.status = ContributionStatus.IN_PROGRESS
        session.add(contribution)

    session.commit()
    session.refresh(prompt)

    return PromptRead.model_validate(prompt, from_attributes=True)


@router.post("/{contribution_id}/finalize", response_model=ContributionRead)
async def finalize_contribution(
    contribution_id: UUID,
    payload: ContributionFinalize,
    session: Session = Depends(get_session),
) -> ContributionRead:
    contribution = session.get(Contribution, contribution_id)
    if contribution is None:
        raise HTTPException(status_code=404, detail="Contribution not found")

    contribution.status = ContributionStatus.COMPLETED
    contribution.completed_at = datetime.now(UTC)
    if payload.final_summary:
        contribution.final_summary = payload.final_summary
    session.add(contribution)
    session.commit()
    session.refresh(contribution)

    prompts = list(
        session.exec(
            select(ContributionPrompt).where(ContributionPrompt.contribution_id == contribution_id)
        ).all()
    )
    return _to_read(contribution, prompts)


@router.delete("/{contribution_id}", status_code=204)
async def delete_contribution(
    contribution_id: UUID, session: Session = Depends(get_session)
) -> None:
    contribution = session.get(Contribution, contribution_id)
    if contribution is None:
        raise HTTPException(status_code=404, detail="Contribution not found")
    if analysis_runner.is_run_active(contribution_id):
        raise HTTPException(
            status_code=409,
            detail="Análise em andamento para este aporte — aguarde terminar antes de apagar.",
        )
    executed_order = session.exec(
        select(Order)
        .where(Order.contribution_id == contribution_id)
        .where(Order.status == OrderStatus.EXECUTED)
        .limit(1)
    ).first()
    if executed_order is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Este aporte tem ordem EXECUTADA — apagá-lo removeria o vínculo "
                "recomendação → posição do track record."
            ),
        )
    # Children first, with an explicit flush: the models define no ORM
    # relationships, so SQLAlchemy won't order these deletes on its own — and
    # with PRAGMA foreign_keys=ON an unordered flush violates the FK.
    for prompt in session.exec(
        select(ContributionPrompt).where(ContributionPrompt.contribution_id == contribution_id)
    ).all():
        session.delete(prompt)
    for order in session.exec(select(Order).where(Order.contribution_id == contribution_id)).all():
        session.delete(order)
    session.flush()
    session.delete(contribution)
    session.commit()
