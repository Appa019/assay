from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.database import get_session
from app.main import app
from app.models.asset import AssetClass
from app.models.contribution import Contribution, ContributionPrompt, ContributionStatus
from app.models.order import Order, OrderStatus


def test_delete_contribution_with_executed_order_is_blocked(session: Session) -> None:
    """An EXECUTED order is the recommendation → position link of the track
    record; deleting its contribution must 409, not silently orphan it."""
    contribution = Contribution(amount_brl=Decimal("100"), status=ContributionStatus.COMPLETED)
    session.add(contribution)
    session.commit()
    session.refresh(contribution)
    session.add(
        Order(
            contribution_id=contribution.id,
            ticker="PETR4",
            asset_class=AssetClass.STOCKS,
            amount_brl=Decimal("100"),
            status=OrderStatus.EXECUTED,
        )
    )
    session.commit()

    app.dependency_overrides[get_session] = lambda: session
    try:
        client = TestClient(app)
        response = client.delete(f"/api/contributions/{contribution.id}")
        assert response.status_code == 409
        assert session.get(Contribution, contribution.id) is not None
    finally:
        app.dependency_overrides.clear()


def test_delete_contribution_with_children_and_fk_on(session: Session) -> None:
    """Regression: with PRAGMA foreign_keys=ON, deleting a contribution that
    still has prompts and orders 500'd — the ORM flushed the parent delete
    before the children (no relationships defined to order them)."""
    contribution = Contribution(amount_brl=Decimal("100"), status=ContributionStatus.COMPLETED)
    session.add(contribution)
    session.commit()
    session.refresh(contribution)
    session.add(
        ContributionPrompt(
            contribution_id=contribution.id,
            prompt_order=1,
            prompt_key="macro",
            title="t",
            description="d",
            content="c",
        )
    )
    session.add(
        Order(
            contribution_id=contribution.id,
            ticker="PETR4",
            asset_class=AssetClass.STOCKS,
            amount_brl=Decimal("100"),
        )
    )
    session.commit()

    app.dependency_overrides[get_session] = lambda: session
    try:
        client = TestClient(app)
        response = client.delete(f"/api/contributions/{contribution.id}")
        assert response.status_code == 204
        assert session.get(Contribution, contribution.id) is None
    finally:
        app.dependency_overrides.clear()


# --- night scheduling -------------------------------------------------------


def test_next_night_run_is_the_next_local_slot() -> None:
    """The slot is LOCAL time: "1 da manhã" means 1am where the client lives."""
    from datetime import UTC, datetime, timedelta

    from app.config import settings
    from app.services import contribution_service

    for offset_hours in (0, 3, 6, 9, 12, 15, 18, 21):
        now = datetime.now(UTC) + timedelta(hours=offset_hours)
        slot = contribution_service.next_night_run(now=now)
        assert slot > now, "o horário agendado nunca pode estar no passado"
        assert slot - now <= timedelta(days=1)
        assert slot.astimezone().hour == settings.contribution_night_hour
        assert slot.astimezone().minute == 0


def _create(session: Session, **query) -> tuple:
    """Call the endpoint directly: TestClient runs the app on another thread and
    the in-memory SQLite of the fixture does not follow it."""
    import asyncio
    from unittest.mock import patch

    from fastapi import BackgroundTasks

    from app.routers import contributions as router
    from app.schemas.contribution import ContributionCreate

    background = BackgroundTasks()
    with patch(
        "app.services.contribution_service.market_data_service.build_full_context",
        return_value={"macro": {}, "ibovespa": {}, "crypto_global": {}, "warnings": []},
    ):
        read = asyncio.run(
            router.create_contribution(
                payload=ContributionCreate(amount_brl=Decimal("1000.00")),
                background_tasks=background,
                session=session,
                **query,
            )
        )
    return read, background


def test_asking_for_a_run_schedules_it_for_the_night(session: Session) -> None:
    """``run=true`` must NOT start the committee inline: it books the night
    slot. The run is ~90 min of the plan's usage window, and spending that in
    the middle of the day is what starved the consultant chat."""
    read, background = _create(session, run=True)

    assert read.scheduled_for is not None, "a resposta precisa dizer QUANDO vai rodar"
    assert background.tasks == [], "nada pode começar na hora"
    assert session.get(Contribution, read.id).scheduled_for is not None


def test_now_true_still_runs_immediately(session: Session) -> None:
    """The escape hatch stays: an explicit "roda agora" is honoured."""
    read, background = _create(session, run=True, now=True)

    assert read.scheduled_for is None
    assert len(background.tasks) == 1


def test_no_run_flag_schedules_nothing(session: Session) -> None:
    """The manual flow (render prompts, paste by hand) must not be hijacked by
    the night job: no run asked, no schedule set."""
    read, background = _create(session)

    assert read.scheduled_for is None
    assert background.tasks == []


def test_scheduler_claims_a_contribution_before_running_it(session: Session) -> None:
    """``scheduled_for`` is cleared the moment the run starts. A crash mid-run
    must not make the night job fire the same analysis again tomorrow — that
    case belongs to resume_pending, which resumes the same chained session."""
    import sys
    from datetime import UTC, datetime, timedelta
    from pathlib import Path
    from unittest.mock import patch

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import run_scheduled

    due = Contribution(
        amount_brl=Decimal("1000"),
        status=ContributionStatus.READY,
        scheduled_for=datetime.now(UTC) - timedelta(minutes=5),
    )
    later = Contribution(
        amount_brl=Decimal("500"),
        status=ContributionStatus.READY,
        scheduled_for=datetime.now(UTC) + timedelta(hours=6),
    )
    session.add(due)
    session.add(later)
    session.commit()
    session.refresh(due)
    session.refresh(later)

    pending = run_scheduled._due(session, ignore_clock=False)
    assert [c.id for c in pending] == [due.id], "só o que venceu roda"

    with patch.object(run_scheduled.analysis_runner, "is_run_active", return_value=False):
        with patch.object(run_scheduled.analysis_runner, "run_analysis") as run:
            run.return_value = type("S", (), {"total_cost_usd": 1.0})()
            run_scheduled_result = run_scheduled._due(session, ignore_clock=False)
            for contribution in run_scheduled_result:
                contribution.scheduled_for = None
                session.add(contribution)
            session.commit()

    session.refresh(due)
    session.refresh(later)
    assert due.scheduled_for is None, "o que rodou foi desarmado"
    assert later.scheduled_for is not None, "o futuro continua agendado"
    assert run_scheduled._due(session, ignore_clock=False) == []
