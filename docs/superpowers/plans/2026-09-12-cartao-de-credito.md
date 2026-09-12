# Cartão de crédito no ledger pessoal — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o Assay rastrear gastos no cartão de crédito (cartão padrão, parcelas, fatura calculada, aviso de fechamento) sem contar nada em dobro, mais um olhinho que oculta valores monetários em todo o app.

**Architecture:** Uma tabela `credit_card` e quatro colunas novas em `cashflow_entry` (`card_id`, `installment_no`, `installment_count`, `installment_group`). Faturas nunca são persistidas: `card_service` as calcula do dia de fechamento e dos lançamentos. Parcelas viram N linhas no mesmo ledger, então todos os resumos existentes continuam válidos. O consultor, o classificador e o roteador aprendem as regras (cartão padrão, "paguei a fatura" não é gasto). No front, o extrato ganha o bloco de fatura, Ajustes ganha o cadastro de cartões e um store de privacidade mascara os três formatadores de moeda.

**Tech Stack:** Python 3.11+ · FastAPI · SQLModel/SQLite · pytest · Next.js 16 · TypeScript strict · Tailwind v4 · Lucide · Framer Motion · pnpm.

**Spec:** `docs/superpowers/specs/2026-09-12-cartao-de-credito-design.md` (o olhinho foi pedido depois do spec; sua seção está em Tasks 17–18).

## Global Constraints

- Regime de competência: gasto no cartão conta no mês da compra (`occurred_on`); pagar fatura NUNCA vira lançamento.
- Cartão é o padrão para gasto em `conta` sem meio explícito; VR/VA e `income` nunca levam cartão.
- `wallet` de compra no cartão continua `conta`.
- Nome de cartão desconhecido → 422, nunca cai no padrão em silêncio.
- `installments` 1–48; `amount_brl` do payload é o TOTAL da compra; resto de centavos na parcela 1; datas clampadas a partir da data ORIGINAL.
- Faturas calculadas, nunca gravadas. Status `open` (`today ≤ closes_on`), `closed` (`closes_on < today ≤ due_on`), `past`.
- Toda frase com "fatura" vai para o Opus no roteador.
- Aviso de fechamento sai no dia SEGUINTE ao fechamento, fora do orçamento semanal de insights, só se a fatura tiver lançamentos.
- Migração: coluna nova = declarar no modelo E em `_ADDED_COLUMNS` (`app/core/database.py`). UUID no SQLite é `CHAR(32)`.
- Python: type hints, `async def` nas rotas, ruff limpo. TS: strict, sem `any`, named exports (páginas exportam default por exigência do Next), arrow functions em componentes, `async/await`.
- Comentários de código em inglês. Commits em inglês, Conventional Commits, atômicos, SEM menção a Claude.
- iOS: controles ≥16px (`text-base`), alvos ≥44px (`min-h-[2.75rem]`/`h-11`). Sem gradiente.
- Antes de cada commit de backend: `.venv/bin/ruff check app/ tests/ scripts/ && .venv/bin/ruff format --check app/ tests/ scripts/ && .venv/bin/python -m pytest -q`. Antes de cada commit de frontend: `cd frontend && pnpm lint && pnpm type-check && pnpm build`.

---

## Estrutura de arquivos

**Backend — criar**
- `app/models/credit_card.py` — modelo `CreditCard`.
- `app/schemas/card.py` — `CardCreate`, `CardUpdate`, `InvoiceRead`, `CardRead`.
- `app/services/card_service.py` — CRUD, regra do padrão, `resolve_card`, matemática de fatura, `card_summaries`.
- `app/routers/cards.py` — `/api/cards`.
- `tests/test_card_service.py`, `tests/test_cards_api.py`, `tests/test_cashflow_api.py`.

**Backend — modificar**
- `app/models/cashflow.py` (4 colunas) · `app/models/__init__.py` · `app/core/database.py` (`_ADDED_COLUMNS`).
- `app/schemas/cashflow.py` · `app/services/cashflow_service.py` · `app/routers/cashflow.py`.
- `app/routers/__init__.py` · `app/main.py` (registrar `cards`).
- `app/services/model_router.py` · `app/services/classifier_service.py` · `app/services/chat_service.py` · `app/services/insight_service.py` · `scripts/daily_insights.py` (docstring).
- Testes: `tests/test_database.py`, `tests/test_cashflow_service.py`, `tests/test_model_router.py`, `tests/test_classifier_service.py`, `tests/test_chat_service.py`, `tests/test_insight_service.py`.

**Frontend — criar**
- `frontend/src/hooks/use-cards.ts` · `frontend/src/lib/privacy.ts` · `frontend/src/components/privacy-toggle.tsx` · `frontend/src/components/values-shell.tsx`.

**Frontend — modificar**
- `frontend/src/lib/api.ts` · `frontend/src/lib/format.ts` · `frontend/src/app/(dashboard)/layout.tsx` · `frontend/src/components/sidebar.tsx`.
- `frontend/src/app/(dashboard)/extrato/page.tsx` · `frontend/src/app/(dashboard)/configuracoes/page.tsx` · `frontend/src/app/(dashboard)/page.tsx`.

**Docs — modificar**
- `docs/03-dominio.md`, `docs/06-api.md`, `docs/07-frontend.md`, `docs/04-motor-ia.md`, `docs/12-decisoes.md`, `docs/13-estado-atual.md`, `CLAUDE.md`.

---

### Task 1: Modelo `CreditCard` + colunas de cartão/parcela no ledger

**Files:**
- Create: `app/models/credit_card.py`
- Modify: `app/models/cashflow.py` (depois do campo `wallet`), `app/models/__init__.py`, `app/core/database.py` (`_ADDED_COLUMNS["cashflow_entry"]`)
- Test: `tests/test_database.py`

**Interfaces:**
- Produces: `CreditCard(id, name, closing_day, due_day, is_default, created_at)`; `CashflowEntry.card_id: UUID | None`, `installment_no: int | None`, `installment_count: int | None`, `installment_group: UUID | None`.

- [ ] **Step 1: Escrever o teste de migração que falha**

Acrescente ao FINAL de `tests/test_database.py`:

```python
import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError


def test_card_columns_are_patched_in_with_fk_on(tmp_path) -> None:
    """The four card/installment columns land on an old ledger table, and the
    REFERENCES clause on card_id is enforced once foreign keys are on."""
    engine = create_engine(f"sqlite:///{tmp_path / 'mig.db'}")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _record):  # noqa: ANN001
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as conn:
        # create_all() runs before the column patch, so the parent exists.
        conn.exec_driver_sql("CREATE TABLE credit_card (id CHAR(32) PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE cashflow_entry (id TEXT PRIMARY KEY)")
    _ensure_sqlite_columns(engine)
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(cashflow_entry)")}
        assert {"card_id", "installment_no", "installment_count", "installment_group"} <= cols
        conn.exec_driver_sql("INSERT INTO credit_card (id) VALUES ('c1')")
        conn.exec_driver_sql("INSERT INTO cashflow_entry (id, card_id) VALUES ('e1', 'c1')")
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO cashflow_entry (id, card_id) VALUES ('e2', 'zz')")
    engine.dispose()
```

Mova os `import` para o topo do arquivo (ruff exige imports no topo): `import pytest`, `from sqlalchemy import create_engine, event`, `from sqlalchemy.exc import IntegrityError`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_database.py -q`
Expected: FAIL no `assert {...} <= cols` (colunas ausentes).

- [ ] **Step 3: Criar o modelo**

`app/models/credit_card.py`:

```python
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


def _now_utc() -> datetime:
    return datetime.now(UTC)


class CreditCard(SQLModel, table=True):
    """A credit card the client pays with.

    Invoices are never stored: they are computed from ``closing_day`` and the
    ledger entries that reference the card, so changing the closing day
    regroups the whole history instantly. Exactly one card is the default
    while any exists — ``card_service`` enforces it.
    """

    __tablename__ = "credit_card"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=40, index=True)
    # 1-31; a month shorter than the day falls back to its last day.
    closing_day: int
    due_day: int
    is_default: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=_now_utc)
```

Em `app/models/cashflow.py`, logo depois do campo `wallet` (antes de `created_at`):

```python
    # Credit card the purchase went on; NULL = pix/debit/cash/benefit card.
    card_id: UUID | None = Field(default=None, foreign_key="credit_card.id", index=True)
    # Installment bookkeeping: one row per installment, all sharing a group.
    # All three stay NULL on a single-payment purchase.
    installment_no: int | None = Field(default=None)
    installment_count: int | None = Field(default=None)
    installment_group: UUID | None = Field(default=None, index=True)
```

Em `app/models/__init__.py`: adicione `from app.models.credit_card import CreditCard` (ordem alfabética, depois de `contribution`) e `"CreditCard",` em `__all__` (depois de `"ContributionStatus"`).

Em `app/core/database.py`, substitua o bloco `"cashflow_entry"` de `_ADDED_COLUMNS`:

```python
    "cashflow_entry": {
        "wallet": "TEXT NOT NULL DEFAULT 'conta'",
        # Credit card + installments (2026-09-12). CHAR(32) is what SQLModel's
        # GUID type uses on SQLite; SQLite only lets ALTER TABLE add a
        # REFERENCES column when its default is NULL, which these are.
        "card_id": "CHAR(32) REFERENCES credit_card(id)",
        "installment_no": "INTEGER",
        "installment_count": "INTEGER",
        "installment_group": "CHAR(32)",
    },
```

- [ ] **Step 4: Rodar a suíte inteira**

Run: `.venv/bin/python -m pytest -q`
Expected: tudo PASS (253 testes: 252 + 1).

- [ ] **Step 5: Lint e commit**

```bash
.venv/bin/ruff check app/ tests/ && .venv/bin/ruff format app/ tests/
git add app/models/credit_card.py app/models/cashflow.py app/models/__init__.py app/core/database.py tests/test_database.py
git commit -m "feat(cashflow): credit card table and card/installment columns"
```

---

### Task 2: `card_service` — CRUD, cartão padrão e `resolve_card`

**Files:**
- Create: `app/schemas/card.py`, `app/services/card_service.py`
- Test: `tests/test_card_service.py`

**Interfaces:**
- Consumes: `CreditCard` (Task 1).
- Produces: `card_service.list_cards(session) -> list[CreditCard]`, `get_card(session, id)`, `default_card(session) -> CreditCard | None`, `find_card_by_name(session, name)`, `create_card(session, CardCreate)`, `update_card(session, id, CardUpdate)`, `delete_card(session, id)`, `resolve_card(session, raw, *, kind, wallet) -> CreditCard | None`; exceções `CardNotFoundError`, `CardNameTakenError`, `CardRuleError`, `CardInUseError`, `UnknownCardError`; schemas `CardCreate`, `CardUpdate`, `InvoiceRead`, `CardRead`, `InvoiceStatus`.

- [ ] **Step 1: Escrever os testes que falham**

`tests/test_card_service.py`:

```python
"""Credit cards: the single-default rule and how a ledger entry resolves to a
card (auto / explicit off-card / by name)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlmodel import Session

from app.models.cashflow import CashflowEntry, CashflowKind, CashflowWallet
from app.schemas.card import CardCreate, CardUpdate
from app.services import card_service


def _card(name: str = "Nubank", closing: int = 25, due: int = 3, default: bool = False) -> CardCreate:
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_card_service.py -q`
Expected: erro de import (`app.schemas.card` / `card_service` não existem).

- [ ] **Step 3: Escrever os schemas**

`app/schemas/card.py`:

```python
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CardCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    closing_day: int = Field(..., ge=1, le=31)
    due_day: int = Field(..., ge=1, le=31)
    is_default: bool = False


class CardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    closing_day: int | None = Field(default=None, ge=1, le=31)
    due_day: int | None = Field(default=None, ge=1, le=31)
    is_default: bool | None = None


# open: still accumulating · closed: waiting for the due date · past: due
# date gone (payment is not tracked, so "overdue" would be a lie).
InvoiceStatus = Literal["open", "closed", "past"]


class InvoiceRead(BaseModel):
    """One billing cycle, computed on read — never stored."""

    card_id: UUID
    period_start: date
    period_end: date
    closes_on: date
    due_on: date
    status: InvoiceStatus
    total_brl: float
    entries: int


class CardRead(BaseModel):
    id: UUID
    name: str
    closing_day: int
    due_day: int
    is_default: bool
    created_at: datetime
    open_invoice: InvoiceRead
    last_closed_invoice: InvoiceRead | None
```

- [ ] **Step 4: Escrever o service (parte CRUD + resolve)**

`app/services/card_service.py`:

```python
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

import structlog
from sqlalchemy import func
from sqlmodel import Session, select

from app.models.cashflow import CashflowEntry, CashflowKind, CashflowWallet
from app.models.credit_card import CreditCard
from app.schemas.card import CardCreate, CardRead, CardUpdate, InvoiceRead, InvoiceStatus

logger = structlog.get_logger()


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
```

Os imports `dataclass`, `monthrange`, `timedelta`, `CardRead`, `InvoiceRead`, `InvoiceStatus` e `logger` ficam sem uso até a Task 3 — o ruff vai reclamar (F401). Para este commit, **não** importe o que ainda não usa: deixe só `unicodedata`, `UUID`, `structlog`, `func`, `Session`, `select`, os modelos e `CardCreate`, `CardUpdate`. A Task 3 adiciona o resto.

- [ ] **Step 5: Rodar os testes**

Run: `.venv/bin/python -m pytest tests/test_card_service.py -q`
Expected: PASS (17 testes).

- [ ] **Step 6: Lint e commit**

```bash
.venv/bin/ruff check app/ tests/ && .venv/bin/ruff format app/ tests/ && .venv/bin/python -m pytest -q
git add app/schemas/card.py app/services/card_service.py tests/test_card_service.py
git commit -m "feat(cards): card registry with single-default rule and card resolution"
```

---

### Task 3: `card_service` — matemática de fatura e `card_summaries`

**Files:**
- Modify: `app/services/card_service.py` (acrescentar ao final)
- Test: `tests/test_card_service.py` (acrescentar ao final)

**Interfaces:**
- Produces: `InvoiceWindow(closes_on, period_start, period_end, due_on)`; `closes_on(card, year, month) -> date`; `due_on(card, closing: date) -> date`; `invoice_window(card, year, month) -> InvoiceWindow`; `open_invoice_month(card, today) -> tuple[int, int]`; `build_invoice(session, card, year, month, *, today) -> InvoiceRead`; `invoices(session, card, *, today=None, months=6) -> list[InvoiceRead]`; `card_summaries(session, *, today=None) -> list[CardRead]`; `shift_month(year, month, delta) -> tuple[int, int]`.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao final de `tests/test_card_service.py`:

```python
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_card_service.py -q`
Expected: FAIL com `AttributeError: module ... has no attribute 'invoice_window'`.

- [ ] **Step 3: Implementar a matemática de fatura**

Acrescente aos imports de `app/services/card_service.py`: `from calendar import monthrange`, `from dataclasses import dataclass`, `from datetime import date, timedelta` e, no import de schemas, `CardRead, InvoiceRead, InvoiceStatus`. Depois acrescente ao final do arquivo:

```python
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
```

- [ ] **Step 4: Rodar os testes**

Run: `.venv/bin/python -m pytest tests/test_card_service.py -q`
Expected: PASS (26 testes).

- [ ] **Step 5: Lint e commit**

```bash
.venv/bin/ruff check app/ tests/ && .venv/bin/ruff format app/ tests/ && .venv/bin/python -m pytest -q
git add app/services/card_service.py tests/test_card_service.py
git commit -m "feat(cards): compute invoice windows, status and per-card summaries"
```

---
### Task 4: Lançamento com cartão — schemas, `add_entry`, resumo e aliases

**Files:**
- Modify: `app/schemas/cashflow.py`, `app/services/cashflow_service.py`
- Test: `tests/test_cashflow_service.py` (acrescentar ao final; e ajustar o parametrize de aliases)

**Interfaces:**
- Consumes: `card_service.resolve_card`, `CardRuleError`, `UnknownCardError` (Task 2).
- Produces: `CashflowCreate.card: str | None`, `CashflowCreate.installments: int` (1–48, default 1); `CashflowRead.card_id`, `card_name`, `installment_no`, `installment_count`, `installment_group`; `CashflowSummary.card_expense_brl: float`; `list_entries(..., card_id: UUID | None = None)`.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao final de `tests/test_cashflow_service.py`:

```python
# --- credit card on an entry ----------------------------------------------------

from uuid import UUID  # noqa: E402

from app.schemas.card import CardCreate  # noqa: E402
from app.services import card_service  # noqa: E402


def _nubank(session: Session, closing: int = 25, due: int = 3):  # noqa: ANN202
    return card_service.create_card(
        session, CardCreate(name="Nubank", closing_day=closing, due_day=due)
    )


def test_expense_from_conta_lands_on_the_default_card(session: Session) -> None:
    card = _nubank(session)
    entry = cashflow_service.add_entry(session, _entry())
    assert entry.card_id == card.id
    assert entry.wallet == CashflowWallet.CONTA  # the money still leaves the account
    assert entry.installment_no is None and entry.installment_group is None


def test_explicit_pix_stays_off_the_card(session: Session) -> None:
    _nubank(session)
    entry = cashflow_service.add_entry(
        session, CashflowCreate(kind=CashflowKind.EXPENSE, amount_brl=Decimal("10"), card="pix")
    )
    assert entry.card_id is None


def test_benefit_and_income_never_get_a_card(session: Session) -> None:
    _nubank(session)
    vr = cashflow_service.add_entry(
        session, CashflowCreate(kind=CashflowKind.EXPENSE, amount_brl=Decimal("35"), wallet="vr")
    )
    salary = cashflow_service.add_entry(
        session, CashflowCreate(kind=CashflowKind.INCOME, amount_brl=Decimal("8400"))
    )
    assert vr.card_id is None and salary.card_id is None


def test_unknown_card_name_is_refused(session: Session) -> None:
    _nubank(session)
    with pytest.raises(card_service.UnknownCardError):
        cashflow_service.add_entry(
            session,
            CashflowCreate(kind=CashflowKind.EXPENSE, amount_brl=Decimal("10"), card="itau"),
        )


def test_summary_reports_card_spend_separately(session: Session) -> None:
    _nubank(session)
    on = date(2026, 9, 10)
    cashflow_service.add_entry(session, _entry(amount="100.00", occurred_on=on))
    cashflow_service.add_entry(
        session,
        CashflowCreate(
            kind=CashflowKind.EXPENSE, amount_brl=Decimal("40"), card="pix", occurred_on=on
        ),
    )
    summary = cashflow_service.month_summary(session, "2026-09")
    assert summary.expense_brl == 140.0
    assert summary.card_expense_brl == 100.0


def test_list_entries_filters_by_card(session: Session) -> None:
    card = _nubank(session)
    cashflow_service.add_entry(session, _entry(amount="100.00"))
    cashflow_service.add_entry(
        session, CashflowCreate(kind=CashflowKind.EXPENSE, amount_brl=Decimal("40"), card="pix")
    )
    assert len(cashflow_service.list_entries(session, card_id=card.id)) == 1
    assert len(cashflow_service.list_entries(session, card_id=UUID(int=0))) == 0
```

No parametrize `test_normalize_wallet_folds_onto_closed_vocabulary`, acrescente a linha
`("cartao", CashflowWallet.CONTA),  # no longer an alias: a card is a card, not a wallet` logo antes de `("cartao misterioso", ...)`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_cashflow_service.py -q`
Expected: FAIL (`CashflowCreate` não aceita `card`; `card_id` não é preenchido).

- [ ] **Step 3: Schemas**

Em `app/schemas/cashflow.py`, dentro de `CashflowCreate`, depois de `wallet`:

```python
    # Card the purchase went on. Free-form: None/"auto" = the default card
    # (for an expense from conta), "none"/"pix"/"debito"/"dinheiro" =
    # explicitly off-card, anything else = a registered card's name.
    card: str | None = Field(default=None, max_length=40)
    # Monthly installments; >1 expands into one ledger row per month and
    # amount_brl is then the TOTAL of the purchase.
    installments: int = Field(default=1, ge=1, le=48)
```

Em `CashflowRead`, antes de `created_at`:

```python
    card_id: UUID | None = None
    card_name: str | None = None  # filled by the router (one lookup, no N+1)
    installment_no: int | None = None
    installment_count: int | None = None
    installment_group: UUID | None = None
```

Em `CashflowSummary`, depois de `entries: int`: `card_expense_brl: float = 0.0`.

- [ ] **Step 4: Service**

Em `app/services/cashflow_service.py`:

1. Import: `from app.services import card_service` (grupo local, depois de `app.schemas.cashflow`).
2. Em `_WALLET_ALIASES`, **remova** as linhas `"cartao": "conta",` e `"credito": "conta",`. Atualize o comentário acima do dict acrescentando: `# "cartao"/"credito" left on purpose: a card is modelled by card_id now, and a caller still sending it as a wallet should show up in the log (unknown → conta).`
3. Em `_recent_duplicate`, acrescente ao `.where(...)`, depois de `CashflowEntry.wallet == entry.wallet,`:
   ```python
            CashflowEntry.card_id == entry.card_id,
            CashflowEntry.installment_no == entry.installment_no,
            CashflowEntry.installment_count == entry.installment_count,
   ```
   (`== None` vira `IS NULL` no SQLAlchemy.)
4. Substitua `add_entry` inteira por:

```python
def add_entry(session: Session, data: CashflowCreate) -> CashflowEntry:
    """Book one expense or income line.

    Raises ``card_service.UnknownCardError`` / ``CardRuleError`` when the
    ``card`` field cannot be honoured — the API turns both into 422.
    """
    wallet = normalize_wallet(data.wallet)
    card = card_service.resolve_card(session, data.card, kind=data.kind, wallet=wallet)
    entry = CashflowEntry(
        kind=data.kind,
        amount_brl=data.amount_brl,
        category=normalize_category(data.category),
        description=(data.description or "").strip() or None,
        occurred_on=data.occurred_on or date.today(),
        source=data.source,
        wallet=wallet,
        card_id=card.id if card is not None else None,
    )
    existing = _recent_duplicate(session, entry)
    if existing is not None:
        logger.info(
            "cashflow_duplicate_ignored",
            amount=float(entry.amount_brl),
            category=entry.category,
            source=str(entry.source),
        )
        return existing
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry
```

5. `list_entries`: acrescente o parâmetro keyword `card_id: UUID | None = None` (depois de `wallet`) e, depois do `if wallet is not None:` block:
   ```python
    if card_id is not None:
        stmt = stmt.where(CashflowEntry.card_id == card_id)
   ```
6. `month_summary`: depois da linha que calcula `expense`, acrescente
   ```python
    card_expense = sum(
        float(e.amount_brl)
        for e in entries
        if e.kind == CashflowKind.EXPENSE and e.card_id is not None
    )
   ```
   e no `return CashflowSummary(...)` acrescente `card_expense_brl=round(card_expense, 2),` depois de `entries=len(entries),`.

- [ ] **Step 5: Rodar os testes**

Run: `.venv/bin/python -m pytest tests/test_cashflow_service.py tests/test_bot_cashflow.py tests/test_insight_service.py -q`
Expected: PASS. (O bot e os insights criam lançamentos sem cartão cadastrado → `card_id` None, nada muda.)

- [ ] **Step 6: Lint e commit**

```bash
.venv/bin/ruff check app/ tests/ && .venv/bin/ruff format app/ tests/ && .venv/bin/python -m pytest -q
git add app/schemas/cashflow.py app/services/cashflow_service.py tests/test_cashflow_service.py
git commit -m "feat(cashflow): default credit card on account expenses and card totals"
```

---

### Task 5: Parcelas — expansão em N linhas, dedup e exclusão do grupo

**Files:**
- Modify: `app/services/cashflow_service.py`
- Test: `tests/test_cashflow_service.py` (acrescentar ao final)

**Interfaces:**
- Consumes: `CashflowCreate.installments` (Task 4).
- Produces: `add_entry` devolve a parcela 1 quando `installments > 1`; `delete_group(session, group_id: UUID) -> int`.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao final de `tests/test_cashflow_service.py`:

```python
# --- installments ------------------------------------------------------------------


def _tv(session: Session, total: str = "100.00", count: int = 3, on: date = date(2026, 1, 31)):  # noqa: ANN202
    return cashflow_service.add_entry(
        session,
        CashflowCreate(
            kind=CashflowKind.EXPENSE,
            amount_brl=Decimal(total),
            category="lazer",
            description="tv",
            occurred_on=on,
            installments=count,
        ),
    )


def test_installments_expand_into_one_row_per_month(session: Session) -> None:
    _nubank(session)
    first = _tv(session)
    rows = sorted(cashflow_service.list_entries(session), key=lambda r: r.occurred_on)
    assert first.id == rows[0].id
    assert [float(r.amount_brl) for r in rows] == [33.34, 33.33, 33.33]
    # Clamped from the ORIGINAL day: Jan 31 → Feb 28 → Mar 31 (never Mar 28).
    assert [r.occurred_on for r in rows] == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
    ]
    assert [r.installment_no for r in rows] == [1, 2, 3]
    assert {r.installment_count for r in rows} == {3}
    assert len({r.installment_group for r in rows}) == 1
    assert all(r.card_id is not None and r.description == "tv" for r in rows)


def test_installments_require_a_card(session: Session) -> None:
    with pytest.raises(card_service.CardRuleError):
        _tv(session)  # no card registered → auto resolves to none


def test_repeated_installment_post_does_not_duplicate_the_group(session: Session) -> None:
    _nubank(session)
    first = _tv(session)
    again = _tv(session)
    assert again.id == first.id
    assert len(cashflow_service.list_entries(session)) == 3


def test_delete_group_removes_every_installment(session: Session) -> None:
    _nubank(session)
    first = _tv(session)
    assert first.installment_group is not None
    assert cashflow_service.delete_group(session, first.installment_group) == 3
    assert cashflow_service.list_entries(session) == []
    with pytest.raises(cashflow_service.CashflowNotFoundError):
        cashflow_service.delete_group(session, first.installment_group)


def test_single_payment_has_no_installment_fields(session: Session) -> None:
    _nubank(session)
    entry = _tv(session, count=1)
    assert entry.installment_no is None
    assert entry.installment_count is None
    assert entry.installment_group is None
    assert float(entry.amount_brl) == 100.0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_cashflow_service.py -q -k "installment or group"`
Expected: FAIL (apenas uma linha é criada; `delete_group` não existe).

- [ ] **Step 3: Implementar**

Em `app/services/cashflow_service.py`:

1. Imports: `from decimal import ROUND_DOWN, Decimal` e `from uuid import UUID, uuid4`.
2. Acima de `add_entry`, acrescente:

```python
def _add_months(day: date, months: int) -> date:
    """Same day-of-month ``months`` later, clamped to that month's length —
    always from the ORIGINAL day (Jan 31 → Feb 28 → Mar 31, never Mar 28)."""
    index = day.year * 12 + (day.month - 1) + months
    year, month0 = divmod(index, 12)
    return date(year, month0 + 1, min(day.day, monthrange(year, month0 + 1)[1]))


def _split_installments(total: Decimal, count: int) -> list[Decimal]:
    """``count`` cent-exact parts of ``total``; the rounding remainder goes to
    the first installment (100 in 3 → 33.34, 33.33, 33.33)."""
    base = (total / count).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return [base + (total - base * count)] + [base] * (count - 1)
```

3. Substitua `add_entry` por:

```python
def add_entry(session: Session, data: CashflowCreate) -> CashflowEntry:
    """Book one purchase or income line.

    A purchase in N installments becomes N rows, one per month, sharing an
    ``installment_group``; the FIRST row is returned. Raises
    ``card_service.UnknownCardError`` / ``CardRuleError`` when the ``card``
    field cannot be honoured — the API turns both into 422.
    """
    wallet = normalize_wallet(data.wallet)
    card = card_service.resolve_card(session, data.card, kind=data.kind, wallet=wallet)
    count = data.installments
    if count > 1 and card is None:
        raise card_service.CardRuleError("Parcelamento exige um cartão cadastrado")

    amounts = _split_installments(Decimal(data.amount_brl).quantize(Decimal("0.01")), count)
    first_day = data.occurred_on or date.today()
    group = uuid4() if count > 1 else None
    rows = [
        CashflowEntry(
            kind=data.kind,
            amount_brl=amounts[index],
            category=normalize_category(data.category),
            description=(data.description or "").strip() or None,
            occurred_on=_add_months(first_day, index),
            source=data.source,
            wallet=wallet,
            card_id=card.id if card is not None else None,
            installment_no=index + 1 if count > 1 else None,
            installment_count=count if count > 1 else None,
            installment_group=group,
        )
        for index in range(count)
    ]
    existing = _recent_duplicate(session, rows[0])
    if existing is not None:
        logger.info(
            "cashflow_duplicate_ignored",
            amount=float(rows[0].amount_brl),
            category=rows[0].category,
            source=str(rows[0].source),
        )
        return existing
    session.add_all(rows)
    session.commit()
    session.refresh(rows[0])
    return rows[0]
```

4. Depois de `delete_entry`, acrescente:

```python
def delete_group(session: Session, group_id: UUID) -> int:
    """Delete every installment of one purchase. Returns how many rows went."""
    rows = list(
        session.exec(
            select(CashflowEntry).where(CashflowEntry.installment_group == group_id)
        ).all()
    )
    if not rows:
        raise CashflowNotFoundError(f"Compra parcelada {group_id} não encontrada")
    for row in rows:
        session.delete(row)
    session.commit()
    return len(rows)
```

- [ ] **Step 4: Rodar os testes**

Run: `.venv/bin/python -m pytest tests/test_cashflow_service.py -q`
Expected: PASS.

- [ ] **Step 5: Lint e commit**

```bash
.venv/bin/ruff check app/ tests/ && .venv/bin/ruff format app/ tests/ && .venv/bin/python -m pytest -q
git add app/services/cashflow_service.py tests/test_cashflow_service.py
git commit -m "feat(cashflow): expand installments into one row per month with group delete"
```

---

### Task 6: Router `/api/cards`

**Files:**
- Create: `app/routers/cards.py`
- Modify: `app/routers/__init__.py`, `app/main.py`
- Test: `tests/test_cards_api.py`

**Interfaces:**
- Consumes: `card_service.*` (Tasks 2–3), schemas de `app/schemas/card.py`.
- Produces: `GET/POST /api/cards`, `PATCH/DELETE /api/cards/{id}`, `GET /api/cards/{id}/invoices?months=`.

- [ ] **Step 1: Escrever os testes que falham**

`tests/test_cards_api.py`:

```python
"""HTTP surface of the card registry: status codes and the embedded invoices."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.database import get_session
from app.main import app
from app.models.cashflow import CashflowEntry, CashflowKind


@pytest.fixture()
def client(session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _create(client: TestClient, name: str = "Nubank", closing: int = 25, due: int = 3) -> dict:
    response = client.post(
        "/api/cards", json={"name": name, "closing_day": closing, "due_day": due}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_list_embed_the_open_invoice(client: TestClient) -> None:
    created = _create(client)
    assert created["is_default"] is True
    assert created["open_invoice"]["status"] == "open"
    assert created["last_closed_invoice"] is None
    listed = client.get("/api/cards").json()
    assert [c["name"] for c in listed] == ["Nubank"]


def test_duplicate_name_is_409(client: TestClient) -> None:
    _create(client)
    response = client.post(
        "/api/cards", json={"name": "nubank", "closing_day": 1, "due_day": 10}
    )
    assert response.status_code == 409


def test_day_out_of_range_is_422(client: TestClient) -> None:
    response = client.post("/api/cards", json={"name": "X", "closing_day": 32, "due_day": 3})
    assert response.status_code == 422


def test_patch_default_and_refuse_unsetting_it(client: TestClient) -> None:
    first = _create(client, "Nubank")
    second = _create(client, "Itaú")
    promoted = client.patch(f"/api/cards/{second['id']}", json={"is_default": True})
    assert promoted.status_code == 200 and promoted.json()["is_default"] is True
    assert client.get("/api/cards").json()[0]["is_default"] is False  # Nubank demoted
    refused = client.patch(f"/api/cards/{second['id']}", json={"is_default": False})
    assert refused.status_code == 422
    assert client.patch(f"/api/cards/{first['id']}", json={"name": "Itaú"}).status_code == 409


def test_delete_in_use_is_409_and_unknown_is_404(client: TestClient, session: Session) -> None:
    card = _create(client)
    session.add(
        CashflowEntry(
            kind=CashflowKind.EXPENSE,
            amount_brl=Decimal("10"),
            occurred_on=date(2026, 9, 1),
            card_id=card["id"],
        )
    )
    session.commit()
    assert client.delete(f"/api/cards/{card['id']}").status_code == 409
    assert client.delete("/api/cards/00000000-0000-0000-0000-000000000000").status_code == 404


def test_delete_unused_card_returns_it(client: TestClient) -> None:
    card = _create(client)
    response = client.delete(f"/api/cards/{card['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == "Nubank"
    assert client.get("/api/cards").json() == []


def test_invoices_history_is_oldest_first_and_capped(client: TestClient) -> None:
    card = _create(client)
    history = client.get(f"/api/cards/{card['id']}/invoices?months=3").json()
    assert len(history) == 3
    assert history[0]["closes_on"] < history[-1]["closes_on"]
    assert history[-1]["status"] == "open"
    assert len(client.get(f"/api/cards/{card['id']}/invoices?months=99").json()) == 24
    assert client.get("/api/cards/00000000-0000-0000-0000-000000000000/invoices").status_code == 404
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_cards_api.py -q`
Expected: FAIL com 404 em `POST /api/cards` (rota não existe).

- [ ] **Step 3: Escrever o router e registrar**

`app/routers/cards.py`:

```python
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.card import CardCreate, CardRead, CardUpdate, InvoiceRead
from app.services import card_service

router = APIRouter(prefix="/api/cards", tags=["cards"])


def _read(session: Session, card_id: UUID) -> CardRead:
    """One card's CardRead. Summaries are computed for every card (a handful,
    two queries each), so pick this one out of the list."""
    for item in card_service.card_summaries(session):
        if item.id == card_id:
            return item
    raise HTTPException(status_code=404, detail="Cartão não encontrado")


@router.get("", response_model=list[CardRead])
async def list_cards(session: Session = Depends(get_session)) -> list[CardRead]:
    """Every card with its open invoice and the last closed one (computed)."""
    return card_service.card_summaries(session)


@router.post("", response_model=CardRead, status_code=status.HTTP_201_CREATED)
async def create_card(data: CardCreate, session: Session = Depends(get_session)) -> CardRead:
    """Register a card. The first one becomes the default automatically."""
    try:
        card = card_service.create_card(session, data)
    except card_service.CardNameTakenError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _read(session, card.id)


@router.patch("/{card_id}", response_model=CardRead)
async def update_card(
    card_id: UUID, data: CardUpdate, session: Session = Depends(get_session)
) -> CardRead:
    try:
        card = card_service.update_card(session, card_id, data)
    except card_service.CardNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except card_service.CardNameTakenError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except card_service.CardRuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _read(session, card.id)


@router.delete("/{card_id}", response_model=CardRead)
async def delete_card(card_id: UUID, session: Session = Depends(get_session)) -> CardRead:
    """Remove a card nothing references. 409 while ledger rows still point at it."""
    snapshot = _read(session, card_id)  # 404 before touching anything
    try:
        card_service.delete_card(session, card_id)
    except card_service.CardInUseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return snapshot


@router.get("/{card_id}/invoices", response_model=list[InvoiceRead])
async def list_invoices(
    card_id: UUID, months: int = 6, session: Session = Depends(get_session)
) -> list[InvoiceRead]:
    """Invoice history, oldest first, ending on the open one (1–24 months)."""
    try:
        card = card_service.get_card(session, card_id)
    except card_service.CardNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return card_service.invoices(session, card, months=max(1, min(months, 24)))
```

Em `app/routers/__init__.py`, acrescente `cards,` na lista (ordem alfabética: depois de `cadence`, antes de `cashflow`). Em `app/main.py`, acrescente `cards,` ao import de `app.routers` e `app.include_router(cards.router)` logo depois de `app.include_router(cashflow.router)`.

- [ ] **Step 4: Rodar os testes**

Run: `.venv/bin/python -m pytest tests/test_cards_api.py -q`
Expected: PASS (7 testes).

- [ ] **Step 5: Lint e commit**

```bash
.venv/bin/ruff check app/ tests/ && .venv/bin/ruff format app/ tests/ && .venv/bin/python -m pytest -q
git add app/routers/cards.py app/routers/__init__.py app/main.py tests/test_cards_api.py
git commit -m "feat(api): card registry endpoints with computed invoices"
```

---

### Task 7: Router `/api/cashflow` — cartão na leitura, filtro, 422 e exclusão de grupo

**Files:**
- Modify: `app/routers/cashflow.py`
- Test: `tests/test_cashflow_api.py` (novo)

**Interfaces:**
- Consumes: `cashflow_service.delete_group`, `list_entries(card_id=)` (Tasks 4–5); `card_service.list_cards` (Task 2).
- Produces: `CashflowRead.card_name` preenchido em toda resposta; `GET /api/cashflow?card_id=`; `DELETE /api/cashflow/groups/{group_id}` → `{"deleted": n}`; POST com cartão inválido → 422.

- [ ] **Step 1: Escrever os testes que falham**

`tests/test_cashflow_api.py`:

```python
"""Ledger endpoints with a card in the picture: card names on reads, the
card filter, 422 on a bad card and the whole-purchase delete."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.database import get_session
from app.main import app


@pytest.fixture()
def client(session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _card(client: TestClient) -> str:
    response = client.post(
        "/api/cards", json={"name": "Nubank", "closing_day": 25, "due_day": 3}
    )
    assert response.status_code == 201
    return response.json()["id"]


def _post(client: TestClient, **overrides: object) -> dict:
    payload = {"kind": "expense", "amount_brl": 300, "category": "lazer", "occurred_on": "2026-09-10"}
    payload.update(overrides)
    response = client.post("/api/cashflow", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_reads_carry_the_card_name(client: TestClient) -> None:
    card_id = _card(client)
    created = _post(client)
    assert created["card_id"] == card_id
    assert created["card_name"] == "Nubank"
    listed = client.get("/api/cashflow?month=2026-09").json()
    assert listed[0]["card_name"] == "Nubank"
    pix = _post(client, card="pix")
    assert pix["card_id"] is None and pix["card_name"] is None


def test_card_filter(client: TestClient) -> None:
    card_id = _card(client)
    _post(client)
    _post(client, card="pix", amount_brl=5)
    assert len(client.get(f"/api/cashflow?month=2026-09&card_id={card_id}").json()) == 1
    assert len(client.get("/api/cashflow?month=2026-09").json()) == 2


def test_unknown_card_and_installments_without_card_are_422(client: TestClient) -> None:
    unknown = client.post(
        "/api/cashflow", json={"kind": "expense", "amount_brl": 10, "card": "itau"}
    )
    assert unknown.status_code == 422
    assert "não cadastrado" in unknown.json()["detail"]
    parcelled = client.post(
        "/api/cashflow", json={"kind": "expense", "amount_brl": 10, "installments": 3}
    )
    assert parcelled.status_code == 422


def test_installment_group_delete(client: TestClient) -> None:
    _card(client)
    first = _post(client, installments=3)
    assert first["installment_no"] == 1 and first["installment_count"] == 3
    group = first["installment_group"]
    assert group is not None
    response = client.delete(f"/api/cashflow/groups/{group}")
    assert response.status_code == 200 and response.json() == {"deleted": 3}
    assert client.delete(f"/api/cashflow/groups/{group}").status_code == 404
    assert client.get("/api/cashflow?month=2026-09").json() == []


def test_summary_exposes_card_expense(client: TestClient) -> None:
    _card(client)
    _post(client, amount_brl=100)
    _post(client, amount_brl=40, card="pix")
    summary = client.get("/api/cashflow/summary?month=2026-09").json()
    assert summary["expense_brl"] == 140.0
    assert summary["card_expense_brl"] == 100.0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_cashflow_api.py -q`
Expected: FAIL (`card_name` é None; `groups` devolve 404/422; cartão desconhecido vira 500).

- [ ] **Step 3: Implementar**

Em `app/routers/cashflow.py`:

1. Imports: `from app.services import card_service, cashflow_service, classifier_service`.
2. Acima de `create_entry`, acrescente:

```python
def _reads(session: Session, entries: list) -> list[CashflowRead]:  # noqa: ANN001
    """CashflowRead rows with the card name attached — ONE card lookup for
    the whole page instead of a query per row."""
    names = {card.id: card.name for card in card_service.list_cards(session)}
    out: list[CashflowRead] = []
    for entry in entries:
        read = CashflowRead.model_validate(entry, from_attributes=True)
        read.card_name = names.get(entry.card_id) if entry.card_id is not None else None
        out.append(read)
    return out


class GroupDeleted(BaseModel):
    deleted: int
```

3. `create_entry`: envolva a chamada ao service:

```python
    try:
        entry = cashflow_service.add_entry(session, data)
    except (card_service.UnknownCardError, card_service.CardRuleError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _reads(session, [entry])[0]
```

4. `list_entries`: acrescente o parâmetro `card_id: UUID | None = None` (depois de `wallet`), passe `card_id=card_id` ao service e devolva `_reads(session, entries)`.
5. Antes de `delete_entry`, acrescente:

```python
@router.delete("/groups/{group_id}", response_model=GroupDeleted)
async def delete_group(group_id: UUID, session: Session = Depends(get_session)) -> GroupDeleted:
    """Delete a whole installment purchase (every monthly row of the group)."""
    try:
        return GroupDeleted(deleted=cashflow_service.delete_group(session, group_id))
    except cashflow_service.CashflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

6. `delete_entry`: devolva `_reads(session, [entry])[0]`.
7. Atualize a docstring de `create_entry` para: `"""Register one expense or income line. A purchase in N installments creates N rows and returns the first; `card` unknown or misused → 422."""`

- [ ] **Step 4: Rodar os testes**

Run: `.venv/bin/python -m pytest tests/test_cashflow_api.py tests/test_cards_api.py -q`
Expected: PASS.

- [ ] **Step 5: Lint e commit**

```bash
.venv/bin/ruff check app/ tests/ && .venv/bin/ruff format app/ tests/ && .venv/bin/python -m pytest -q
git add app/routers/cashflow.py tests/test_cashflow_api.py
git commit -m "feat(api): card name on ledger reads, card filter and installment group delete"
```

---
### Task 8: Roteador — toda frase com "fatura" vai para o Opus

**Files:**
- Modify: `app/services/model_router.py` (`_ASKS_RE`, `_ADVICE_RE`)
- Test: `tests/test_model_router.py` (acrescentar ao final)

**Interfaces:**
- Produces: `model_router.route("paguei a fatura 3200").tier is Tier.DEEP`.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao final de `tests/test_model_router.py`:

```python
# --- credit card ---------------------------------------------------------------


def test_card_purchase_still_books_fast() -> None:
    assert _tier("gastei 42 no cartão") is model_router.Tier.FAST
    assert _tier("comprei a tv em 10x de 200 no cartão") is model_router.Tier.FAST


def test_paying_the_invoice_is_never_a_booking() -> None:
    """"paguei a fatura 3200" has a past-tense verb and an amount — the fast
    path would book a R$ 3.200 expense that double-counts every purchase
    already in the ledger. Anything about the invoice goes to opus."""
    assert _tier("paguei a fatura 3200") is model_router.Tier.DEEP
    assert _tier("paguei a fatura do nubank, 3.412,90") is model_router.Tier.DEEP


def test_invoice_questions_skip_the_lookup_tier() -> None:
    assert _tier("quanto tá minha fatura?") is model_router.Tier.DEEP
    assert _tier("qual o valor da fatura") is model_router.Tier.DEEP
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_model_router.py -q`
Expected: FAIL em `test_paying_the_invoice_is_never_a_booking` (vai para FAST) e no `qual o valor da fatura` (vai para LOOKUP).

- [ ] **Step 3: Implementar**

Em `app/services/model_router.py`:

- Em `_ASKS_RE`, troque a última alternativa `r"parcel\w*|financi\w*|juros|d[íi]vida|empr[ée]stimo)\b",` por `r"parcel\w*|financi\w*|juros|d[íi]vida|empr[ée]stimo|fatura)\b",`.
- Em `_ADVICE_RE`, troque `r"tend[êe]ncia|parcel\w*|financi\w*|juros|d[íi]vida|empr[ée]stimo)\b",` por `r"tend[êe]ncia|parcel\w*|financi\w*|juros|d[íi]vida|empr[ée]stimo|fatura)\b",`.
- Acrescente ao comentário acima de `_ASKS_RE` a linha: `# "fatura" is here on purpose: paying the invoice is NOT an expense (every purchase is already booked), and only opus carries that rule.`

- [ ] **Step 4: Rodar os testes**

Run: `.venv/bin/python -m pytest tests/test_model_router.py -q`
Expected: PASS.

- [ ] **Step 5: Lint e commit**

```bash
.venv/bin/ruff check app/ tests/ && .venv/bin/ruff format app/ tests/ && .venv/bin/python -m pytest -q
git add app/services/model_router.py tests/test_model_router.py
git commit -m "fix(router): send every invoice message to the deep tier"
```

---

### Task 9: Classificador — `card` e `installments` no rascunho

**Files:**
- Modify: `app/services/classifier_service.py`
- Test: `tests/test_classifier_service.py` (acrescentar ao final)

**Interfaces:**
- Consumes: `CashflowCreate.card`, `.installments` (Task 4).
- Produces: `classify(text)` devolve `card` (None quando "auto"/ausente) e `installments` (1 quando ausente/inválido).

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao final de `tests/test_classifier_service.py`:

```python
def test_classify_carries_card_and_installments(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_step(
        monkeypatch,
        {
            "kind": "expense",
            "amount_brl": 2000.0,
            "category": "lazer",
            "description": "tv",
            "occurred_on": "2026-09-10",
            "wallet": "conta",
            "card": "nubank",
            "installments": 10,
        },
    )
    draft = classifier_service.classify("comprei uma tv em 10x de 200 no nubank")
    assert draft.card == "nubank"
    assert draft.installments == 10


def test_classify_auto_card_becomes_none_and_bad_installments_fall_to_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_step(
        monkeypatch,
        {"kind": "expense", "amount_brl": 10.0, "category": "mercado", "card": "auto",
         "installments": "99"},
    )
    draft = classifier_service.classify("gastei 10 no mercado")
    assert draft.card is None
    assert draft.installments == 1


def test_classify_old_shape_defaults_card_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_step(monkeypatch, {"kind": "expense", "amount_brl": 10.0, "category": "mercado"})
    draft = classifier_service.classify("gastei 10 no mercado")
    assert draft.card is None
    assert draft.installments == 1
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_classifier_service.py -q`
Expected: FAIL (`draft.card` não é "nubank"; `installments` não é 10).

- [ ] **Step 3: Implementar**

Em `classifier_service._prompt`, troque a linha do JSON de exemplo por:

```
{{"kind": "expense|income", "amount_brl": 0.00, "category": "...", "description": "...", "occurred_on": "AAAA-MM-DD", "wallet": "conta|vr|va", "card": "auto|none|<nome do cartão>", "installments": 1}}
```

e acrescente, depois da regra de `wallet` (antes de `- Hoje é ...`):

```
- `card`: como pagou. "auto" quando a frase não diz (o cartão de crédito
  padrão do cliente é aplicado). "none" se citar pix, débito, dinheiro ou
  transferência. Se citar um cartão pelo nome ("no nubank", "no cartão itaú"),
  só o nome ("nubank", "itaú"). Gasto em VR/VA: sempre "none".
- `installments`: número de parcelas. "em 10x", "10 vezes", "parcelado em 10"
  → 10. Sem parcelamento, 1. Com parcelas, `amount_brl` é o TOTAL da compra
  (10x de 200 → 2000.00).
```

Em `classify`, depois da linha `wallet = normalize_wallet(...)`, acrescente:

```python
    card_raw = str(data.get("card") or "").strip()
    card = None if card_raw.lower() in ("", "auto") else card_raw[:40]

    try:
        installments = int(data.get("installments") or 1)
    except (TypeError, ValueError):
        installments = 1
    if not 1 <= installments <= 48:
        logger.warning("cashflow_classify_bad_installments", raw=str(data.get("installments"))[:8])
        installments = 1
```

e passe `card=card, installments=installments` ao `CashflowCreate(...)` devolvido. Acrescente `card=card, installments=installments` também ao `logger.info("cashflow_classified", ...)`.

- [ ] **Step 4: Rodar os testes**

Run: `.venv/bin/python -m pytest tests/test_classifier_service.py -q`
Expected: PASS.

- [ ] **Step 5: Lint e commit**

```bash
.venv/bin/ruff check app/ tests/ && .venv/bin/ruff format app/ tests/ && .venv/bin/python -m pytest -q
git add app/services/classifier_service.py tests/test_classifier_service.py
git commit -m "feat(classifier): draft card and installments from free text"
```

---

### Task 10: Ordens permanentes do consultor

**Files:**
- Modify: `app/services/chat_service.py` (`_CONSULTANT_ORDERS` e `_SEED_CHAT_MEMORY`)
- Test: `tests/test_chat_service.py::test_ensure_workspace_seeds_and_preserves_memory`

Lembrete: `_CONSULTANT_ORDERS` passa por `.format(...)`, então **chaves literais são duplicadas** (`{{` `}}`) e `{backend_url}` é placeholder.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/test_chat_service.py`, dentro de `test_ensure_workspace_seeds_and_preserves_memory`, depois de `assert "/api/cashflow" in orders`, acrescente:

```python
    assert "/api/cards" in orders
    assert "PAGAMENTO DE FATURA NÃO É GASTO" in orders
    assert '"installments"' in orders
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_chat_service.py -q -k seeds_and_preserves`
Expected: FAIL no `"/api/cards"`.

- [ ] **Step 3: Editar as ordens**

Em `_CONSULTANT_ORDERS`:

(a) No item 1 de "O que você faz nesta conversa", depois da linha `   investível nem como sobra de caixa.`, acrescente:

```
   **Cartão de crédito**: o cliente passa TUDO no cartão. Gasto pago da
   `conta` sem meio explícito → NÃO mande `card` (a API aplica o cartão
   padrão). Pix, débito, dinheiro → `"card": "none"`. Outro cartão pelo nome
   → `"card": "<nome>"`. VR/VA nunca levam cartão. Parcelado ("em 10x", "10
   vezes", "parcelei em 10") → `"installments": 10` e `amount_brl` = TOTAL da
   compra (10x de 200 → 2000); a API cria uma linha por mês, cada uma com
   `installment_no/installment_count`.
   **PAGAMENTO DE FATURA NÃO É GASTO** — cada compra já está no ledger, lançar
   a fatura contaria tudo em dobro. "paguei a fatura" → não registre nada;
   leia `GET {backend_url}/api/cards`, compare o que ele pagou com
   `last_closed_invoice.total_brl` e trate a diferença como compra que faltou
   registrar (pergunte o que foi e lance com a data da compra). Sem cartão
   cadastrado? Registre o gasto (vai sem cartão) e pergunte UMA vez qual
   cartão, fecha e vence que dia — então `POST {backend_url}/api/cards`.
```

(b) Em "Puxe antes de falar", depois da linha `  linha (achar o gasto que destoa).`, acrescente:

```
- `GET {backend_url}/api/cards` — fatura aberta (total, fecha, vence) e a
  fechada aguardando pagamento. Cite as duas em todo resumo do mês: é o
  dinheiro que ainda vai sair da conta.
```

(c) Troque a linha `   - Valor que varia (luz, cartão): anote "varia" e peça o número real.` por:

```
   - Valor que varia (conta de luz): anote "varia" e peça o número real. A
     fatura do cartão NÃO entra aqui — não é gasto, é a soma de compras já
     lançadas.
```

(d) Em "API local do sistema", troque o bloco que vai de `- Registrar gasto/ganho:` até `    2 minutos, mas não conte com isso: valores diferentes passariam.)` pelo mesmo bloco com estas mudanças:
   - o `-d` do exemplo passa a terminar em `"source": "chat", "wallet": "conta", "installments": 1}}'` (mantenha `{{`/`}}`);
   - depois da linha `  · occurred_on: ...` acrescente:
     ```
  · card: omita para usar o cartão padrão (gasto da conta). "none" para
    pix/débito/dinheiro. Nome do cartão para outro cartão. Nunca em VR/VA.
  · installments: parcelas (1-48). Com parcelas, amount_brl é o TOTAL.
    Nome de cartão desconhecido → 422: cadastre com POST /api/cards antes.
     ```
   - troque `  (aceita também \`wallet=conta|vr|va\`)` por `  (aceita também \`wallet=conta|vr|va\` e \`card_id=<uuid>\`)`;
   - depois da linha `- Apagar lançamento errado: ...` acrescente:
     ```
- Apagar uma compra parcelada inteira: `DELETE {backend_url}/api/cashflow/groups/<installment_group>`
- Cartões: `GET {backend_url}/api/cards` (cada um com `open_invoice` e
  `last_closed_invoice`: período, `closes_on`, `due_on`, `status`
  open|closed|past, `total_brl`) · `POST {backend_url}/api/cards`
  `{{"name": "Nubank", "closing_day": 25, "due_day": 3}}` · histórico:
  `GET {backend_url}/api/cards/<id>/invoices?months=6`
     ```

(e) Em "Arquivos recebidos", troque as duas linhas `- Extrato/fatura → resuma e registre os lançamentos relevantes; liste o que` / `  registrou (evite duplicar lançamento que o cliente já contou no chat).` por:

```
- Extrato bancário → registre os lançamentos relevantes com `"card": "none"`
  (é dinheiro que saiu da conta), pulando o pagamento da fatura do cartão.
- Fatura do cartão → concilie linha a linha com
  `GET {backend_url}/api/cashflow?card_id=<id>&month=<mês>` no período da
  fatura e lance SÓ o que falta. Linha parcelada ("TV 03/10") → lance a
  compra INTEIRA retroativa: amount_brl = parcela × n, installments = n,
  occurred_on = data da compra original (data da parcela na fatura menos k−1
  meses); a API gera as parcelas passadas e futuras. Antes, confira que as
  parcelas não existem. Liste o que registrou.
```

Em `_SEED_CHAT_MEMORY`, troque `Valor variável (conta de luz, cartão): escreva "varia" no valor e registre o` / `número real quando o cliente contar.` por:

```
Valor variável (conta de luz): escreva "varia" no valor e registre o número
real quando o cliente contar. Cartões de crédito ficam em `GET /api/cards`,
não aqui — e a fatura NÃO é gasto fixo (é a soma de compras já lançadas).
```

- [ ] **Step 4: Rodar os testes**

Run: `.venv/bin/python -m pytest tests/test_chat_service.py -q`
Expected: PASS. (Se `KeyError`/`IndexError` no `.format`, há `{` sem dobrar no texto novo.)

- [ ] **Step 5: Lint e commit**

```bash
.venv/bin/ruff check app/ tests/ && .venv/bin/ruff format app/ tests/ && .venv/bin/python -m pytest -q
git add app/services/chat_service.py tests/test_chat_service.py
git commit -m "feat(consultant): card, installment and invoice rules in the standing orders"
```

---

### Task 11: Aviso de fechamento de fatura (`insight_service`, regra 3)

**Files:**
- Modify: `app/services/insight_service.py`, `scripts/daily_insights.py` (docstring)
- Test: `tests/test_insight_service.py` (acrescentar ao final)

**Interfaces:**
- Consumes: `card_service.list_cards`, `invoice_window`, `build_invoice` (Tasks 2–3).
- Produces: `run_daily` envia `💳 Fatura do <cartão> fechou: R$ X · vence dd/mm. N lançamentos.` no dia seguinte ao fechamento, uma vez por cartão e data, fora do orçamento semanal; estado em `state["card_closing_fired"][card_id] = closes_on ISO`.

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao final de `tests/test_insight_service.py`:

```python
# --- rule 3: card invoice closed -----------------------------------------------

from app.schemas.card import CardCreate  # noqa: E402
from app.services import card_service  # noqa: E402


def _card_with_spend(session: Session) -> None:
    card = card_service.create_card(
        session, CardCreate(name="Nubank", closing_day=25, due_day=3)
    )
    session.add(
        CashflowEntry(
            kind=CashflowKind.EXPENSE,
            amount_brl=Decimal("3412.90"),
            category="mercado",
            occurred_on=date(2026, 9, 10),
            card_id=card.id,
        )
    )
    session.commit()


def test_invoice_closing_notice_fires_the_morning_after_once(
    session: Session, state_path: Path, notified: list[str]
) -> None:
    _card_with_spend(session)
    # Closing day itself: purchases can still land, so nothing yet.
    insight_service.run_daily(session, today=date(2026, 9, 25))
    assert notified == []
    result = insight_service.run_daily(session, today=date(2026, 9, 26))
    assert len(notified) == 1
    assert notified[0].startswith("💳 Fatura do Nubank fechou: R$ 3.412,90 · vence 03/10.")
    assert "1 lançamento." in notified[0]
    assert result["sent"][0]["kind"] == "card_closing"
    # Same day again (or later): no repeat for the same closing date.
    insight_service.run_daily(session, today=date(2026, 9, 26))
    insight_service.run_daily(session, today=date(2026, 9, 27))
    assert len(notified) == 1
    assert json.loads(state_path.read_text())["card_closing_fired"] != {}


def test_empty_invoice_does_not_notify(
    session: Session, state_path: Path, notified: list[str]
) -> None:
    card_service.create_card(session, CardCreate(name="Nubank", closing_day=25, due_day=3))
    insight_service.run_daily(session, today=date(2026, 9, 26))
    assert notified == []


def test_closing_notice_ignores_the_weekly_budget(
    session: Session, state_path: Path, notified: list[str]
) -> None:
    _card_with_spend(session)
    state_path.write_text(json.dumps({"week": {"key": "2026-W39", "sent": 2}}))
    insight_service.run_daily(session, today=date(2026, 9, 26))  # ISO week 39
    assert len(notified) == 1
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_insight_service.py -q -k "closing or empty_invoice"`
Expected: FAIL (`notified == []` no dia 26).

- [ ] **Step 3: Implementar**

Em `app/services/insight_service.py`:

1. Import: `from app.services import card_service, cashflow_service, notification_center`.
2. Atualize o docstring do módulo: troque `Two rules, evaluated once a day` por `Three rules, evaluated once a day` e acrescente, depois do item 2, o parágrafo:

```
3. **Card invoice closed** — the morning AFTER a card's closing day (the
   closing day itself still takes purchases), one notice per card per
   closing date with the total and the due date. It is a bill, not an
   insight, so it bypasses the weekly push budget; an empty invoice is
   silent. State: ``"card_closing_fired": {"<card id>": "<closes_on ISO>"}``.
```

3. Antes de `# --- daily entrypoint`, acrescente:

```python
# --- rule 3: card invoice closed ---------------------------------------------------


def _evaluate_card_closings(session: Session, today: date) -> list[tuple[str, date, Insight]]:
    """Cards whose invoice closed YESTERDAY → (card id, closing date, notice).

    Evaluated the morning after, not on the closing day: purchases made on
    the closing day still enter that invoice. Empty invoices are skipped —
    there is nothing to pay.
    """
    yesterday = today - timedelta(days=1)
    out: list[tuple[str, date, Insight]] = []
    for card in card_service.list_cards(session):
        window = card_service.invoice_window(card, yesterday.year, yesterday.month)
        if window.closes_on != yesterday:
            continue
        invoice = card_service.build_invoice(
            session, card, yesterday.year, yesterday.month, today=today
        )
        if invoice.entries == 0:
            continue
        plural = "s" if invoice.entries != 1 else ""
        text = (
            f"💳 Fatura do {card.name} fechou: {_fmt(invoice.total_brl)} · "
            f"vence {invoice.due_on.strftime('%d/%m')}. "
            f"{invoice.entries} lançamento{plural}."
        )
        out.append((str(card.id), window.closes_on, Insight(kind="card_closing", text=text)))
    return out
```

4. Em `run_daily`, logo depois do bloco da regra 2 (após `anomaly_fired[month_key] = sorted(...)`) e ANTES de `# Weekly push budget`, acrescente:

```python
    # Rule 3 — a closed invoice is a bill, not an insight: it goes out
    # regardless of the weekly budget, once per card per closing date.
    closing_fired = state.get("card_closing_fired")
    if not isinstance(closing_fired, dict):
        closing_fired = {}
    bills: list[Insight] = []
    for card_id, closes_on, notice in _evaluate_card_closings(session, today):
        if closing_fired.get(card_id) == closes_on.isoformat():
            continue
        closing_fired[card_id] = closes_on.isoformat()
        bills.append(notice)
    state["card_closing_fired"] = closing_fired
```

5. Ainda em `run_daily`, logo antes de `state["week"] = {"key": week_key, "sent": sent_this_week}`, acrescente `to_send = bills + to_send`. O loop de envio existente (`for insight in to_send: notification_center.notify(insight.text, kind=NotificationKind.LEDGER)`) passa a ser:

```python
    for insight in to_send:
        notification_center.notify(
            insight.text,
            kind=NotificationKind.LEDGER,
            url="/extrato" if insight.kind == "card_closing" else None,
        )
```

6. Em `scripts/daily_insights.py`, troque `Runs the two insight rules (run-rate balance projection + per-category` / `anomaly)` por `Runs the three insight rules (run-rate balance projection, per-category` / `anomaly, card-invoice-closed notice)`.

- [ ] **Step 4: Rodar os testes**

Run: `.venv/bin/python -m pytest tests/test_insight_service.py -q`
Expected: PASS (os testes antigos continuam: sem cartão, a regra 3 é silenciosa).

- [ ] **Step 5: Lint e commit**

```bash
.venv/bin/ruff check app/ tests/ scripts/ && .venv/bin/ruff format app/ tests/ scripts/ && .venv/bin/python -m pytest -q
git add app/services/insight_service.py scripts/daily_insights.py tests/test_insight_service.py
git commit -m "feat(insights): notify the morning after a card invoice closes"
```

---
### Task 12: Frontend — tipos e funções de API + hook `useCards`

**Files:**
- Modify: `frontend/src/lib/api.ts` (seção "Personal cashflow")
- Create: `frontend/src/hooks/use-cards.ts`

**Interfaces:**
- Produces: tipos `InvoiceStatus`, `CardInvoice`, `CreditCard`, `CardCreate`, `CardUpdate`; `CashflowEntry.card_id/card_name/installment_no/installment_count/installment_group`; `CashflowCreate.card?/installments?`; `CashflowSummary.card_expense_brl`; funções `fetchCards`, `createCard`, `updateCard`, `deleteCard`, `deleteCashflowGroup`; hook `useCards() → { cards, error, refresh }`.

- [ ] **Step 1: Tipos e funções em `api.ts`**

Em `CashflowEntry`, depois de `wallet: CashflowWallet;`:

```ts
  /** Card the purchase went on; null = pix/debit/cash/benefit card. */
  card_id: string | null;
  card_name: string | null;
  /** 1-based installment number and total; null on a single payment. */
  installment_no: number | null;
  installment_count: number | null;
  installment_group: string | null;
```

Em `CashflowCreate`, depois de `wallet?: CashflowWallet;`:

```ts
  /** "none" for pix/debit/cash, a card name, or omitted for the default card. */
  card?: string | null;
  /** Monthly installments (1–48); amount_brl is then the TOTAL. */
  installments?: number;
```

Em `CashflowSummary`, depois de `entries: number;`: `card_expense_brl: number;`.

Depois de `deleteCashflowEntry`, acrescente:

```ts
/** Delete every monthly row of one installment purchase. */
export const deleteCashflowGroup = async (
  groupId: string,
): Promise<{ deleted: number }> =>
  json<{ deleted: number }>(
    await fetch(`${API_BASE}/api/cashflow/groups/${groupId}`, { method: "DELETE" }),
  );

// ── Credit cards (invoices are computed by the backend, never stored) ───────

export type InvoiceStatus = "open" | "closed" | "past";

export type CardInvoice = {
  card_id: string;
  period_start: string;
  period_end: string;
  closes_on: string;
  due_on: string;
  status: InvoiceStatus;
  total_brl: number;
  entries: number;
};

export type CreditCard = {
  id: string;
  name: string;
  closing_day: number;
  due_day: number;
  is_default: boolean;
  created_at: string;
  open_invoice: CardInvoice;
  last_closed_invoice: CardInvoice | null;
};

export type CardCreate = {
  name: string;
  closing_day: number;
  due_day: number;
  is_default?: boolean;
};

export type CardUpdate = Partial<CardCreate>;

export const fetchCards = async (): Promise<CreditCard[]> =>
  json<CreditCard[]>(await fetch(`${API_BASE}/api/cards`));

export const createCard = async (payload: CardCreate): Promise<CreditCard> =>
  json<CreditCard>(
    await fetch(`${API_BASE}/api/cards`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );

export const updateCard = async (
  id: string,
  payload: CardUpdate,
): Promise<CreditCard> =>
  json<CreditCard>(
    await fetch(`${API_BASE}/api/cards/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );

export const deleteCard = async (id: string): Promise<CreditCard> =>
  json<CreditCard>(
    await fetch(`${API_BASE}/api/cards/${id}`, { method: "DELETE" }),
  );
```

- [ ] **Step 2: Hook**

`frontend/src/hooks/use-cards.ts`:

```ts
"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchCards, type CreditCard } from "@/lib/api";

/**
 * Every card with its computed invoices. `cards` stays null until the first
 * load resolves (or fails), so screens can tell "loading" from "no cards".
 */
export const useCards = () => {
  const [cards, setCards] = useState<CreditCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const list = await fetchCards();
        if (cancelled) return;
        setCards(list);
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Erro ao carregar cartões");
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [version]);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  return { cards, error, refresh };
};
```

- [ ] **Step 3: Validar e commitar**

Run: `cd frontend && pnpm lint && pnpm type-check`
Expected: limpo (nada consome os tipos novos ainda; os campos novos em `CashflowEntry` são obrigatórios e nenhum literal do tipo existe no front).

```bash
git add frontend/src/lib/api.ts frontend/src/hooks/use-cards.ts
git commit -m "feat(frontend): card and installment types, card API client and useCards hook"
```

---

### Task 13: Ajustes — cadastro de cartões

**Files:**
- Modify: `frontend/src/app/(dashboard)/configuracoes/page.tsx`

**Interfaces:**
- Consumes: `useCards`, `createCard`, `updateCard`, `deleteCard`, `CreditCard` (Task 12).

- [ ] **Step 1: Imports**

Troque `import { useCallback, useEffect, useState } from "react";` por `import { useCallback, useEffect, useState, type FormEvent } from "react";` e `import { API_BASE, sendPushTest } from "@/lib/api";` por:

```ts
import {
  API_BASE,
  createCard,
  deleteCard,
  sendPushTest,
  updateCard,
  type CreditCard,
} from "@/lib/api";
import { useCards } from "@/hooks/use-cards";
```

- [ ] **Step 2: Renderizar a seção**

Logo depois de `<NotificationsCard />` no JSX, acrescente `<CardsCard />`.

- [ ] **Step 3: Componente**

Acrescente ao FINAL do arquivo:

```tsx
const inputStyle = {
  borderColor: "var(--border)",
  background: "var(--bg-card)",
  color: "var(--text-primary)",
} as const;

/**
 * The client's credit cards. Closing and due days are what turn ledger rows
 * into invoices; the default card is where an account expense lands when
 * the sentence does not say how it was paid.
 */
const CardsCard = () => {
  const { cards, error, refresh } = useCards();
  const [name, setName] = useState("");
  const [closingDay, setClosingDay] = useState("");
  const [dueDay, setDueDay] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setNote(null);
    setBusy(true);
    try {
      await createCard({
        name: name.trim(),
        closing_day: Number(closingDay),
        due_day: Number(dueDay),
      });
      setName("");
      setClosingDay("");
      setDueDay("");
      refresh();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Não foi possível cadastrar o cartão.");
    } finally {
      setBusy(false);
    }
  };

  const makeDefault = async (card: CreditCard) => {
    setNote(null);
    try {
      await updateCard(card.id, { is_default: true });
      refresh();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Não foi possível alterar o padrão.");
    }
  };

  const remove = async (card: CreditCard) => {
    setNote(null);
    try {
      await deleteCard(card.id);
      refresh();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Não foi possível remover o cartão.");
    }
  };

  return (
    <section
      className="p-5 md:p-6 rounded-md space-y-4"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      <h3
        className="text-xl tracking-tight"
        style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
      >
        Cartões
      </h3>
      <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
        Tudo que você compra vai no cartão padrão, salvo quando disser pix,
        débito ou dinheiro. Fechamento e vencimento definem a fatura.
      </p>

      {cards && cards.length === 0 && (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          Nenhum cartão ainda. Cadastre o primeiro abaixo.
        </p>
      )}

      {cards && cards.length > 0 && (
        <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
          {cards.map((card) => (
            <li
              key={card.id}
              className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3"
            >
              <div className="min-w-0">
                <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                  {card.name}
                  {card.is_default && (
                    <span
                      className="ml-2 text-[10px] uppercase tracking-[0.14em]"
                      style={{ color: "var(--accent)" }}
                    >
                      padrão
                    </span>
                  )}
                </p>
                <p className="text-[12px]" style={{ color: "var(--text-muted)" }}>
                  fecha dia {card.closing_day} · vence dia {card.due_day}
                </p>
              </div>
              <div className="flex gap-2">
                {!card.is_default && (
                  <button
                    type="button"
                    onClick={() => void makeDefault(card)}
                    className="min-h-[2.75rem] rounded-md border px-3 text-[13px] font-medium"
                    style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
                  >
                    Tornar padrão
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => void remove(card)}
                  className="min-h-[2.75rem] rounded-md border px-3 text-[13px] font-medium"
                  style={{ borderColor: "var(--border)", color: "var(--danger)" }}
                >
                  Remover
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <form
        onSubmit={(event) => void submit(event)}
        className="grid gap-3 sm:grid-cols-[1fr_6rem_6rem_auto] sm:items-end"
      >
        <label className="flex flex-col gap-1 text-[12px]" style={{ color: "var(--text-muted)" }}>
          Nome
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            maxLength={40}
            placeholder="Nubank"
            className="min-h-[2.75rem] rounded-md border px-3 text-base"
            style={inputStyle}
          />
        </label>
        <label className="flex flex-col gap-1 text-[12px]" style={{ color: "var(--text-muted)" }}>
          Fecha dia
          <input
            type="number"
            inputMode="numeric"
            min={1}
            max={31}
            required
            value={closingDay}
            onChange={(event) => setClosingDay(event.target.value)}
            className="min-h-[2.75rem] rounded-md border px-3 text-base"
            style={inputStyle}
          />
        </label>
        <label className="flex flex-col gap-1 text-[12px]" style={{ color: "var(--text-muted)" }}>
          Vence dia
          <input
            type="number"
            inputMode="numeric"
            min={1}
            max={31}
            required
            value={dueDay}
            onChange={(event) => setDueDay(event.target.value)}
            className="min-h-[2.75rem] rounded-md border px-3 text-base"
            style={inputStyle}
          />
        </label>
        <button
          type="submit"
          disabled={busy}
          className="min-h-[2.75rem] rounded-md px-5 text-sm font-semibold disabled:opacity-40"
          style={{ background: "var(--accent)", color: "white" }}
        >
          Cadastrar
        </button>
      </form>

      {error && (
        <p className="text-sm" style={{ color: "var(--danger)" }}>
          {error}
        </p>
      )}
      {note && (
        <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
          {note}
        </p>
      )}
    </section>
  );
};
```

- [ ] **Step 4: Validar no navegador e commitar**

Run: `cd frontend && pnpm lint && pnpm type-check && pnpm build`
Expected: limpo. Suba `./start.sh` no desktop, abra `/configuracoes`, cadastre "Nubank · 25 · 3", veja o selo "padrão", cadastre um segundo e use "Tornar padrão"; remova o segundo.

```bash
git add "frontend/src/app/(dashboard)/configuracoes/page.tsx"
git commit -m "feat(frontend): credit card registry in settings"
```

---

### Task 14: Extrato — bloco da fatura, selo de cartão/parcela e exclusão da compra

**Files:**
- Modify: `frontend/src/app/(dashboard)/extrato/page.tsx`

**Interfaces:**
- Consumes: `useCards`, `deleteCashflowGroup`, `CreditCard`, `CashflowEntry.card_name/installment_*`, `CashflowSummary.card_expense_brl` (Task 12).

- [ ] **Step 1: Imports e helpers**

Troque o import de `@/lib/api` por:

```ts
import {
  currentMonth,
  deleteCashflowEntry,
  deleteCashflowGroup,
  type CashflowEntry,
  type CategoryTotal,
  type CreditCard,
} from "@/lib/api";
import { useCards } from "@/hooks/use-cards";
```

Depois de `dayLabel`, acrescente:

```ts
const shortDate = (iso: string): string =>
  parseLocalDate(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });

const daysUntil = (iso: string): number => {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.max(0, Math.round((parseLocalDate(iso).getTime() - today.getTime()) / 86_400_000));
};
```

- [ ] **Step 2: Componente do bloco de fatura**

Depois de `CategoryBars`, acrescente:

```tsx
/** The open invoice per card, plus the last closed one while it waits to be paid. */
const InvoiceBlock = ({ cards }: { cards: CreditCard[] }) => (
  <section className="mt-9">
    <h3
      className="text-[11px] uppercase tracking-[0.18em]"
      style={{ color: "var(--text-muted)" }}
    >
      Cartão
    </h3>
    <div className="mt-3.5 flex flex-col gap-3">
      {cards.map((card) => {
        const open = card.open_invoice;
        const closed = card.last_closed_invoice;
        const days = daysUntil(open.closes_on);
        return (
          <div
            key={card.id}
            className="rounded-lg border px-4 py-4"
            style={{ borderColor: "var(--border)", background: "var(--bg-card)" }}
          >
            <div className="flex items-baseline justify-between gap-3">
              <p
                className="text-[12px] font-semibold uppercase tracking-[0.1em]"
                style={{ color: "var(--text-secondary)" }}
              >
                {card.name}
              </p>
              <p className="text-[12px]" style={{ color: "var(--text-muted)" }}>
                fatura aberta
              </p>
            </div>
            <p
              className="tabular mt-1 text-[1.75rem] leading-none"
              style={{ fontFamily: "var(--font-heading)", color: "var(--text-primary)" }}
            >
              {formatBRL(open.total_brl)}
            </p>
            <p className="mt-2 text-[12px]" style={{ color: "var(--text-muted)" }}>
              fecha {shortDate(open.closes_on)} ({days === 0 ? "hoje" : `${days} dias`}) · vence{" "}
              {shortDate(open.due_on)}
            </p>
            {closed && (
              <p
                className="mt-3 border-t pt-3 text-[13px]"
                style={{
                  borderColor: "var(--border)",
                  color: closed.status === "past" ? "var(--text-muted)" : "var(--text-primary)",
                }}
              >
                {closed.status === "past"
                  ? `Última fatura ${formatBRL(closed.total_brl)}, venceu ${shortDate(closed.due_on)}`
                  : `Fatura fechada · ${formatBRL(closed.total_brl)} · vence ${shortDate(closed.due_on)}`}
              </p>
            )}
          </div>
        );
      })}
    </div>
  </section>
);
```

- [ ] **Step 3: Estado, exclusão de grupo e render**

Em `ExtratoPage`, depois de `const { entries, summary, loading, error, refresh } = useCashflow(month);`, acrescente `const { cards } = useCards();`.

Depois da função `remove`, acrescente:

```ts
  const removeGroup = async (groupId: string) => {
    setOpenId(null);
    setDeleteError(null);
    try {
      await deleteCashflowGroup(groupId);
      refresh();
    } catch {
      setDeleteError("Não foi possível excluir a compra parcelada.");
    }
  };

  const cardExpense = summary?.card_expense_brl ?? 0;
```

Logo depois do bloco `{benefitWallets.length > 0 && (...)}` (ainda dentro da `<section className="mt-7">`), acrescente:

```tsx
        {cardExpense > 0 && (
          <p className="tabular mt-2 text-[12px]" style={{ color: "var(--text-muted)" }}>
            no cartão {formatBRL(cardExpense)}
          </p>
        )}
```

Logo depois do fechamento dessa `</section>` (antes de `{expenses.length > 0 && (`), acrescente:

```tsx
      {cards && cards.length > 0 && <InvoiceBlock cards={cards} />}
      {cards && cards.length === 0 && (
        <p className="mt-6 text-[13px]" style={{ color: "var(--text-muted)" }}>
          <Link href="/configuracoes" className="underline underline-offset-4">
            Cadastre seu cartão em Ajustes
          </Link>{" "}
          para acompanhar a fatura aqui.
        </p>
      )}
```

Na linha secundária do lançamento, troque

```tsx
                          {entry.category}
                          {entry.wallet !== "conta" && ` · ${entry.wallet.toUpperCase()}`}
```

por

```tsx
                          {entry.category}
                          {entry.card_name && ` · ${entry.card_name}`}
                          {entry.installment_no !== null &&
                            entry.installment_count !== null &&
                            ` · ${entry.installment_no}/${entry.installment_count}`}
                          {entry.wallet !== "conta" && ` · ${entry.wallet.toUpperCase()}`}
```

No `map` dos lançamentos, logo depois de `const open = openId === entry.id;`, acrescente `const group = entry.installment_group;`. No painel expandido, troque o `<div className="flex items-center justify-between gap-3 px-4 pb-3 text-[12px]" ...>` inteiro por:

```tsx
                          <div
                            className="flex flex-wrap items-center justify-between gap-3 px-4 pb-3 text-[12px]"
                            style={{ color: "var(--text-muted)" }}
                          >
                            <span>Registrado pelo {sourceLabel(entry.source)}</span>
                            <span className="flex gap-2">
                              {group && (
                                <button
                                  type="button"
                                  onClick={() => void removeGroup(group)}
                                  className="flex min-h-[2.25rem] items-center gap-1.5 rounded-md border px-3 font-medium"
                                  style={{ borderColor: "var(--border)", color: "var(--danger)" }}
                                >
                                  <Trash2 size={14} strokeWidth={1.9} />
                                  Excluir compra ({entry.installment_count} parcelas)
                                </button>
                              )}
                              <button
                                type="button"
                                onClick={() => void remove(entry.id)}
                                className="flex min-h-[2.25rem] items-center gap-1.5 rounded-md border px-3 font-medium"
                                style={{ borderColor: "var(--border)", color: "var(--danger)" }}
                              >
                                <Trash2 size={14} strokeWidth={1.9} />
                                {group ? "Excluir parcela" : "Excluir"}
                              </button>
                            </span>
                          </div>
```

Atualize o comentário do componente: troque `only deletion survives, because a` / `misclassified line needs a one-tap correction, not a round trip.` por `only deletion survives (one row, or a whole installment purchase), because a misclassified line needs a one-tap correction, not a round trip.`

- [ ] **Step 4: Validar e commitar**

Run: `cd frontend && pnpm lint && pnpm type-check && pnpm build`
Expected: limpo. No navegador (`/extrato`), com um cartão cadastrado: bloco "Cartão" com fatura aberta; lance pela API uma compra em 3x (`curl -X POST localhost:8000/api/cashflow -H 'Content-Type: application/json' -d '{"kind":"expense","amount_brl":300,"category":"lazer","description":"tv","installments":3}'`) e veja "lazer · Nubank · 1/3" e os dois botões ao expandir.

```bash
git add "frontend/src/app/(dashboard)/extrato/page.tsx"
git commit -m "feat(frontend): invoice block, card badges and installment delete in the statement"
```

---

### Task 15: Visão geral — linha do cartão no card "O mês"

**Files:**
- Modify: `frontend/src/app/(dashboard)/page.tsx`

**Interfaces:**
- Consumes: `useCards`, `CashflowSummary.card_expense_brl` (Task 12).

- [ ] **Step 1: Imports**

Acrescente `import { useCards } from "@/hooks/use-cards";` depois de `import { usePortfolioHistory } ...`, e troque `import { formatBRLCompact, parseLocalDate } from "@/lib/format";` por `import { formatBRL, formatBRLCompact, parseLocalDate } from "@/lib/format";`.

- [ ] **Step 2: Data da próxima fatura**

Depois de `const netColor = ...;` (antes do `return (`), acrescente:

```ts
  const { cards } = useCards();
  // The soonest bill: a closed invoice waiting for its due date, else the
  // open one. ISO dates sort chronologically as strings.
  const nextDue = useMemo(() => {
    if (!cards || cards.length === 0) return null;
    const dues = cards.map((card) => {
      const closed = card.last_closed_invoice;
      return closed && closed.status === "closed" ? closed.due_on : card.open_invoice.due_on;
    });
    return [...dues].sort()[0] ?? null;
  }, [cards]);
  const nextDueLabel =
    nextDue === null
      ? null
      : parseLocalDate(nextDue).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
```

- [ ] **Step 3: Render**

Dentro de `<div className="md:self-center">`, logo depois de `<FlowRails income={cashflow.income_brl} expense={cashflow.expense_brl} />`, acrescente:

```tsx
                {cashflow.card_expense_brl > 0 && nextDueLabel && (
                  <p className="tabular mt-4 text-[12px]" style={{ color: "var(--text-muted)" }}>
                    No cartão {formatBRL(cashflow.card_expense_brl)} · fatura vence {nextDueLabel}
                  </p>
                )}
```

- [ ] **Step 4: Validar e commitar**

Run: `cd frontend && pnpm lint && pnpm type-check && pnpm build`
Expected: limpo; em `/` a linha aparece sob os trilhos quando há gasto no cartão no mês.

```bash
git add "frontend/src/app/(dashboard)/page.tsx"
git commit -m "feat(frontend): card spend and next invoice due date on the overview"
```

---
### Task 16: Documentação

**Files:**
- Modify: `docs/03-dominio.md`, `docs/06-api.md`, `docs/07-frontend.md`, `docs/04-motor-ia.md`, `docs/12-decisoes.md`, `docs/13-estado-atual.md`, `CLAUDE.md`

- [ ] **Step 1: `docs/03-dominio.md`**

Na lista de tabelas do topo (linha `CashflowEntry   (ledger pessoal: gasto/ganho)`), acrescente abaixo: `CreditCard      (cartão de crédito: fechamento, vencimento, padrão)`.

Depois do parágrafo **Deduplicação** da seção `CashflowEntry`, acrescente:

```markdown
**Cartão de crédito (`card_id`, 2026-09-12):** compra no cartão é gasto em
`conta` (o dinheiro sai da conta no vencimento) com `card_id` apontando para
um `CreditCard`. **Regime de competência**: conta no mês da compra
(`occurred_on`); pagar a fatura NUNCA vira lançamento. Regra do padrão em
`card_service.resolve_card`: `card` ausente → cartão padrão se `kind=expense`
e `wallet=conta`; `none`/`pix`/`debito`/`dinheiro` → sem cartão; nome
desconhecido → 422 (nunca cai no padrão em silêncio). Cartão em `income` ou
em VR/VA → 422. Os apelidos `cartao`/`credito` saíram de `_WALLET_ALIASES`:
cartão não é carteira.

**Parcelas:** `installments` (1–48) expande em N linhas, uma por mês
(`_add_months` clampa o dia a partir da data ORIGINAL: 31/jan → 28/fev →
31/mar), `amount_brl` do payload é o TOTAL, centavos sobrando na parcela 1
(`_split_installments`). As N linhas compartilham `installment_group` e
levam `installment_no`/`installment_count`; `delete_group` apaga a compra
inteira. Parcelamento exige cartão.

### `CreditCard` — cartão de crédito

`name` (único após fold), `closing_day`, `due_day` (1–31, clampados ao fim do
mês curto), `is_default` (exatamente um enquanto houver cartões: o primeiro
vira padrão, promover outro rebaixa o anterior, remover o padrão promove o
mais antigo). **Faturas nunca são persistidas**: `card_service.invoice_window`
calcula `(fechamento anterior, fechamento]`, `due_on` = primeira ocorrência
de `due_day` estritamente após o fechamento, status `open` (`hoje ≤
fechamento`) · `closed` (até o vencimento) · `past`. Sem controle de
pagamento. `DELETE` só sem lançamentos (409).
```

Na seção **Migrações de schema**, no bloco de exemplo `_ADDED_COLUMNS`, acrescente a linha
`"cashflow_entry": {"wallet": "TEXT NOT NULL DEFAULT 'conta'", "card_id": "CHAR(32) REFERENCES credit_card(id)", ...},` e, após o bloco, a frase: `UUID no SQLite é \`CHAR(32)\`; coluna com \`REFERENCES\` só entra por \`ALTER TABLE\` com default NULL (e \`create_all\` já criou a tabela pai antes).`

- [ ] **Step 2: `docs/06-api.md`**

Na tabela de `/api/cashflow`:
- linha `POST` ``: acrescente ao final da célula: `, \`card?\` (omitido = cartão padrão p/ gasto em conta; \`none\`/\`pix\`/\`debito\`/\`dinheiro\` = sem cartão; nome = cartão cadastrado, desconhecido → **422**), \`installments?\` (1–48; N linhas, \`amount_brl\` = total, devolve a parcela 1). Resposta traz \`card_id\`, \`card_name\`, \`installment_no/count/group\``
- linha `GET` lista: troque `?month=YYYY-MM&kind=&wallet=&limit=100` por `?month=YYYY-MM&kind=&wallet=&card_id=&limit=100`
- linha `GET /summary`: acrescente `, \`card_expense_brl\`` depois de `entries`
- acrescente antes da linha `DELETE /{id}`: `| \`DELETE\` | \`/groups/{installment_group}\` | Apaga a compra parcelada inteira → \`{deleted}\`. 404 se nenhuma linha |`

Depois da tabela de cashflow (antes de `---` / Chat), acrescente:

```markdown
## Cartões de crédito — `/api/cards`

| Método | Rota | O que faz |
|---|---|---|
| `GET` | `` | Todos os cartões, cada um com `open_invoice` e `last_closed_invoice` (calculadas: `period_start/end`, `closes_on`, `due_on`, `status` open\|closed\|past, `total_brl`, `entries`) |
| `POST` | `` | Body `{name, closing_day 1–31, due_day 1–31, is_default?}`. **201.** O primeiro cartão vira padrão. 409 nome repetido |
| `PATCH` | `/{id}` | Campos opcionais. `is_default: true` rebaixa o anterior; `false` no único padrão → 422. 409 nome repetido |
| `DELETE` | `/{id}` | 409 se há lançamentos no cartão. Remover o padrão promove o mais antigo |
| `GET` | `/{id}/invoices?months=6` | Histórico de faturas (1–24), mais antiga primeiro, termina na aberta |
```

- [ ] **Step 3: `docs/07-frontend.md`**

Na árvore de **Estrutura**: troque `│       ├── extrato/          ledger pessoal, somente leitura` por `│       ├── extrato/          ledger pessoal + fatura do cartão, somente leitura`; troque `│       ├── configuracoes/    diagnóstico (/api/health)` por `│       ├── configuracoes/    diagnóstico, push, cadastro de cartões`; em `components/`, troque `8 componentes` por `10 componentes (+ privacy-toggle, values-shell)`; em `hooks/`, acrescente `use-cards`; em `lib/`, acrescente `privacy.ts`.

Depois da seção **Camada de dados**, acrescente:

```markdown
## Olhinho (ocultar valores)

`lib/privacy.ts` é um store mínimo (`useSyncExternalStore`) persistido em
`localStorage` (`assay.values-hidden`). Os três formatadores de moeda de
`lib/format.ts` (`formatBRL`, `formatBRLCompact`, `formatAmount`) leem o flag
e devolvem `••••` quando oculto — percentuais e quantidades continuam
visíveis. Como são funções puras chamadas no render, `ValuesShell` (no
layout) remonta a página ao alternar (`key` no wrapper): estado local da
tela reseta, o que é aceitável para uma ação rara. O botão (`PrivacyToggle`,
Lucide `Eye`/`EyeOff`) vive na sidebar e flutua ao lado do sino no celular.
Ao abrir o app com o flag salvo há um frame com valores visíveis antes da
remontagem — trade-off documentado, não bug.
```

- [ ] **Step 4: `docs/04-motor-ia.md`**

Na seção **Roteador de modelo**, depois do parágrafo que termina em `**Na dúvida, opus** continua valendo.`, acrescente:

```markdown
**"fatura" vai sempre para opus** (2026-09-12): "paguei a fatura 3200" tem
verbo no passado + valor e cairia no haiku, que lançaria um gasto fantasma de
R$ 3.200 — cada compra já está no ledger. A palavra está em `_ASKS_RE` e em
`_ADVICE_RE`, então sai do caminho rápido e do lookup.
```

Na seção **Classificador de gasto**, troque `(\`kind\`, \`amount_brl\`, \`category\`, \`description\`, \`occurred_on\` com data` / `relativa resolvida)` por `(\`kind\`, \`amount_brl\`, \`category\`, \`description\`, \`occurred_on\` com data relativa resolvida, \`card\` auto|none|nome, \`installments\`)`.

Na seção **Chat do consultor**, acrescente ao final:

```markdown
Ordens de cartão (2026-09-12): gasto da conta sem meio explícito vai sem
`card` (a API aplica o padrão); pix/débito/dinheiro → `"card": "none"`;
parcelas → `installments` + total; **pagamento de fatura NUNCA é lançado** —
o consultor lê `GET /api/cards` e concilia; fatura em PDF é conciliada linha a
linha contra `GET /api/cashflow?card_id=`. Cartões ficam no banco, não no
MEMORY.md.
```

- [ ] **Step 5: `docs/12-decisoes.md`**

Acrescente ao final:

```markdown
### D39 · Cartão de crédito: competência, cartão padrão e fatura que não é gasto
O cliente passa tudo no cartão. Três decisões: **(1) competência** — a compra
conta no mês em que foi feita (`occurred_on`), e pagar a fatura não gera
lançamento nenhum (seria contar cada compra duas vezes); a fatura é uma
visão calculada (`card_service`), nunca uma tabela. **(2) cartão é o
padrão** — gasto em `conta` sem meio de pagamento vai para o cartão padrão;
a regra mora em `resolve_card`, não em prompt, para valer em toda porta
(consultor, classificador, bot, API). Nome de cartão desconhecido é 422, não
fallback: um erro de digitação tem que voltar para quem lançou. **(3)
parcelas são linhas** — N linhas, uma por mês, no mesmo ledger, para que
resumo mensal, insights e histórico continuem corretos sem saber o que é
parcela. Efeitos colaterais: `cartao`/`credito` deixaram de ser apelidos de
carteira (cartão não é pote de dinheiro), e o roteador manda toda frase com
"fatura" para opus, porque "paguei a fatura 3200" tinha o formato exato de
um lançamento rápido. O aviso de fechamento sai no dia SEGUINTE (compra no
dia do fechamento ainda entra) e fora do orçamento semanal de insights (é
conta a pagar).
```

- [ ] **Step 6: `docs/13-estado-atual.md`**

Depois da linha `> Fotografia de 2026-09-06.` (atualize para `2026-09-12`), acrescente antes da seção de 2026-09-06:

```markdown
## 2026-09-12 — cartão de crédito e olhinho

Tabela `credit_card` + 4 colunas em `cashflow_entry` (migração automática no
boot). Cartão padrão para gasto da conta, parcelas expandidas em linhas,
fatura calculada (`/api/cards`), aviso no dia seguinte ao fechamento,
consultor/classificador/roteador com as regras (D39). No front: bloco de
fatura no extrato, cadastro em Ajustes, linha na visão geral e o **olhinho**
que mascara os formatadores de moeda (`lib/privacy.ts`). Sem variável de
ambiente nova. Depois do deploy no Pi: cadastrar o cartão em `/configuracoes`
(ou dizer ao consultor "meu cartão fecha dia X e vence dia Y").
```

Na tabela **Onde o repositório está**, atualize a linha de testes com a contagem real após `pytest -q`.

- [ ] **Step 7: `CLAUDE.md`**

No bullet **Ledger de finanças pessoais**, depois de `VR/VA = benefício, só comida — NUNCA contam como sobra investível.`, acrescente:

```markdown
  **Cartão de crédito (D39)**: `CreditCard` (fechamento/vencimento/padrão) +
  `card_id` no lançamento. Competência: conta no mês da compra; **pagar a
  fatura NUNCA é gasto**. Gasto em `conta` sem meio explícito → cartão padrão
  (`card_service.resolve_card`, única fonte da regra); `installments` expande
  em N linhas; faturas são calculadas (`/api/cards`), nunca gravadas; aviso
  no dia seguinte ao fechamento. Roteador: "fatura" → opus sempre.
```

- [ ] **Step 8: Commit**

```bash
git add docs/ CLAUDE.md
git commit -m "docs: credit card ledger, invoices and the privacy toggle"
```

---

### Task 17: Olhinho — store de privacidade e formatadores mascarados

**Files:**
- Create: `frontend/src/lib/privacy.ts`
- Modify: `frontend/src/lib/format.ts`

**Interfaces:**
- Produces: `valuesHidden(): boolean`, `setValuesHidden(next)`, `toggleValuesHidden()`, `hydrateValuesHidden()`, `useValuesHidden(): boolean`; `formatBRL`/`formatBRLCompact`/`formatAmount` devolvem `••••` quando oculto.

- [ ] **Step 1: Store**

`frontend/src/lib/privacy.ts`:

```ts
import { useSyncExternalStore } from "react";

/**
 * "Hide values" switch. A tiny external store so the money formatters (plain
 * functions) can read it synchronously, plus a hook for the toggle button.
 *
 * The flag starts as `false` on server and client alike: reading localStorage
 * during render would make the hydrated HTML disagree with the server's.
 * `hydrateValuesHidden()` applies the saved choice after mount instead.
 */

const STORAGE_KEY = "assay.values-hidden";
const listeners = new Set<() => void>();
let hidden = false;

const notifyAll = () => {
  for (const notify of listeners) notify();
};

export const valuesHidden = (): boolean => hidden;

export const setValuesHidden = (next: boolean): void => {
  if (next === hidden) return;
  hidden = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
  } catch {
    // Private mode or blocked storage: the choice lives for this page only.
  }
  notifyAll();
};

export const toggleValuesHidden = (): void => setValuesHidden(!hidden);

/** Apply the saved choice. Call once after mount, never during render. */
export const hydrateValuesHidden = (): void => {
  try {
    if (window.localStorage.getItem(STORAGE_KEY) === "1") setValuesHidden(true);
  } catch {
    // No storage: stay visible.
  }
};

const subscribe = (notify: () => void) => {
  listeners.add(notify);
  return () => {
    listeners.delete(notify);
  };
};
const getSnapshot = () => hidden;
const getServerSnapshot = () => false;

export const useValuesHidden = (): boolean =>
  useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
```

- [ ] **Step 2: Formatadores**

Em `frontend/src/lib/format.ts`, no topo: `import { valuesHidden } from "@/lib/privacy";` e, abaixo dos imports:

```ts
/** What money becomes while the eye is closed. Percentages and quantities
 *  stay visible: they do not give the absolute amounts away. */
const MASK = "••••";
```

Em `formatBRL`, depois de `if (value === null || value === undefined) return "–";`, acrescente `if (valuesHidden()) return \`R$ ${MASK}\`;` (o ` ` é o mesmo espaço não separável que o Intl usa). Em `formatAmount`, depois da mesma checagem de null, acrescente `if (valuesHidden()) return MASK;`. `formatBRLCompact` delega e já fica coberto.

- [ ] **Step 3: Validar e commitar**

Run: `cd frontend && pnpm lint && pnpm type-check`
Expected: limpo.

```bash
git add frontend/src/lib/privacy.ts frontend/src/lib/format.ts
git commit -m "feat(frontend): privacy store that masks money formatters"
```

---

### Task 18: Olhinho — botão, shell que remonta e posicionamento

**Files:**
- Create: `frontend/src/components/privacy-toggle.tsx`, `frontend/src/components/values-shell.tsx`
- Modify: `frontend/src/app/(dashboard)/layout.tsx`, `frontend/src/components/sidebar.tsx`

**Interfaces:**
- Consumes: `useValuesHidden`, `toggleValuesHidden`, `hydrateValuesHidden` (Task 17).

- [ ] **Step 1: Botão**

`frontend/src/components/privacy-toggle.tsx`:

```tsx
"use client";

import { Eye, EyeOff } from "lucide-react";
import { toggleValuesHidden, useValuesHidden } from "@/lib/privacy";

/**
 * The eye. Rendered twice by the shell, like the bell: inline in the desktop
 * sidebar, floating beside the bell on phones.
 */
export const PrivacyToggle = ({ variant }: { variant: "sidebar" | "floating" }) => {
  const hidden = useValuesHidden();
  const Icon = hidden ? EyeOff : Eye;
  const label = hidden ? "Mostrar valores" : "Ocultar valores";
  return (
    <button
      type="button"
      onClick={toggleValuesHidden}
      aria-label={label}
      aria-pressed={hidden}
      className={
        variant === "sidebar"
          ? "flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium w-full"
          : "md:hidden fixed right-[4.25rem] z-40 flex items-center justify-center h-11 w-11 rounded-full"
      }
      style={
        variant === "sidebar"
          ? { color: "var(--text-secondary)" }
          : {
              top: "calc(env(safe-area-inset-top) + 0.75rem)",
              background: "var(--bg-card)",
              border: "1px solid var(--border)",
              color: "var(--text-secondary)",
            }
      }
    >
      <Icon size={17} strokeWidth={1.8} />
      {variant === "sidebar" && label}
    </button>
  );
};
```

- [ ] **Step 2: Shell**

`frontend/src/components/values-shell.tsx`:

```tsx
"use client";

import { useEffect, type ReactNode } from "react";
import { hydrateValuesHidden, useValuesHidden } from "@/lib/privacy";

/**
 * Remounts the page when the eye is toggled.
 *
 * Money is formatted by plain functions that read the privacy flag, and a
 * page only re-renders when its own state changes — so the cheapest correct
 * way to repaint every figure (charts included) is a new `key`. Local UI
 * state resets on toggle; it is a rare action, and nothing is lost that a
 * tap cannot bring back.
 */
export const ValuesShell = ({ children }: { children: ReactNode }) => {
  const hidden = useValuesHidden();

  // Deferred a tick, like the bell's first load: the saved choice is applied
  // after hydration so server and client HTML agree.
  useEffect(() => {
    const timer = setTimeout(hydrateValuesHidden, 0);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div key={hidden ? "hidden" : "shown"} className="max-w-[1400px]">
      {children}
    </div>
  );
};
```

- [ ] **Step 3: Layout e sidebar**

Em `frontend/src/app/(dashboard)/layout.tsx`: acrescente `import { PrivacyToggle } from "@/components/privacy-toggle";` e `import { ValuesShell } from "@/components/values-shell";`; troque `<div className="max-w-[1400px]">{children}</div>` por `<ValuesShell>{children}</ValuesShell>`; e acrescente `<PrivacyToggle variant="floating" />` na linha imediatamente antes de `<NotificationsBell variant="floating" />`.

Em `frontend/src/components/sidebar.tsx`: acrescente `import { PrivacyToggle } from "@/components/privacy-toggle";` e, dentro de `<div className="mt-auto pt-8">`, acrescente `<PrivacyToggle variant="sidebar" />` na linha antes de `<NotificationsBell variant="sidebar" />`.

- [ ] **Step 4: Validar e commitar**

Run: `cd frontend && pnpm lint && pnpm type-check && pnpm build`
Expected: limpo. No navegador: em `/`, clique no olho → todos os valores em R$ viram `R$ ••••` (gráficos incluídos), percentuais continuam; recarregue → continua oculto; clique de novo → volta. No celular (largura < 768px) o olho flutua à esquerda do sino, sem sobrepor.

```bash
git add frontend/src/components/privacy-toggle.tsx frontend/src/components/values-shell.tsx "frontend/src/app/(dashboard)/layout.tsx" frontend/src/components/sidebar.tsx
git commit -m "feat(frontend): eye toggle that hides every money figure"
```

---

## Fechamento

- [ ] `make check` verde (ruff + pytest + lint/type-check/build).
- [ ] Deploy no Pi conforme `docs/09-operacao.md` (rsync excluindo `.venv node_modules .next storage .env`, `pnpm install && pnpm build` em `frontend/` com `BACKEND_ORIGIN` setado, `systemctl --user restart investimentos-backend investimentos-frontend`). O boot cria `credit_card` e as 4 colunas sozinho.
- [ ] No Pi, cadastrar o cartão em `/configuracoes` e conferir `journalctl --user -u investimentos-backend` sem erro de migração.

## Auto-revisão do plano

**Cobertura do spec** — §3.1/3.2 → Task 1; §4.1 → Tasks 2–3; §4.2 → Tasks 4–5; §4.3 → Task 11; §5.1 → Task 6; §5.2 → Task 7; §6.1 → Task 10; §6.2 → Task 9; §6.3 → Task 8; §7.1 → Task 12; §7.2 → Task 14; §7.3 → Task 13; §7.4 → Task 15; §8 → Fechamento; §9 → testes dentro de cada task; §10 → Task 16. Olhinho (pedido após o spec) → Tasks 17–18 e docs em Task 16.

**Consistência de nomes** — `card_service.resolve_card/list_cards/get_card/create_card/update_card/delete_card/invoice_window/build_invoice/invoices/card_summaries/shift_month` usados em Tasks 4, 6, 7, 11 batem com Tasks 2–3; `cashflow_service.delete_group` (Task 5) usado em Task 7; `CashflowRead.card_name` (Task 4) preenchido em Task 7 e lido em Task 14; `card_expense_brl` (Task 4) lido em Tasks 14–15; `useCards` (Task 12) usado em Tasks 13–15; `valuesHidden/useValuesHidden/toggleValuesHidden/hydrateValuesHidden` (Task 17) usados em Task 18.

**Nota sobre a rota `/groups`** — o spec dizia que a rota por UUID rejeitaria "groups" com 422 se viesse antes; na prática `/{entry_id}` só casa um segmento e `/groups/{id}` tem dois, então não há conflito. A ordem "groups antes" fica por clareza; o teste da Task 7 prova o comportamento.
