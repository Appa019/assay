"""Cash flow forecast — committed money in, committed money out, per month.

Only what is REGISTERED counts: ledger lines already written (including the
future installments a card purchase created) plus the monthly commitments in
``recurrence``. No historical average is ever mixed in, so every number on
the screen can be traced to a row the client can point at. The consequence is
deliberate: variable spending (mercado, ifood) is absent, which makes the
projected leftover a CEILING, not an expectation.

Three rules hold the arithmetic together:

1. **One formula** — ``total = real entries + recurrences not yet fulfilled``
   — serves the current month and every future one.
2. **Competência, never caixa.** An installment counts on its own
   ``occurred_on``; a card invoice is a legend on the month it falls due, not
   an outflow, or the same purchase would be booked twice.
3. **Benefit wallets stay out.** VR/VA can only buy food and are never
   investable leftover.
"""

from datetime import date

from sqlmodel import Session

from app.models.cashflow import CashflowEntry, CashflowKind, CashflowWallet
from app.models.credit_card import CreditCard
from app.models.recurrence import Recurrence
from app.schemas.forecast import Forecast, ForecastInvoice, ForecastLine, ForecastMonth
from app.services import card_service, cashflow_service, recurrence_service

_MAX_MONTHS = 24


def _entry_line(entry: CashflowEntry, card_name: str | None) -> ForecastLine:
    return ForecastLine(
        # A future-dated row is a commitment, not something that happened; an
        # installment is always flagged as such so the screen can show "3/10".
        origin="installment" if entry.installment_no is not None else "realized",
        kind=entry.kind,
        label=entry.description or entry.category,
        category=entry.category,
        amount_brl=round(float(entry.amount_brl), 2),
        day=entry.occurred_on.day,
        card_name=card_name,
        installment_no=entry.installment_no,
        installment_count=entry.installment_count,
    )


def _recurrence_line(recurrence: Recurrence, day: date, card_name: str | None) -> ForecastLine:
    return ForecastLine(
        origin="recurring",
        kind=recurrence.kind,
        label=recurrence.description or recurrence.category,
        category=recurrence.category,
        amount_brl=round(float(recurrence.amount_brl), 2),
        day=day.day,
        card_name=card_name,
        recurrence_id=recurrence.id,
    )


def _fulfilled_by(recurrence: Recurrence, candidates: list[CashflowEntry]) -> CashflowEntry | None:
    """The ledger line that already paid this commitment, if any.

    Same kind and same (normalized) category, closest amount first: two
    subscriptions in one category with only one of them registered must cancel
    the matching one, not the cheaper one at random. Installment rows are
    never candidates — a parcelled purchase filed under "lazer" would
    otherwise silently cancel the monthly gym fee.
    """
    matches = [
        entry
        for entry in candidates
        if entry.kind == recurrence.kind and entry.category == recurrence.category
    ]
    if not matches:
        return None
    target = float(recurrence.amount_brl)
    return min(matches, key=lambda entry: abs(float(entry.amount_brl) - target))


def _invoices_due_in(
    session: Session, cards: list[CreditCard], year: int, month: int, *, today: date
) -> list[ForecastInvoice]:
    """Invoices whose due date falls in this month — legend only.

    An invoice closing in month X falls due in X or X+1, so only those two
    cycles can land here. Empty invoices are dropped: a card with nothing on
    it has no bill worth naming.
    """
    out: list[ForecastInvoice] = []
    for card in cards:
        for delta in (0, -1):
            cycle_year, cycle_month = card_service.shift_month(year, month, delta)
            invoice = card_service.build_invoice(
                session, card, cycle_year, cycle_month, today=today
            )
            if invoice.due_on.year == year and invoice.due_on.month == month:
                if invoice.total_brl > 0:
                    out.append(
                        ForecastInvoice(
                            card_id=card.id,
                            card_name=card.name,
                            closes_on=invoice.closes_on,
                            due_on=invoice.due_on,
                            total_brl=invoice.total_brl,
                        )
                    )
                break
    return sorted(out, key=lambda invoice: invoice.due_on)


def _build_month(
    session: Session,
    year: int,
    month: int,
    *,
    today: date,
    cards: list[CreditCard],
) -> ForecastMonth:
    key = f"{year}-{month:02d}"
    card_names = {card.id: card.name for card in cards}
    entries = cashflow_service.list_entries(
        session, month=key, wallet=CashflowWallet.CONTA, limit=10_000
    )

    lines = [_entry_line(entry, card_names.get(entry.card_id)) for entry in entries]
    realized = {CashflowKind.INCOME: 0.0, CashflowKind.EXPENSE: 0.0}
    pending = {CashflowKind.INCOME: 0.0, CashflowKind.EXPENSE: 0.0}
    for entry in entries:
        bucket = realized if entry.occurred_on <= today else pending
        bucket[entry.kind] += float(entry.amount_brl)

    # Only plain rows can settle a commitment; installments never do.
    unclaimed = [entry for entry in entries if entry.installment_no is None]
    for recurrence, day in recurrence_service.occurrences_in_month(session, year, month):
        if recurrence.wallet != CashflowWallet.CONTA:
            continue
        settled = _fulfilled_by(recurrence, unclaimed)
        if settled is not None:
            unclaimed.remove(settled)  # one entry settles one commitment
            continue
        lines.append(_recurrence_line(recurrence, day, card_names.get(recurrence.card_id)))
        pending[recurrence.kind] += float(recurrence.amount_brl)

    income = round(realized[CashflowKind.INCOME] + pending[CashflowKind.INCOME], 2)
    expense = round(realized[CashflowKind.EXPENSE] + pending[CashflowKind.EXPENSE], 2)
    return ForecastMonth(
        month=key,
        is_current=(year, month) == (today.year, today.month),
        income_brl=income,
        expense_brl=expense,
        net_brl=round(income - expense, 2),
        realized_income_brl=round(realized[CashflowKind.INCOME], 2),
        realized_expense_brl=round(realized[CashflowKind.EXPENSE], 2),
        pending_income_brl=round(pending[CashflowKind.INCOME], 2),
        pending_expense_brl=round(pending[CashflowKind.EXPENSE], 2),
        lines=sorted(lines, key=lambda line: (line.day, line.label)),
        invoices=_invoices_due_in(session, cards, year, month, today=today),
    )


def build_forecast(session: Session, *, months: int = 6, today: date | None = None) -> Forecast:
    """The next ``months`` months of committed money, current month first."""
    today = today or date.today()
    months = max(1, min(months, _MAX_MONTHS))
    cards = card_service.list_cards(session)

    out: list[ForecastMonth] = []
    for offset in range(months):
        year, month = card_service.shift_month(today.year, today.month, offset)
        out.append(_build_month(session, year, month, today=today, cards=cards))

    income = round(sum(item.income_brl for item in out), 2)
    expense = round(sum(item.expense_brl for item in out), 2)
    return Forecast(
        generated_on=today,
        months=out,
        total_income_brl=income,
        total_expense_brl=expense,
        total_net_brl=round(income - expense, 2),
        has_commitments=any(item.lines for item in out),
    )
