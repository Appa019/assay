"""Deterministic insights over the personal cashflow ledger — zero LLM.

Two rules, evaluated once a day by ``scripts/daily_insights.py`` and pushed
over Telegram. Both the decision AND the copy are plain arithmetic and
f-strings; no model is ever consulted.

1. **Run-rate balance projection** — month-to-date spend extrapolated to the
   full month vs the income the month can be expected to bring (the income
   already registered this month or, when higher, the average of the last six
   tracked months). Fires only when the month projects NEGATIVE, once per
   month per crossing: when the projection returns to positive the alert
   re-arms, exactly like ``scripts/check_alerts.py`` does for price levels.

2. **Category anomaly** — a category's month-to-date spend vs its own
   day-prorated baseline built from the 12 weeks preceding the current month.
   Fires when the deviation exceeds 40% AND the absolute delta exceeds
   R$ 100. A category only arms once at least 6 of the baseline weeks contain
   entries — the ledger is young, and with less history than that the rule
   would only produce false positives. One alert per category per month.

State lives in ``storage/insights_state.json`` and is parsed tolerantly: a
malformed file is logged, discarded and rebuilt — it never crashes the cron.
Shape:

    {
      "projection_fired": {"2026-08": true},        // false = re-armed
      "anomaly_fired":    {"2026-08": ["mercado"]},
      "week":             {"key": "2026-W34", "sent": 2},
      "queue":            [{"kind": "...", "text": "...", "queued_at": "..."}],
      "last_digest_week": "2026-W33"
    }

A weekly budget caps pushes at ``_MAX_PUSHES_PER_WEEK``; the overflow is
queued in the state and delivered by the Sunday digest instead. Note on
dates: all the math runs on ``CashflowEntry.occurred_on`` (already a calendar
date) and ``date.today()`` (already local) — no UTC-naive timestamp is ever
turned into a calendar date here.
"""

import json
from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from sqlmodel import Session, select

from app.models.asset import Asset
from app.models.cashflow import CashflowKind
from app.services import cashflow_service, telegram_service

logger = structlog.get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE_PATH = _PROJECT_ROOT / "storage" / "insights_state.json"

_MAX_PUSHES_PER_WEEK = 2
# Run-rate on day 1-4 is dominated by whichever bill happened to land first;
# both rules stay silent until the month has a minimally meaningful sample.
_MIN_ELAPSED_DAYS = 5
_INCOME_LOOKBACK_MONTHS = 6
_ANOMALY_BASELINE_WEEKS = 12
_ANOMALY_MIN_WEEKS = 6
_ANOMALY_DEVIATION = 0.40
_ANOMALY_MIN_DELTA_BRL = 100.0

_MONTH_NAMES = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


@dataclass(frozen=True)
class Insight:
    """One triggered insight, ready to push (or queue for the digest)."""

    kind: str  # "projection" | "anomaly"
    text: str
    category: str | None = None


# --- state (tolerant JSON on disk) ---------------------------------------------


def _load_state() -> dict[str, Any]:
    try:
        raw = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("insights_state_unreadable_reset", error=str(exc))
        return {}
    if not isinstance(raw, dict):
        logger.warning("insights_state_wrong_shape_reset")
        return {}
    return raw


def _save_state(state: dict[str, Any]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")


def _month_map(state: dict[str, Any], key: str, month_key: str) -> dict[str, Any]:
    """A per-month sub-dict, pruned to the current month (tolerant of garbage)."""
    value = state.get(key)
    if not isinstance(value, dict):
        value = {}
    state[key] = {month_key: value[month_key]} if month_key in value else {}
    return state[key]


def _queue(state: dict[str, Any]) -> list[dict[str, Any]]:
    value = state.get("queue")
    if not isinstance(value, list):
        value = []
    state["queue"] = [q for q in value if isinstance(q, dict) and isinstance(q.get("text"), str)]
    return state["queue"]


def _week_key(day: date) -> str:
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


# --- formatting ----------------------------------------------------------------


def _fmt(value: float) -> str:
    integer, decimals = f"{value:,.2f}".split(".")
    return f"R$ {integer.replace(',', '.')},{decimals}"


# --- rule 1: run-rate balance projection ---------------------------------------


def _evaluate_projection(session: Session, today: date) -> tuple[bool, Insight | None]:
    """(month projects negative?, insight to push). The bool drives re-arming."""
    elapsed_days = today.day
    if elapsed_days < _MIN_ELAPSED_DAYS:
        return False, None
    month_key = today.strftime("%Y-%m")
    summary = cashflow_service.month_summary(session, month_key)
    if summary.entries == 0 or summary.expense_brl <= 0:
        return False, None

    average_income = cashflow_service.average_monthly_income(
        session, months=_INCOME_LOOKBACK_MONTHS, before=today
    )
    # "What the month can be expected to bring": the income already registered,
    # or the historical average when it is higher (salary not landed yet).
    # Summing the two would double-count a salary that already arrived.
    expected_income = max(summary.income_brl, average_income)
    if expected_income <= 0:
        # Expense-only ledger: "in the red" is meaningless, every month would fire.
        return False, None

    days_in_month = monthrange(today.year, today.month)[1]
    projected_expense = summary.expense_brl / elapsed_days * days_in_month
    deficit = projected_expense - expected_income
    if deficit <= 0:
        return False, None

    top = next((c for c in summary.by_category if c.kind == CashflowKind.EXPENSE), None)
    brake = (
        f" — dá pra evitar segurando {top.category} ({_fmt(top.total_brl)} no mês)" if top else ""
    )
    month_name = _MONTH_NAMES[today.month - 1]
    text = (
        f"⚠️ Nesse ritmo você fecha {month_name} {_fmt(deficit)} no vermelho: "
        f"gasto projetado de {_fmt(projected_expense)} contra {_fmt(expected_income)} "
        f"de ganhos esperados{brake}."
    )
    return True, Insight(kind="projection", text=text)


# --- rule 2: category anomaly --------------------------------------------------


def _evaluate_anomalies(session: Session, today: date) -> list[Insight]:
    """Categories spending ahead of their own 12-week baseline, biggest delta first."""
    elapsed_days = today.day
    if elapsed_days < _MIN_ELAPSED_DAYS:
        return []
    month_key = today.strftime("%Y-%m")
    summary = cashflow_service.month_summary(session, month_key)
    if summary.entries == 0:
        return []

    # Baseline: the 12 full weeks BEFORE this month, so the month under test
    # can never contaminate its own reference.
    baseline_end = today.replace(day=1) - timedelta(days=1)
    weekly = cashflow_service.category_week_totals(
        session, weeks=_ANOMALY_BASELINE_WEEKS, end=baseline_end
    )

    flagged: list[tuple[float, Insight]] = []
    for cat in summary.by_category:
        if cat.kind != CashflowKind.EXPENSE:
            continue
        buckets = weekly.get(cat.category)
        if buckets is None:
            continue
        # Young-ledger guard: without enough weeks of real history the
        # "baseline" is noise and every month looks anomalous.
        weeks_with_entries = sum(1 for total in buckets if total > 0)
        if weeks_with_entries < _ANOMALY_MIN_WEEKS:
            continue
        daily_baseline = sum(buckets) / (len(buckets) * 7)
        expected_to_date = daily_baseline * elapsed_days
        if expected_to_date <= 0:
            continue
        delta = cat.total_brl - expected_to_date
        if cat.total_brl <= expected_to_date * (1 + _ANOMALY_DEVIATION):
            continue
        if delta <= _ANOMALY_MIN_DELTA_BRL:
            continue
        pct_above = (cat.total_brl / expected_to_date - 1) * 100
        text = (
            f"📈 Gasto fora do padrão em {cat.category}: {_fmt(cat.total_brl)} no mês "
            f"até dia {today.day:02d}, {pct_above:.0f}% acima do seu normal para esta "
            f"altura ({_fmt(expected_to_date)}). Diferença de {_fmt(delta)}."
        )
        flagged.append((delta, Insight(kind="anomaly", text=text, category=cat.category)))

    flagged.sort(key=lambda pair: pair[0], reverse=True)
    return [insight for _delta, insight in flagged]


# --- daily entrypoint ----------------------------------------------------------


def run_daily(session: Session, *, today: date | None = None) -> dict[str, Any]:
    """Evaluate every rule, push what fits the weekly budget, queue the rest.

    Returns ``{"date", "sent", "queued"}`` where sent/queued are lists of
    ``{"kind", "text"}``. State is persisted BEFORE notifying (check_alerts
    pattern): a Telegram blip may drop one push but can never double-fire.
    """
    today = today or date.today()
    month_key = today.strftime("%Y-%m")
    state = _load_state()

    triggered: list[Insight] = []

    # Rule 1 — fired once per month per crossing, re-armed when back in band.
    projection_fired = _month_map(state, "projection_fired", month_key)
    in_the_red, projection = _evaluate_projection(session, today)
    already_fired = bool(projection_fired.get(month_key))
    if in_the_red and projection is not None and not already_fired:
        triggered.append(projection)
        projection_fired[month_key] = True
    elif not in_the_red and already_fired:
        projection_fired[month_key] = False  # re-armed for the next crossing

    # Rule 2 — deduped per category per month (no re-arm inside the month).
    anomaly_fired = _month_map(state, "anomaly_fired", month_key)
    fired_categories = anomaly_fired.get(month_key)
    if not isinstance(fired_categories, list):
        fired_categories = []
    for insight in _evaluate_anomalies(session, today):
        if insight.category in fired_categories:
            continue
        triggered.append(insight)
        fired_categories.append(insight.category)
    anomaly_fired[month_key] = sorted(str(c) for c in fired_categories)

    # Weekly push budget: the overflow waits for the Sunday digest.
    week_key = _week_key(today)
    week = state.get("week")
    if not isinstance(week, dict) or week.get("key") != week_key:
        week = {"key": week_key, "sent": 0}
    try:
        sent_this_week = int(week.get("sent", 0))
    except (TypeError, ValueError):
        sent_this_week = 0

    queue = _queue(state)
    to_send: list[Insight] = []
    to_queue: list[Insight] = []
    for insight in triggered:
        if sent_this_week < _MAX_PUSHES_PER_WEEK:
            to_send.append(insight)
            sent_this_week += 1
        else:
            to_queue.append(insight)
            queue.append(
                {
                    "kind": insight.kind,
                    "text": insight.text,
                    "queued_at": datetime.now(UTC).isoformat(),
                }
            )
    state["week"] = {"key": week_key, "sent": sent_this_week}
    _save_state(state)

    # Success side-effect strictly AFTER the state is persisted; notify() never
    # raises, so a failed send cannot roll anything back.
    for insight in to_send:
        telegram_service.notify(insight.text)

    result = {
        "date": today.isoformat(),
        "sent": [{"kind": i.kind, "text": i.text} for i in to_send],
        "queued": [{"kind": i.kind, "text": i.text} for i in to_queue],
    }
    if to_send or to_queue:
        logger.info("insights_evaluated", sent=len(to_send), queued=len(to_queue))
    return result


# --- weekly digest -------------------------------------------------------------


def build_weekly_digest(session: Session, *, today: date | None = None) -> str | None:
    """The Sunday digest: both halves of the money plus the queued insights.

    Month balance and top spending categories come from ``month_summary``;
    total invested wealth is included when there are Assets. Returns ``None``
    when the month's ledger is empty — nothing worth sending. Read-only: the
    queue is only cleared by ``mark_digest_sent`` after a successful send.
    """
    today = today or date.today()
    month_key = today.strftime("%Y-%m")
    summary = cashflow_service.month_summary(session, month_key)
    if summary.entries == 0:
        return None

    month_name = _MONTH_NAMES[today.month - 1]
    mood = "no azul" if summary.net_brl >= 0 else "no vermelho"
    lines = [
        f"📒 Resumo financeiro — {month_name} até dia {today.day:02d}",
        "",
        f"Saldo do mês: {_fmt(summary.net_brl)} ({mood})",
        f"• Ganhos: {_fmt(summary.income_brl)} · Gastos: {_fmt(summary.expense_brl)}",
    ]

    top_expenses = [c for c in summary.by_category if c.kind == CashflowKind.EXPENSE][:3]
    if top_expenses:
        lines += ["", "Maiores gastos do mês:"]
        lines += [
            f"{i}. {c.category} — {_fmt(c.total_brl)} ({c.count}x)"
            for i, c in enumerate(top_expenses, 1)
        ]

    invested = _total_invested(session)
    if invested is not None:
        lines += ["", f"Patrimônio investido: {_fmt(invested)}"]

    queued_texts = [q["text"] for q in _queue(_load_state())]
    if queued_texts:
        lines += ["", "Insights da semana que ficaram na fila:"]
        lines += [f"• {text}" for text in queued_texts]

    return "\n".join(lines)


def _total_invested(session: Session) -> float | None:
    """Mark-to-market total of every Asset lot; None when the portfolio is empty."""
    assets = list(session.exec(select(Asset)).all())
    if not assets:
        return None
    total = 0.0
    for asset in assets:
        price = asset.current_price if asset.current_price is not None else asset.avg_price
        total += float(asset.quantity) * float(price)
    return round(total, 2)


def digest_already_sent(*, today: date | None = None) -> bool:
    """Whether this ISO week's digest already went out (cron self-gating)."""
    today = today or date.today()
    return _load_state().get("last_digest_week") == _week_key(today)


def mark_digest_sent(*, today: date | None = None) -> None:
    """Record a delivered digest: clears the insight queue and stamps the week."""
    today = today or date.today()
    state = _load_state()
    state["queue"] = []
    state["last_digest_week"] = _week_key(today)
    _save_state(state)
