from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlmodel import Session

from app.models.cashflow import CashflowKind, CashflowSource
from app.schemas.cashflow import CashflowCreate
from app.services import cashflow_service


def _entry(
    kind: CashflowKind = CashflowKind.EXPENSE,
    amount: str = "50.00",
    category: str = "mercado",
    occurred_on: date | None = None,
) -> CashflowCreate:
    return CashflowCreate(
        kind=kind,
        amount_brl=Decimal(amount),
        category=category,
        occurred_on=occurred_on,
        source=CashflowSource.BOT,
    )


def test_add_entry_normalizes_category_and_defaults_date(session: Session) -> None:
    entry = cashflow_service.add_entry(session, _entry(category="  Mercado "))
    assert entry.category == "mercado"
    assert entry.occurred_on == date.today()
    assert entry.source == CashflowSource.BOT


def test_add_entry_blank_category_falls_back_to_outros(session: Session) -> None:
    entry = cashflow_service.add_entry(session, _entry(category="   "))
    assert entry.category == "outros"


def test_list_entries_filters_by_month_and_kind(session: Session) -> None:
    cashflow_service.add_entry(session, _entry(occurred_on=date(2026, 7, 10)))
    cashflow_service.add_entry(
        session, _entry(kind=CashflowKind.INCOME, amount="1000", occurred_on=date(2026, 7, 31))
    )
    cashflow_service.add_entry(session, _entry(occurred_on=date(2026, 6, 30)))

    july = cashflow_service.list_entries(session, month="2026-07")
    assert len(july) == 2
    incomes = cashflow_service.list_entries(session, month="2026-07", kind=CashflowKind.INCOME)
    assert len(incomes) == 1
    assert incomes[0].kind == CashflowKind.INCOME


def test_list_entries_rejects_bad_month(session: Session) -> None:
    with pytest.raises(ValueError):
        cashflow_service.list_entries(session, month="2026-13")


def test_month_summary_totals_and_categories(session: Session) -> None:
    when = date(2026, 7, 15)
    cashflow_service.add_entry(session, _entry(amount="30", occurred_on=when))
    cashflow_service.add_entry(session, _entry(amount="20", occurred_on=when))
    cashflow_service.add_entry(
        session, _entry(amount="12.50", category="transporte", occurred_on=when)
    )
    cashflow_service.add_entry(
        session,
        _entry(kind=CashflowKind.INCOME, amount="1000", category="salario", occurred_on=when),
    )

    summ = cashflow_service.month_summary(session, "2026-07")
    assert summ.expense_brl == pytest.approx(62.50)
    assert summ.income_brl == pytest.approx(1000.0)
    assert summ.net_brl == pytest.approx(937.50)
    assert summ.entries == 4
    top = summ.by_category[0]
    assert (top.kind, top.category, top.total_brl) == (CashflowKind.INCOME, "salario", 1000.0)
    mercado = next(c for c in summ.by_category if c.category == "mercado")
    assert mercado.total_brl == pytest.approx(50.0)
    assert mercado.count == 2


def test_delete_entry_and_missing(session: Session) -> None:
    entry = cashflow_service.add_entry(session, _entry())
    cashflow_service.delete_entry(session, entry.id)
    assert cashflow_service.list_entries(session) == []
    with pytest.raises(cashflow_service.CashflowNotFoundError):
        cashflow_service.delete_entry(session, uuid4())
