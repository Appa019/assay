from datetime import date
from decimal import Decimal

from sqlmodel import Session

from app.models.cashflow import CashflowKind, CashflowSource
from app.schemas.card import CardCreate
from app.schemas.cashflow import CashflowCreate
from app.schemas.recurrence import RecurrenceCreate
from app.services import cashflow_service, forecast_service, recurrence_service

TODAY = date(2026, 9, 13)


def _month(forecast, key: str):  # noqa: ANN001, ANN202 — test helper
    return next(m for m in forecast.months if m.month == key)


def _salary(session: Session, amount: str = "8000") -> None:
    recurrence_service.create(
        session,
        RecurrenceCreate(
            kind=CashflowKind.INCOME,
            amount_brl=Decimal(amount),
            category="salario",
            description="salário",
            day_of_month=5,
            starts_on=date(2026, 1, 1),
        ),
    )


def _rent(session: Session, amount: str = "2200", **over: object) -> None:
    payload: dict[str, object] = {
        "kind": CashflowKind.EXPENSE,
        "amount_brl": Decimal(amount),
        "category": "moradia",
        "description": "aluguel",
        "day_of_month": 10,
        "starts_on": date(2026, 1, 1),
    }
    payload.update(over)
    recurrence_service.create(session, RecurrenceCreate(**payload))  # type: ignore[arg-type]


def _entry(
    session: Session,
    *,
    kind: CashflowKind = CashflowKind.EXPENSE,
    amount: str = "100",
    category: str = "mercado",
    description: str | None = None,
    occurred_on: date = TODAY,
    wallet: str = "conta",
    card: str | None = "none",
    installments: int = 1,
) -> None:
    cashflow_service.add_entry(
        session,
        CashflowCreate(
            kind=kind,
            amount_brl=Decimal(amount),
            category=category,
            description=description,
            occurred_on=occurred_on,
            source=CashflowSource.API,
            wallet=wallet,
            card=card,
            installments=installments,
        ),
    )


def test_empty_ledger_reports_no_commitments(session: Session) -> None:
    forecast = forecast_service.build_forecast(session, months=6, today=TODAY)
    assert forecast.has_commitments is False
    assert len(forecast.months) == 6
    assert forecast.months[0].month == "2026-09"
    assert forecast.months[-1].month == "2027-02"
    assert forecast.total_net_brl == 0.0


def test_recurrences_fill_every_month_of_the_horizon(session: Session) -> None:
    _salary(session)
    _rent(session)
    forecast = forecast_service.build_forecast(session, months=6, today=TODAY)
    assert forecast.has_commitments is True
    for month in forecast.months:
        assert month.income_brl == 8000.0
        assert month.expense_brl == 2200.0
        assert month.net_brl == 5800.0
    assert forecast.total_income_brl == 48000.0
    assert forecast.total_net_brl == 34800.0


def test_registered_salary_is_not_counted_twice(session: Session) -> None:
    _salary(session)
    _entry(
        session,
        kind=CashflowKind.INCOME,
        amount="8150",
        category="salario",
        occurred_on=date(2026, 9, 5),
    )
    current = _month(forecast_service.build_forecast(session, months=2, today=TODAY), "2026-09")
    # The real amount wins — the recurrence was an estimate of THIS entry.
    assert current.income_brl == 8150.0
    assert current.realized_income_brl == 8150.0
    assert current.pending_income_brl == 0.0
    assert [line.origin for line in current.lines if line.kind == CashflowKind.INCOME] == [
        "realized"
    ]
    # Next month still expects the recurrence.
    nxt = _month(forecast_service.build_forecast(session, months=2, today=TODAY), "2026-10")
    assert nxt.income_brl == 8000.0
    assert nxt.pending_income_brl == 8000.0


def test_one_of_two_same_category_recurrences_lands(session: Session) -> None:
    _rent(session, amount="50", category="assinatura", description="netflix", day_of_month=8)
    _rent(session, amount="22", category="assinatura", description="spotify", day_of_month=8)
    _entry(session, amount="50", category="assinatura", occurred_on=date(2026, 9, 8))
    current = _month(forecast_service.build_forecast(session, months=1, today=TODAY), "2026-09")
    assert current.expense_brl == 72.0  # 50 real + 22 still expected
    origins = sorted(line.origin for line in current.lines)
    assert origins == ["realized", "recurring"]


def test_installment_does_not_cancel_a_recurrence_of_the_same_category(
    session: Session,
) -> None:
    _rent(session, amount="120", category="lazer", description="academia", day_of_month=10)
    from app.services import card_service

    card_service.create_card(session, CardCreate(name="Nubank", closing_day=25, due_day=5))
    _entry(
        session,
        amount="300",
        category="lazer",
        occurred_on=date(2026, 9, 20),
        card="Nubank",
        installments=3,
    )
    current = _month(forecast_service.build_forecast(session, months=1, today=TODAY), "2026-09")
    assert current.expense_brl == 220.0  # 100 installment + 120 gym, neither cancelled
    assert sorted(line.origin for line in current.lines) == ["installment", "recurring"]


def test_future_installments_are_committed_outflow(session: Session) -> None:
    from app.services import card_service

    card_service.create_card(session, CardCreate(name="Nubank", closing_day=25, due_day=5))
    _entry(
        session,
        amount="3000",
        category="eletronicos",
        description="tv",
        occurred_on=date(2026, 9, 20),
        card="Nubank",
        installments=3,
    )
    forecast = forecast_service.build_forecast(session, months=6, today=TODAY)
    assert [m.expense_brl for m in forecast.months] == [1000.0, 1000.0, 1000.0, 0.0, 0.0, 0.0]
    line = _month(forecast, "2026-10").lines[0]
    assert line.origin == "installment"
    assert (line.installment_no, line.installment_count) == (2, 3)
    assert line.card_name == "Nubank"


def test_ended_recurrence_frees_the_following_months(session: Session) -> None:
    _rent(session, amount="900", category="educacao", ends_on=date(2026, 11, 30))
    forecast = forecast_service.build_forecast(session, months=4, today=TODAY)
    assert [m.expense_brl for m in forecast.months] == [900.0, 900.0, 900.0, 0.0]


def test_benefit_wallets_stay_out_of_the_flow(session: Session) -> None:
    _entry(session, amount="40", category="restaurante", wallet="vr")
    recurrence_service.create(
        session,
        RecurrenceCreate(
            kind=CashflowKind.INCOME,
            amount_brl=Decimal("800"),
            category="reembolso",
            day_of_month=1,
            wallet="vr",
            starts_on=date(2026, 1, 1),
        ),
    )
    forecast = forecast_service.build_forecast(session, months=1, today=TODAY)
    assert forecast.months[0].expense_brl == 0.0
    assert forecast.months[0].income_brl == 0.0
    assert forecast.has_commitments is False


def test_realized_and_pending_split_on_the_current_month(session: Session) -> None:
    _rent(session, amount="500", category="moradia", day_of_month=25)
    _entry(session, amount="80", category="mercado", occurred_on=date(2026, 9, 2))
    current = _month(forecast_service.build_forecast(session, months=1, today=TODAY), "2026-09")
    assert current.is_current is True
    assert current.realized_expense_brl == 80.0
    assert current.pending_expense_brl == 500.0
    assert current.expense_brl == 580.0


def test_invoice_is_a_legend_not_an_outflow(session: Session) -> None:
    from app.services import card_service

    card_service.create_card(session, CardCreate(name="Nubank", closing_day=25, due_day=5))
    _entry(
        session,
        amount="600",
        category="mercado",
        occurred_on=date(2026, 9, 20),
        card="Nubank",
    )
    forecast = forecast_service.build_forecast(session, months=2, today=TODAY)
    september = _month(forecast, "2026-09")
    october = _month(forecast, "2026-10")
    # The purchase counts in September (competência) and never again.
    assert september.expense_brl == 600.0
    assert october.expense_brl == 0.0
    # October only carries the legend of the invoice falling due on the 5th.
    invoice = october.invoices[0]
    assert invoice.card_name == "Nubank"
    assert invoice.total_brl == 600.0
    assert invoice.due_on == date(2026, 10, 5)
    assert september.invoices == []
