"""Credit cards and their invoices.

Cards are configuration the client owns (name, closing day, due day). Invoices
are NEVER stored: every read recomputes them from the card and the ledger
entries that reference it, so editing a closing day regroups history at once.
"""

import unicodedata
from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, select

from app.models.cashflow import CashflowEntry, CashflowKind, CashflowWallet
from app.models.credit_card import CreditCard
from app.schemas.card import CardCreate, CardUpdate


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
    - ``None``/blank/``auto`` → the default card, but only for an expense paid
      from ``conta`` (income and benefit cards never sit on a credit card);
    - an off-card word (none, nenhum, pix, debito, dinheiro, conta) → no card;
    - anything else → a registered card by name. Unknown names raise instead
      of silently falling back, so a typo comes back to the caller.
    """
    folded = _fold(raw)
    on_card_allowed = kind == CashflowKind.EXPENSE and wallet == CashflowWallet.CONTA
    if not folded or folded == "auto":
        return default_card(session) if on_card_allowed else None
    if folded in _NO_CARD_WORDS:
        return None
    card = find_card_by_name(session, folded)
    if card is None:
        raise UnknownCardError(f"Cartão '{(raw or '').strip()}' não cadastrado")
    if not on_card_allowed:
        raise CardRuleError("Cartão só vale para gasto pago da conta (não em ganho, VR ou VA)")
    return card
