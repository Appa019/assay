"""Personal cashflow ledger: register and summarize expenses and income.

Written primarily by the Telegram consultant (Claude registers what the user
tells it over chat) and by the quick /gasto and /ganho bot commands. Category
names are normalized here — case, accents and known aliases — so the same
real-world category can never split into two buckets depending on which door
(consultant, classifier, bot, form) wrote it.
"""

import unicodedata
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import func
from sqlmodel import Session, select

from app.models.cashflow import CashflowEntry, CashflowKind
from app.schemas.cashflow import (
    CashflowCreate,
    CashflowSummary,
    CategoryTotal,
    MonthTotals,
)

logger = structlog.get_logger()

# The ONE category vocabulary. The consultant's standing orders and the
# classifier prompt both render THIS list — never their own copy — and
# ``normalize_category`` folds whatever still arrives onto it. Two prompts
# once carried divergent lists ("saúde"/"assinaturas" vs "saude"/"assinatura")
# and the monthly summary fragmented the same category into two lines.
CANONICAL_CATEGORIES: tuple[str, ...] = (
    "mercado",
    "restaurante",
    "transporte",
    "moradia",
    "saude",
    "lazer",
    "assinatura",
    "educacao",
    "vestuario",
    "pets",
    "viagem",
    "impostos",
    "presente",
    "salario",
    "freela",
    "dividendos",
    "reembolso",
    "outros",
)

# Legacy/synonym spellings (post accent-fold) → canonical bucket.
_CATEGORY_ALIASES: dict[str, str] = {
    "casa": "moradia",
    "aluguel": "moradia",
    "assinaturas": "assinatura",
    "freelance": "freela",
    "alimentacao": "mercado",
    "supermercado": "mercado",
    "farmacia": "saude",
    "imposto": "impostos",
    "presentes": "presente",
    "viagens": "viagem",
    "pet": "pets",
    "restaurantes": "restaurante",
}


def _fold_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def normalize_category(raw: str | None) -> str:
    """Fold case/accents and known aliases onto the canonical vocabulary.

    Free-form categories remain allowed (the user may invent one) — the
    guarantee is only that the SAME category always lands as the SAME string.
    """
    value = _fold_accents((raw or "").strip().lower()).strip()[:64]
    if not value:
        return "outros"
    return _CATEGORY_ALIASES.get(value, value)


class CashflowNotFoundError(LookupError):
    """The requested cashflow entry does not exist."""


def _month_bounds(month: str) -> tuple[date, date]:
    """'YYYY-MM' → (first day, last day). Raises ValueError on bad input."""
    year_s, _, month_s = month.partition("-")
    year, mon = int(year_s), int(month_s)
    if not 1 <= mon <= 12:
        raise ValueError(f"Mês inválido: {month}")
    return date(year, mon, 1), date(year, mon, monthrange(year, mon)[1])


# An identical entry arriving within this window is treated as a repeat of the
# same POST, not as a second purchase. The consultant sometimes posts, fails to
# read the response, and posts again — which silently doubled an expense in the
# ledger. Two genuine identical purchases minutes apart still both land.
_DUPLICATE_WINDOW_S = 120


def _recent_duplicate(session: Session, entry: CashflowEntry) -> CashflowEntry | None:
    """An entry identical in every field, written moments ago."""
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=_DUPLICATE_WINDOW_S)
    return session.exec(
        select(CashflowEntry)
        .where(
            CashflowEntry.kind == entry.kind,
            CashflowEntry.amount_brl == entry.amount_brl,
            CashflowEntry.category == entry.category,
            CashflowEntry.occurred_on == entry.occurred_on,
            CashflowEntry.description == entry.description,
            CashflowEntry.created_at >= cutoff,
        )
        .order_by(CashflowEntry.created_at.desc())
    ).first()


def add_entry(session: Session, data: CashflowCreate) -> CashflowEntry:
    entry = CashflowEntry(
        kind=data.kind,
        amount_brl=data.amount_brl,
        category=normalize_category(data.category),
        description=(data.description or "").strip() or None,
        occurred_on=data.occurred_on or date.today(),
        source=data.source,
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


def list_entries(
    session: Session,
    *,
    month: str | None = None,
    kind: CashflowKind | None = None,
    limit: int = 100,
) -> list[CashflowEntry]:
    stmt = select(CashflowEntry)
    if month:
        start, end = _month_bounds(month)
        stmt = stmt.where(CashflowEntry.occurred_on >= start, CashflowEntry.occurred_on <= end)
    if kind is not None:
        stmt = stmt.where(CashflowEntry.kind == kind)
    stmt = stmt.order_by(CashflowEntry.occurred_on.desc(), CashflowEntry.created_at.desc())
    return list(session.exec(stmt.limit(limit)).all())


def delete_entry(session: Session, entry_id: UUID) -> CashflowEntry:
    entry = session.get(CashflowEntry, entry_id)
    if entry is None:
        raise CashflowNotFoundError(f"Lançamento {entry_id} não encontrado")
    session.delete(entry)
    session.commit()
    return entry


def month_summary(session: Session, month: str | None = None) -> CashflowSummary:
    month = month or date.today().strftime("%Y-%m")
    entries = list_entries(session, month=month, limit=10_000)

    income = sum(float(e.amount_brl) for e in entries if e.kind == CashflowKind.INCOME)
    expense = sum(float(e.amount_brl) for e in entries if e.kind == CashflowKind.EXPENSE)

    buckets: dict[tuple[CashflowKind, str], list[float]] = {}
    for e in entries:
        buckets.setdefault((e.kind, e.category), []).append(float(e.amount_brl))
    by_category = sorted(
        (
            CategoryTotal(
                kind=kind, category=category, total_brl=round(sum(vals), 2), count=len(vals)
            )
            for (kind, category), vals in buckets.items()
        ),
        key=lambda c: c.total_brl,
        reverse=True,
    )

    return CashflowSummary(
        month=month,
        income_brl=round(income, 2),
        expense_brl=round(expense, 2),
        net_brl=round(income - expense, 2),
        entries=len(entries),
        by_category=by_category,
    )


def month_history(session: Session, months: int = 6) -> list[MonthTotals]:
    """Totals per month, oldest first, ending on the current month.

    One call instead of one per month: the consultant needs the trend to say
    anything useful about whether spending is drifting, and asking it to stitch
    six requests together is both slow and easy to get wrong. A single GROUP BY
    replaces the former query-per-month loop; months without entries still
    appear, zeroed, so the trend line has no holes.
    """
    months = max(1, min(months, 36))
    today = date.today()
    first_year, first_mon = divmod(today.year * 12 + (today.month - 1) - (months - 1), 12)
    start = date(first_year, first_mon + 1, 1)

    month_expr = func.strftime("%Y-%m", CashflowEntry.occurred_on)
    rows = session.exec(
        select(
            month_expr,
            CashflowEntry.kind,
            func.coalesce(func.sum(CashflowEntry.amount_brl), 0),
            func.count(),
        )
        .where(CashflowEntry.occurred_on >= start)
        .group_by(month_expr, CashflowEntry.kind)
    ).all()

    totals: dict[str, dict[str, float]] = {}
    for label, kind, total, count in rows:
        bucket = totals.setdefault(str(label), {"income": 0.0, "expense": 0.0, "entries": 0.0})
        bucket["income" if kind == CashflowKind.INCOME else "expense"] = float(total)
        bucket["entries"] += int(count)

    out: list[MonthTotals] = []
    for offset in range(months - 1, -1, -1):
        year, mon = divmod(today.year * 12 + (today.month - 1) - offset, 12)
        label = f"{year:04d}-{mon + 1:02d}"
        bucket = totals.get(label, {"income": 0.0, "expense": 0.0, "entries": 0.0})
        out.append(
            MonthTotals(
                month=label,
                income_brl=round(bucket["income"], 2),
                expense_brl=round(bucket["expense"], 2),
                net_brl=round(bucket["income"] - bucket["expense"], 2),
                entries=int(bucket["entries"]),
            )
        )
    return out
