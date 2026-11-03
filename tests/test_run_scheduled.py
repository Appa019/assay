"""The 01:00 job never waits for the usage window in-process (that would carry the
committee into the morning): it runs fail-fast, and a limit or a busy lock is a
deferral for the night-only resume timer, not a failure."""

import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.core.database import get_session, init_db
from app.models.contribution import Contribution, ContributionStatus
from app.models.notification import NotificationLevel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import run_scheduled  # noqa: E402


@pytest.fixture()
def due_contribution() -> Contribution:
    init_db()
    session = next(get_session())
    contribution = Contribution(
        amount_brl=Decimal("1000"),
        status=ContributionStatus.READY,
        scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
    )
    session.add(contribution)
    session.commit()
    session.refresh(contribution)
    yield contribution
    session.delete(contribution)
    session.commit()


@pytest.mark.parametrize(
    "error",
    [
        run_scheduled.analysis_runner.LimitError("limite"),
        run_scheduled.analysis_runner.RunBusyError("ocupado"),
    ],
)
def test_limit_or_busy_defers_without_failing(
    monkeypatch: pytest.MonkeyPatch, due_contribution: Contribution, error: Exception
) -> None:
    calls: list[dict[str, Any]] = []
    notes: list[tuple[str, Any]] = []

    def fake_run(_session: Any, _cid: Any, **kwargs: Any) -> None:
        calls.append(kwargs)
        raise error

    monkeypatch.setattr(sys, "argv", ["run_scheduled.py"])
    monkeypatch.setattr(run_scheduled.analysis_runner, "is_run_active", lambda _cid: False)
    monkeypatch.setattr(run_scheduled.analysis_runner, "run_analysis", fake_run)
    monkeypatch.setattr(
        run_scheduled.notification_center,
        "notify",
        lambda text, **kw: notes.append((text, kw["level"])),
    )

    assert run_scheduled.main() == 0
    assert calls[0]["fail_fast_on_limit"] is True
    assert notes and notes[0][1] == NotificationLevel.WARNING
    assert "próxima madrugada" in notes[0][0]


def test_a_real_failure_still_fails(
    monkeypatch: pytest.MonkeyPatch, due_contribution: Contribution
) -> None:
    def fake_run(*_a: Any, **_k: Any) -> None:
        raise run_scheduled.analysis_runner.AnalysisError("quebrou")

    monkeypatch.setattr(sys, "argv", ["run_scheduled.py"])
    monkeypatch.setattr(run_scheduled.analysis_runner, "is_run_active", lambda _cid: False)
    monkeypatch.setattr(run_scheduled.analysis_runner, "run_analysis", fake_run)
    levels: list[Any] = []
    monkeypatch.setattr(
        run_scheduled.notification_center, "notify", lambda _t, **kw: levels.append(kw["level"])
    )

    assert run_scheduled.main() == 1
    assert levels == [NotificationLevel.ERROR]
