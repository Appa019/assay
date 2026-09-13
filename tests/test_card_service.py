"""Credit cards: the single-default rule and how a ledger entry resolves to a
card (auto / explicit off-card / by name)."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlmodel import Session

from app.models.cashflow import CashflowEntry, CashflowKind, CashflowWallet
from app.schemas.card import CardCreate, CardUpdate
from app.services import card_service


def _card(
    name: str = "Nubank", closing: int = 25, due: int = 3, default: bool = False
) -> CardCreate:
    return CardCreate(name=name, closing_day=closing, due_day=due, is_default=default)


# --- CRUD + default ------------------------------------------------------------


def test_first_card_becomes_default_even_if_not_asked(session: Session) -> None:
    card = card_service.create_card(session, _card(default=False))
    assert card.is_default is True


def test_second_default_demotes_the_first(session: Session) -> None:
    first = card_service.create_card(session, _card("Nubank"))
    second = card_service.create_card(session, _card("Itaú", default=True))
    session.refresh(first)
    assert first.is_default is False
    assert second.is_default is True
    assert card_service.default_card(session).id == second.id


def test_blank_name_is_rejected_by_the_schema() -> None:
    with pytest.raises(ValidationError):
        CardCreate(name="   ", closing_day=1, due_day=2)


def test_duplicate_name_is_rejected_after_fold(session: Session) -> None:
    card_service.create_card(session, _card("Itaú"))
    with pytest.raises(card_service.CardNameTakenError):
        card_service.create_card(session, _card("  itau "))


def test_update_promotes_and_refuses_to_unset_the_only_default(session: Session) -> None:
    first = card_service.create_card(session, _card("Nubank"))
    second = card_service.create_card(session, _card("Itaú"))
    card_service.update_card(session, second.id, CardUpdate(is_default=True))
    session.refresh(first)
    assert first.is_default is False
    with pytest.raises(card_service.CardRuleError):
        card_service.update_card(session, second.id, CardUpdate(is_default=False))


def test_update_changes_days_and_name(session: Session) -> None:
    card = card_service.create_card(session, _card())
    updated = card_service.update_card(
        session, card.id, CardUpdate(name="Nu", closing_day=10, due_day=17)
    )
    assert (updated.name, updated.closing_day, updated.due_day) == ("Nu", 10, 17)


def test_delete_refuses_a_card_with_entries(session: Session) -> None:
    card = card_service.create_card(session, _card())
    session.add(
        CashflowEntry(
            kind=CashflowKind.EXPENSE,
            amount_brl=Decimal("10"),
            occurred_on=date(2026, 9, 1),
            card_id=card.id,
        )
    )
    session.commit()
    with pytest.raises(card_service.CardInUseError):
        card_service.delete_card(session, card.id)


def test_delete_default_promotes_the_oldest_remaining(session: Session) -> None:
    first = card_service.create_card(session, _card("Nubank"))
    second = card_service.create_card(session, _card("Itaú"))
    third = card_service.create_card(session, _card("XP"))
    card_service.delete_card(session, first.id)
    session.refresh(second)
    session.refresh(third)
    assert second.is_default is True
    assert third.is_default is False


def test_get_unknown_card_raises(session: Session) -> None:
    from uuid import uuid4

    with pytest.raises(card_service.CardNotFoundError):
        card_service.get_card(session, uuid4())


# --- resolve_card ----------------------------------------------------------------


def test_resolve_auto_uses_default_for_expense_from_conta(session: Session) -> None:
    card = card_service.create_card(session, _card())
    resolved = card_service.resolve_card(
        session, None, kind=CashflowKind.EXPENSE, wallet=CashflowWallet.CONTA
    )
    assert resolved is not None and resolved.id == card.id


@pytest.mark.parametrize("raw", ["cartão", "crédito", "cartão de crédito", "padrão"])
def test_resolve_generic_card_word_uses_default_for_expense_from_conta(
    session: Session, raw: str
) -> None:
    """A generic card word names "a card" without naming ONE — it must resolve
    to the default card like "auto", never raise as an unknown card."""
    card = card_service.create_card(session, _card())
    resolved = card_service.resolve_card(
        session, raw, kind=CashflowKind.EXPENSE, wallet=CashflowWallet.CONTA
    )
    assert resolved is not None and resolved.id == card.id


def test_resolve_generic_card_word_never_puts_income_on_a_card(session: Session) -> None:
    card_service.create_card(session, _card())
    assert (
        card_service.resolve_card(
            session, "cartão", kind=CashflowKind.INCOME, wallet=CashflowWallet.CONTA
        )
        is None
    )


@pytest.mark.parametrize("raw", [None, "", "auto"])
def test_resolve_auto_without_cards_is_none(session: Session, raw: str | None) -> None:
    assert (
        card_service.resolve_card(
            session, raw, kind=CashflowKind.EXPENSE, wallet=CashflowWallet.CONTA
        )
        is None
    )


@pytest.mark.parametrize(
    ("kind", "wallet"),
    [
        (CashflowKind.INCOME, CashflowWallet.CONTA),
        (CashflowKind.EXPENSE, CashflowWallet.VR),
        (CashflowKind.EXPENSE, CashflowWallet.VA),
    ],
)
def test_resolve_auto_never_puts_income_or_benefit_on_a_card(
    session: Session, kind: CashflowKind, wallet: CashflowWallet
) -> None:
    card_service.create_card(session, _card())
    assert card_service.resolve_card(session, None, kind=kind, wallet=wallet) is None


@pytest.mark.parametrize("raw", ["none", "nenhum", "PIX", "débito", "dinheiro", "conta"])
def test_resolve_explicit_off_card_words(session: Session, raw: str) -> None:
    card_service.create_card(session, _card())
    assert (
        card_service.resolve_card(
            session, raw, kind=CashflowKind.EXPENSE, wallet=CashflowWallet.CONTA
        )
        is None
    )


def test_resolve_by_name_folds_case_and_accents(session: Session) -> None:
    card_service.create_card(session, _card("Nubank"))
    itau = card_service.create_card(session, _card("Itaú"))
    resolved = card_service.resolve_card(
        session, "ITAU", kind=CashflowKind.EXPENSE, wallet=CashflowWallet.CONTA
    )
    assert resolved is not None and resolved.id == itau.id


def test_resolve_unknown_name_raises_instead_of_falling_back(session: Session) -> None:
    card_service.create_card(session, _card())
    with pytest.raises(card_service.UnknownCardError):
        card_service.resolve_card(
            session, "bradesco", kind=CashflowKind.EXPENSE, wallet=CashflowWallet.CONTA
        )


def test_resolve_named_card_on_income_or_benefit_is_a_rule_error(session: Session) -> None:
    card_service.create_card(session, _card())
    with pytest.raises(card_service.CardRuleError):
        card_service.resolve_card(
            session, "nubank", kind=CashflowKind.INCOME, wallet=CashflowWallet.CONTA
        )
    with pytest.raises(card_service.CardRuleError):
        card_service.resolve_card(
            session, "nubank", kind=CashflowKind.EXPENSE, wallet=CashflowWallet.VR
        )


# --- invoices --------------------------------------------------------------------


def _spend(session: Session, card_id, amount: str, on: date) -> None:  # noqa: ANN001
    session.add(
        CashflowEntry(
            kind=CashflowKind.EXPENSE, amount_brl=Decimal(amount), occurred_on=on, card_id=card_id
        )
    )
    session.commit()


def test_open_invoice_window_and_due_date(session: Session) -> None:
    card = card_service.create_card(session, _card(closing=25, due=3))
    window = card_service.invoice_window(card, 2026, 9)
    assert window.period_start == date(2026, 8, 26)
    assert window.period_end == date(2026, 9, 25)
    assert window.closes_on == date(2026, 9, 25)
    assert window.due_on == date(2026, 10, 3)


def test_due_day_after_closing_day_stays_in_the_same_month(session: Session) -> None:
    card = card_service.create_card(session, _card(closing=5, due=15))
    assert card_service.invoice_window(card, 2026, 9).due_on == date(2026, 9, 15)


def test_closing_day_31_clamps_to_short_months(session: Session) -> None:
    card = card_service.create_card(session, _card(closing=31, due=10))
    window = card_service.invoice_window(card, 2026, 2)
    assert window.closes_on == date(2026, 2, 28)
    assert window.period_start == date(2026, 2, 1)  # Jan 31 + 1 day
    assert window.due_on == date(2026, 3, 10)


def test_open_invoice_rolls_over_the_year(session: Session) -> None:
    card = card_service.create_card(session, _card(closing=25, due=3))
    assert card_service.open_invoice_month(card, date(2026, 12, 28)) == (2027, 1)
    window = card_service.invoice_window(card, 2027, 1)
    assert window.period_start == date(2026, 12, 26)
    assert window.due_on == date(2027, 2, 3)


def test_invoice_status_by_date(session: Session) -> None:
    card = card_service.create_card(session, _card(closing=25, due=3))
    build = lambda today: card_service.build_invoice(session, card, 2026, 9, today=today)  # noqa: E731
    assert build(date(2026, 9, 25)).status == "open"  # closing day itself still open
    assert build(date(2026, 9, 26)).status == "closed"
    assert build(date(2026, 10, 3)).status == "closed"
    assert build(date(2026, 10, 4)).status == "past"


def test_invoice_totals_only_count_this_card_inside_the_window(session: Session) -> None:
    card = card_service.create_card(session, _card(closing=25, due=3))
    other = card_service.create_card(session, _card("Itaú", closing=25, due=3))
    _spend(session, card.id, "100.00", date(2026, 8, 26))  # first day of the window
    _spend(session, card.id, "50.50", date(2026, 9, 25))  # last day
    _spend(session, card.id, "999.00", date(2026, 8, 25))  # previous invoice
    _spend(session, other.id, "10.00", date(2026, 9, 10))  # other card
    _spend(session, None, "20.00", date(2026, 9, 10))  # pix
    invoice = card_service.build_invoice(session, card, 2026, 9, today=date(2026, 9, 12))
    assert invoice.total_brl == 150.5
    assert invoice.entries == 2


def test_invoices_end_on_the_open_one_oldest_first(session: Session) -> None:
    card = card_service.create_card(session, _card(closing=25, due=3))
    history = card_service.invoices(session, card, today=date(2026, 9, 12), months=3)
    assert [i.closes_on for i in history] == [
        date(2026, 7, 25),
        date(2026, 8, 25),
        date(2026, 9, 25),
    ]
    assert [i.status for i in history] == ["past", "past", "open"]


def test_card_summaries_pair_open_with_last_closed(session: Session) -> None:
    card = card_service.create_card(session, _card(closing=25, due=3))
    _spend(session, card.id, "80.00", date(2026, 9, 1))  # September invoice
    summaries = card_service.card_summaries(session, today=date(2026, 9, 26))
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.open_invoice.closes_on == date(2026, 10, 25)
    assert summary.open_invoice.total_brl == 0.0
    assert summary.last_closed_invoice is not None
    assert summary.last_closed_invoice.closes_on == date(2026, 9, 25)
    assert summary.last_closed_invoice.total_brl == 80.0
    assert summary.last_closed_invoice.status == "closed"


def test_card_summaries_hide_an_empty_previous_invoice(session: Session) -> None:
    card_service.create_card(session, _card(closing=25, due=3))
    summary = card_service.card_summaries(session, today=date(2026, 9, 12))[0]
    assert summary.last_closed_invoice is None
