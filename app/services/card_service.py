"""Credit cards and their invoices.

Cards are configuration the client owns (name, closing day, due day). Invoices
are NEVER stored: every read recomputes them from the card and the ledger
entries that reference it, so editing a closing day regroups history at once.
"""

import unicodedata
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, select

from app.models.cashflow import CashflowEntry, CashflowKind, CashflowWallet
from app.models.credit_card import CreditCard
from app.schemas.card import CardCreate, CardRead, CardUpdate, InvoiceRead, InvoiceStatus


class CardNotFoundError(LookupError):
    """No card with that id."""


class CardNameTakenError(ValueError):
    """Another card already carries this name (after case/accent fold)."""


class UnknownCardError(ValueError):
    """A card was named that is not registered."""


class CardRuleError(ValueError):
    """The request breaks a card invariant (default handling, wallet/kind)."""


class CardInUseError(RuntimeError):
    """Ledger entries still reference the card."""


# Words meaning "this purchase did NOT go on a card" (post accent-fold).
_NO_CARD_WORDS = frozenset({"none", "nenhum", "pix", "debito", "dinheiro", "conta"})

# Generic card words (post accent-fold) that name "a card" without naming ONE
# — nobody actually registers a card called "cartão", so these mean the
# client's default card, same as "auto".
_AUTO_WORDS = frozenset({"auto", "cartao", "credito", "cartao de credito", "no cartao", "padrao"})


def _fold(text: str | None) -> str:
    stripped = "".join(
        ch
        for ch in unicodedata.normalize("NFKD", (text or "").strip().lower())
        if not unicodedata.combining(ch)
    )
    return " ".join(stripped.split())


# --- CRUD ------------------------------------------------------------------------


def list_cards(session: Session) -> list[CreditCard]:
    return list(session.exec(select(CreditCard).order_by(CreditCard.created_at)).all())


def get_card(session: Session, card_id: UUID) -> CreditCard:
    card = session.get(CreditCard, card_id)
    if card is None:
        raise CardNotFoundError(f"Cartão {card_id} não encontrado")
    return card


def default_card(session: Session) -> CreditCard | None:
    return next((c for c in list_cards(session) if c.is_default), None)


def find_card_by_name(session: Session, name: str) -> CreditCard | None:
    wanted = _fold(name)
    return next((c for c in list_cards(session) if _fold(c.name) == wanted), None)


def _demote_others(session: Session, keep_id: UUID | None) -> None:
    for card in list_cards(session):
        if card.is_default and card.id != keep_id:
            card.is_default = False
            session.add(card)


def create_card(session: Session, data: CardCreate) -> CreditCard:
    name = data.name.strip()
    if find_card_by_name(session, name) is not None:
        raise CardNameTakenError(f"Já existe um cartão chamado {name}")
    # The first card is the default whatever the payload said: a lone card
    # that is not the default would make the auto rule silently book nothing.
    first = not list_cards(session)
    card = CreditCard(
        name=name,
        closing_day=data.closing_day,
        due_day=data.due_day,
        is_default=first or data.is_default,
    )
    if card.is_default:
        _demote_others(session, keep_id=None)
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


def update_card(session: Session, card_id: UUID, data: CardUpdate) -> CreditCard:
    card = get_card(session, card_id)
    if data.name is not None:
        name = data.name.strip()
        clash = find_card_by_name(session, name)
        if clash is not None and clash.id != card.id:
            raise CardNameTakenError(f"Já existe um cartão chamado {name}")
        card.name = name
    if data.closing_day is not None:
        card.closing_day = data.closing_day
    if data.due_day is not None:
        card.due_day = data.due_day
    if data.is_default is True:
        _demote_others(session, keep_id=card.id)
        card.is_default = True
    elif data.is_default is False and card.is_default:
        raise CardRuleError("Marque outro cartão como padrão antes de desmarcar este")
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


def delete_card(session: Session, card_id: UUID) -> CreditCard:
    card = get_card(session, card_id)
    used = session.exec(
        select(func.count()).select_from(CashflowEntry).where(CashflowEntry.card_id == card.id)
    ).one()
    if used:
        raise CardInUseError(f"{card.name} tem {used} lançamento(s); apague-os antes de remover")
    was_default = card.is_default
    session.delete(card)
    session.flush()
    if was_default:
        heir = session.exec(select(CreditCard).order_by(CreditCard.created_at)).first()
        if heir is not None:
            heir.is_default = True
            session.add(heir)
    session.commit()
    return card


# --- which card does an entry go on? ---------------------------------------------


def resolve_card(
    session: Session,
    raw: str | None,
    *,
    kind: CashflowKind,
    wallet: CashflowWallet,
) -> CreditCard | None:
    """Which card (if any) a ledger entry goes on.

    ``raw`` is the API's free-form ``card`` field:
    - ``None``/blank/``auto``/a generic card word (cartão, crédito, cartão de
      crédito, no cartão, padrão) → the default card, but only for an expense
      paid from ``conta`` (income and benefit cards never sit on a credit
      card). These words name "a card" without naming ONE, so they resolve
      like "auto" instead of raising as an unknown card named "cartão";
    - an off-card word (none, nenhum, pix, debito, dinheiro, conta) → no card;
    - anything else → a registered card by name. Unknown names raise instead
      of silently falling back, so a typo comes back to the caller.
    """
    folded = _fold(raw)
    on_card_allowed = kind == CashflowKind.EXPENSE and wallet == CashflowWallet.CONTA
    if not folded or folded in _AUTO_WORDS:
        return default_card(session) if on_card_allowed else None
    if folded in _NO_CARD_WORDS:
        return None
    card = find_card_by_name(session, folded)
    if card is None:
        raise UnknownCardError(f"Cartão '{(raw or '').strip()}' não cadastrado")
    if not on_card_allowed:
        raise CardRuleError("Cartão só vale para gasto pago da conta (não em ganho, VR ou VA)")
    return card


# --- invoices (computed, never stored) --------------------------------------------


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """(year, month) moved by ``delta`` months; month is 1-12."""
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _clamp_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, monthrange(year, month)[1]))


def closes_on(card: CreditCard, year: int, month: int) -> date:
    """Closing date of the invoice that closes in (year, month)."""
    return _clamp_day(year, month, card.closing_day)


def due_on(card: CreditCard, closing: date) -> date:
    """First occurrence of ``due_day`` strictly after the closing date."""
    candidate = _clamp_day(closing.year, closing.month, card.due_day)
    if candidate > closing:
        return candidate
    year, month = shift_month(closing.year, closing.month, 1)
    return _clamp_day(year, month, card.due_day)


@dataclass(frozen=True)
class InvoiceWindow:
    closes_on: date
    period_start: date
    period_end: date
    due_on: date


def invoice_window(card: CreditCard, year: int, month: int) -> InvoiceWindow:
    """The cycle that closes in (year, month): (previous closing, closing]."""
    closing = closes_on(card, year, month)
    prev_year, prev_month = shift_month(year, month, -1)
    start = closes_on(card, prev_year, prev_month) + timedelta(days=1)
    return InvoiceWindow(
        closes_on=closing, period_start=start, period_end=closing, due_on=due_on(card, closing)
    )


def open_invoice_month(card: CreditCard, today: date) -> tuple[int, int]:
    """(year, month) of the invoice still open on ``today`` — the earliest
    closing date on or after today (the closing day itself is still open)."""
    if closes_on(card, today.year, today.month) >= today:
        return today.year, today.month
    return shift_month(today.year, today.month, 1)


def _status(window: InvoiceWindow, today: date) -> InvoiceStatus:
    if today <= window.closes_on:
        return "open"
    if today <= window.due_on:
        return "closed"
    return "past"


def _window_totals(session: Session, card_id: UUID, start: date, end: date) -> tuple[float, int]:
    total, count = session.exec(
        select(func.coalesce(func.sum(CashflowEntry.amount_brl), 0), func.count())
        .where(CashflowEntry.card_id == card_id)
        .where(CashflowEntry.occurred_on >= start, CashflowEntry.occurred_on <= end)
    ).one()
    return round(float(total), 2), int(count)


def build_invoice(
    session: Session, card: CreditCard, year: int, month: int, *, today: date
) -> InvoiceRead:
    window = invoice_window(card, year, month)
    total, count = _window_totals(session, card.id, window.period_start, window.period_end)
    return InvoiceRead(
        card_id=card.id,
        period_start=window.period_start,
        period_end=window.period_end,
        closes_on=window.closes_on,
        due_on=window.due_on,
        status=_status(window, today),
        total_brl=total,
        entries=count,
    )


def invoices(
    session: Session, card: CreditCard, *, today: date | None = None, months: int = 6
) -> list[InvoiceRead]:
    """The last ``months`` invoices, oldest first, ending on the open one."""
    today = today or date.today()
    months = max(1, min(months, 24))
    year, month = open_invoice_month(card, today)
    out: list[InvoiceRead] = []
    for offset in range(months - 1, -1, -1):
        y, m = shift_month(year, month, -offset)
        out.append(build_invoice(session, card, y, m, today=today))
    return out


def card_summaries(session: Session, *, today: date | None = None) -> list[CardRead]:
    """Every card with its open invoice and the previous one (when it has
    anything in it) — the single call the screens need."""
    today = today or date.today()
    out: list[CardRead] = []
    for card in list_cards(session):
        year, month = open_invoice_month(card, today)
        current = build_invoice(session, card, year, month, today=today)
        prev_year, prev_month = shift_month(year, month, -1)
        previous = build_invoice(session, card, prev_year, prev_month, today=today)
        out.append(
            CardRead(
                id=card.id,
                name=card.name,
                closing_day=card.closing_day,
                due_day=card.due_day,
                is_default=card.is_default,
                created_at=card.created_at,
                open_invoice=current,
                last_closed_invoice=previous if previous.entries else None,
            )
        )
    return out
