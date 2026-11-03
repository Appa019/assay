"""Night review timers never wait for the usage window in-process (that would carry
the committee past 03:00): they run fail-fast, and a limit is a deferral to the
next night, not a failure (D53)."""

import sys
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session

from app.models.notification import NotificationLevel
from app.services import analysis_runner, notification_service, review_service

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_cadence  # noqa: E402
import weekly_review  # noqa: E402

_LOT = {
    "ticker": "BTC",
    "asset_class": "crypto",
    "quantity": 1,
    "avg_price": 100,
    "total_value": 100,
}


async def _no_macro() -> dict[str, Any]:
    return {}


def _notes(monkeypatch: pytest.MonkeyPatch, module: Any) -> list[tuple[str, Any]]:
    notes: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        module.notification_center,
        "notify",
        lambda text, **kw: notes.append((text, kw.get("level"))),
    )
    return notes


def test_flag_shortens_the_limit_wait(monkeypatch: pytest.MonkeyPatch, session: Session) -> None:
    seen: list[Any] = []

    def fake_chain(*_a: Any, **kwargs: Any) -> None:
        seen.append(kwargs["limit_backoff"])
        raise analysis_runner.LimitError("limite")

    monkeypatch.setattr(analysis_runner, "run_chain", fake_chain)
    monkeypatch.setattr(review_service, "has_reviewable_data", lambda _s: True)
    with pytest.raises(analysis_runner.LimitError):
        review_service.run_weekly_review(
            session, macro_ctx={}, notify=False, fail_fast_on_limit=True
        )
    with pytest.raises(analysis_runner.LimitError):
        review_service.run_maturity_review(
            session, [_LOT], macro_ctx={}, notify=False, fail_fast_on_limit=True
        )
    with pytest.raises(analysis_runner.LimitError):
        review_service.run_maturity_review(session, [_LOT], macro_ctx={})
    # Fail-fast = one 2-min retry; the default keeps waiting for the reset.
    assert seen == [[120], [120], None]


def test_weekly_timer_defers_on_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_review(_session: Any, **kwargs: Any) -> None:
        calls.append(kwargs)
        raise analysis_runner.LimitError("limite")

    monkeypatch.setattr(sys, "argv", ["weekly_review.py"])
    monkeypatch.setattr(weekly_review, "_is_due", lambda _s: True)
    monkeypatch.setattr(review_service, "has_reviewable_data", lambda _s: True)
    monkeypatch.setattr(review_service, "fetch_macro", _no_macro)
    monkeypatch.setattr(review_service, "run_weekly_review", fake_review)
    notes = _notes(monkeypatch, weekly_review)

    assert weekly_review.main() == 0
    assert calls[0]["fail_fast_on_limit"] is True
    assert notes and notes[0][1] == NotificationLevel.WARNING
    assert "próxima madrugada" in notes[0][0]


@pytest.mark.parametrize(
    ("error", "warns"),
    [
        (analysis_runner.LimitError("limite"), True),
        (analysis_runner.RunBusyError("ocupado"), False),
    ],
)
def test_maturity_timer_defers_and_keeps_lots_pending(
    monkeypatch: pytest.MonkeyPatch, error: Exception, warns: bool
) -> None:
    calls: list[dict[str, Any]] = []
    marked: list[Any] = []

    def fake_review(_session: Any, _rows: Any, **kwargs: Any) -> None:
        calls.append(kwargs)
        raise error

    monkeypatch.setattr(
        notification_service, "pending_maturities", lambda _s: ([{"ticker": "BTC"}], ["k"])
    )
    monkeypatch.setattr(notification_service, "mark_maturities", marked.append)
    monkeypatch.setattr(review_service, "days_until_weekly_due", lambda _s: 6.0)
    monkeypatch.setattr(review_service, "fetch_macro", _no_macro)
    monkeypatch.setattr(review_service, "run_maturity_review", fake_review)
    notes = _notes(monkeypatch, check_cadence)

    assert check_cadence.main() == 0
    assert calls[0]["fail_fast_on_limit"] is True
    assert marked == []  # tomorrow's pass sees the same lots again
    assert [level for _, level in notes] == ([NotificationLevel.WARNING] if warns else [])
