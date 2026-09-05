"""Deterministic insight engine: projection math, the anomaly history guard,
dedupe/re-arm semantics and the weekly push budget with its digest queue.
Telegram is always mocked — nothing is ever sent for real."""

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlmodel import Session

from app.models.asset import Asset, AssetClass
from app.models.cashflow import CashflowEntry, CashflowKind
from app.services import insight_service

# Day 20 of a 31-day month: run-rate math stays exact (3000/20*31 = 4650).
TODAY = date(2026, 8, 20)
# Anomaly baseline window: the 12 full weeks before August = 2026-05-09..07-31.
BASELINE_START = date(2026, 5, 9)


@pytest.fixture()
def state_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "insights_state.json"
    monkeypatch.setattr(insight_service, "_STATE_PATH", path)
    return path


@pytest.fixture()
def notified(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []

    def _fake_notify(text: str, **_kwargs: object) -> object:
        sent.append(text)
        return object()

    monkeypatch.setattr(insight_service.notification_center, "notify", _fake_notify)
    return sent


def _add(
    session: Session,
    amount: str,
    *,
    on: date,
    kind: CashflowKind = CashflowKind.EXPENSE,
    category: str = "mercado",
) -> None:
    # Direct model insert: bypasses add_entry's duplicate window on purpose.
    session.add(
        CashflowEntry(kind=kind, amount_brl=Decimal(amount), category=category, occurred_on=on)
    )
    session.commit()


def _salary_history(session: Session, amount: str = "4000") -> None:
    """Three tracked prior months of income → average_monthly_income == amount."""
    for month in (5, 6, 7):
        _add(session, amount, kind=CashflowKind.INCOME, category="salario", on=date(2026, month, 5))


def _weekly_baseline(session: Session, category: str, amount: str, weeks: int) -> None:
    """One expense per week inside the anomaly baseline window, oldest first."""
    for k in range(weeks):
        _add(session, amount, category=category, on=BASELINE_START + timedelta(days=7 * k))


# --- rule 1: run-rate projection -----------------------------------------------


def test_projection_fires_with_exact_run_rate_math(
    session: Session, state_path: Path, notified: list[str]
) -> None:
    _salary_history(session)  # expected income: max(0, 4000) = 4000
    _add(session, "2000", on=date(2026, 8, 5), category="mercado")
    _add(session, "1000", on=date(2026, 8, 10), category="lazer")
    # 3000 spent in 20 days → 4650 projected over 31 days → 650 in the red.

    result = insight_service.run_daily(session, today=TODAY)

    assert len(notified) == 1
    assert result["sent"][0]["kind"] == "projection"
    text = notified[0]
    assert "agosto" in text
    assert "R$ 650,00" in text  # the projected deficit, to the cent
    assert "R$ 4.650,00" in text  # projected spend
    assert "R$ 4.000,00" in text  # expected income
    assert "mercado" in text  # the biggest category to hold back


def test_projection_quiet_when_month_projects_positive(
    session: Session, state_path: Path, notified: list[str]
) -> None:
    _salary_history(session)
    _add(session, "2000", on=date(2026, 8, 5))  # → 3100 projected < 4000 income

    result = insight_service.run_daily(session, today=TODAY)

    assert notified == []
    assert result["sent"] == [] and result["queued"] == []


def test_projection_quiet_on_expense_only_ledger(
    session: Session, state_path: Path, notified: list[str]
) -> None:
    """No income ever tracked → "in the red" is meaningless, never fire."""
    _add(session, "3000", on=date(2026, 8, 5))

    insight_service.run_daily(session, today=TODAY)

    assert notified == []


def test_projection_waits_for_minimum_elapsed_days(
    session: Session, state_path: Path, notified: list[str]
) -> None:
    """Day 3 run-rate (900/3*31 = 9300) would scream — but it is pure noise."""
    _salary_history(session)
    _add(session, "900", on=date(2026, 8, 2))

    insight_service.run_daily(session, today=date(2026, 8, 3))

    assert notified == []


def test_projection_dedupes_then_rearms_on_recrossing(
    session: Session, state_path: Path, notified: list[str]
) -> None:
    _salary_history(session)
    _add(session, "2000", on=date(2026, 8, 5), category="mercado")
    _add(session, "1000", on=date(2026, 8, 10), category="lazer")

    insight_service.run_daily(session, today=TODAY)
    insight_service.run_daily(session, today=TODAY)  # same crossing → deduped
    assert len(notified) == 1

    # Income lands: 5000 real > 4650 projected spend → back in band → re-arms.
    _add(session, "5000", kind=CashflowKind.INCOME, category="freela", on=date(2026, 8, 12))
    insight_service.run_daily(session, today=TODAY)
    assert len(notified) == 1
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["projection_fired"]["2026-08"] is False

    # Spending accelerates past the new income → a NEW crossing fires again.
    _add(session, "1000", on=date(2026, 8, 16), category="mercado")  # → 6200 projected
    insight_service.run_daily(session, today=TODAY)
    assert len(notified) == 2


# --- rule 2: category anomaly --------------------------------------------------


def test_anomaly_needs_six_weeks_of_category_history(
    session: Session, state_path: Path, notified: list[str]
) -> None:
    _salary_history(session, "10000")
    _add(session, "10000", kind=CashflowKind.INCOME, category="salario", on=date(2026, 8, 1))
    # Only 4 baseline weeks contain "lazer" → the guard must hold even though
    # the month-to-date spend is a massive outlier vs that thin baseline.
    for on in (date(2026, 5, 10), date(2026, 5, 24), date(2026, 6, 7), date(2026, 6, 21)):
        _add(session, "100", category="lazer", on=on)
    _add(session, "800", category="lazer", on=date(2026, 8, 10))

    result = insight_service.run_daily(session, today=TODAY)

    assert notified == []
    assert result["sent"] == [] and result["queued"] == []


def test_anomaly_fires_with_enough_history_and_dedupes(
    session: Session, state_path: Path, notified: list[str]
) -> None:
    _salary_history(session, "10000")
    _add(session, "10000", kind=CashflowKind.INCOME, category="salario", on=date(2026, 8, 1))
    _weekly_baseline(session, "mercado", "150", weeks=12)  # 1800/84 ≈ 21.43/day
    _add(session, "400", category="mercado", on=date(2026, 8, 5))
    _add(session, "300", category="mercado", on=date(2026, 8, 15))
    # 700 actual vs 428.57 expected at day 20 → +63% and +R$ 271 → fires.

    result = insight_service.run_daily(session, today=TODAY)
    assert len(notified) == 1
    assert result["sent"][0]["kind"] == "anomaly"
    assert "mercado" in notified[0]
    assert "R$ 700,00" in notified[0]

    insight_service.run_daily(session, today=TODAY)  # same month → deduped
    assert len(notified) == 1


def test_anomaly_thresholds_require_both_deviation_and_delta(session: Session) -> None:
    # transporte: 62% above baseline but only +R$ 92.86 → delta floor holds.
    _weekly_baseline(session, "transporte", "20", weeks=12)  # expected@20 ≈ 57.14
    _add(session, "150", category="transporte", on=date(2026, 8, 10))
    # moradia: +R$ 500 but only 25% above baseline → deviation floor holds.
    _weekly_baseline(session, "moradia", "700", weeks=12)  # expected@20 = 2000.00
    _add(session, "2500", category="moradia", on=date(2026, 8, 12))

    assert insight_service._evaluate_anomalies(session, TODAY) == []


# --- weekly budget + digest queue ----------------------------------------------


def test_weekly_budget_caps_pushes_and_queues_for_digest(
    session: Session, state_path: Path, notified: list[str]
) -> None:
    _salary_history(session, "10000")
    _add(session, "10000", kind=CashflowKind.INCOME, category="salario", on=date(2026, 8, 1))
    for category, spend, on in (
        ("mercado", "900", date(2026, 8, 5)),
        ("restaurante", "800", date(2026, 8, 6)),
        ("transporte", "700", date(2026, 8, 7)),
    ):
        _weekly_baseline(session, category, "150", weeks=12)
        _add(session, spend, category=category, on=on)

    result = insight_service.run_daily(session, today=TODAY)

    # Three anomalies triggered, sorted by delta: only two fit the weekly budget.
    assert len(notified) == 2
    assert "mercado" in notified[0] and "restaurante" in notified[1]
    assert len(result["queued"]) == 1
    assert "transporte" in result["queued"][0]["text"]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(state["queue"]) == 1
    assert state["week"]["sent"] == 2

    # The queued insight surfaces in the digest, alongside both money halves.
    digest = insight_service.build_weekly_digest(session, today=TODAY)
    assert digest is not None
    assert "transporte" in digest
    assert "Saldo do mês" in digest
    assert "Maiores gastos do mês" in digest

    # Marking the digest sent drains the queue and gates the week.
    assert insight_service.digest_already_sent(today=TODAY) is False
    insight_service.mark_digest_sent(today=TODAY)
    assert insight_service.digest_already_sent(today=TODAY) is True
    assert json.loads(state_path.read_text(encoding="utf-8"))["queue"] == []
    digest_after = insight_service.build_weekly_digest(session, today=TODAY)
    assert digest_after is not None and "fila" not in digest_after


def test_digest_none_when_month_ledger_is_empty(session: Session, state_path: Path) -> None:
    _add(session, "500", on=date(2026, 7, 10))  # previous month only

    assert insight_service.build_weekly_digest(session, today=TODAY) is None


def test_digest_includes_portfolio_total_only_when_assets_exist(
    session: Session, state_path: Path
) -> None:
    _add(session, "100", on=date(2026, 8, 3))

    digest = insight_service.build_weekly_digest(session, today=TODAY)
    assert digest is not None and "Patrimônio" not in digest

    session.add(
        Asset(
            ticker="PETR4",
            asset_class=AssetClass.STOCKS,
            quantity=Decimal("100"),
            avg_price=Decimal("38.50"),
            current_price=Decimal("40.00"),
        )
    )
    session.commit()
    digest = insight_service.build_weekly_digest(session, today=TODAY)
    assert digest is not None and "Patrimônio investido: R$ 4.000,00" in digest


# --- state resilience ----------------------------------------------------------


def test_malformed_state_file_never_crashes_the_run(
    session: Session, state_path: Path, notified: list[str]
) -> None:
    state_path.write_text("{ this is not json !", encoding="utf-8")
    _salary_history(session)
    _add(session, "3000", on=date(2026, 8, 5))

    result = insight_service.run_daily(session, today=TODAY)

    assert len(notified) == 1
    assert result["sent"][0]["kind"] == "projection"
    # The state file was rebuilt from scratch and is valid JSON again.
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["projection_fired"]["2026-08"] is True
