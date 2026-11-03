#!/usr/bin/env python3
"""Consolidated monthly report — cheap cron (no Claude involved).

Self-gating: runs on the first days of the month and reports the PREVIOUS
month once (skips if that month's report already exists; ``--force`` re-runs
for the current month). Content: portfolio value and month delta, per-class
allocation, trades of the month with realized P&L, analysis spend, benchmark
excerpt and IR/DARF status. Saved as Report(kind=monthly) and sent to
Telegram as text + a .md attachment.

    python scripts/monthly_report.py [--force]
"""

import argparse
import asyncio
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlmodel import Session, select  # noqa: E402

from app.core.database import engine, init_db  # noqa: E402
from app.models.chat import ChatMessage, ChatRole  # noqa: E402
from app.models.contribution import ContributionPrompt  # noqa: E402
from app.models.notification import NotificationKind, NotificationLevel  # noqa: E402
from app.models.portfolio_snapshot import PortfolioSnapshot  # noqa: E402
from app.models.report import Report, ReportKind  # noqa: E402
from app.models.trade import Trade  # noqa: E402
from app.services import (  # noqa: E402
    notification_center,
    portfolio_service,
    price_refresh_service,
    tax_service,
)


def _month_bounds(ref: date) -> tuple[date, date]:
    first_this = ref.replace(day=1)
    last_prev = first_this - timedelta(days=1)
    return last_prev.replace(day=1), last_prev


def _fmt(value: float) -> str:
    integer, decimals = f"{value:,.2f}".split(".")
    return f"R$ {integer.replace(',', '.')},{decimals}"


def _local_day(dt: datetime) -> date:
    """Local calendar date for a stored UTC-naive timestamp (A5 pattern)."""
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone().date()


def build_report(session: Session, start: date, end: date) -> str:
    label = start.strftime("%Y-%m")
    summary = portfolio_service.get_portfolio_summary(session)
    alloc = summary.allocation

    snaps = list(
        session.exec(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.snapshot_date >= start - timedelta(days=5))
            .where(PortfolioSnapshot.snapshot_date <= end)
            .order_by(PortfolioSnapshot.snapshot_date)
        ).all()
    )
    month_delta = ""
    if len(snaps) >= 2:
        first, last = float(snaps[0].total_value), float(snaps[-1].total_value)
        if first > 0:
            month_delta = f" ({(last - first) / first * 100:+.2f}% no mês, sem ajuste de aportes)"

    trades = list(
        session.exec(
            select(Trade)
            .where(Trade.executed_at >= datetime(start.year, start.month, 1, tzinfo=UTC))
            .where(
                Trade.executed_at
                < datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
            )
            .order_by(Trade.executed_at)
        ).all()
    )
    spend = session.exec(
        select(ContributionPrompt)
        .where(ContributionPrompt.responded_at >= datetime(start.year, start.month, 1, tzinfo=UTC))
        .where(
            ContributionPrompt.responded_at
            < datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
        )
    ).all()
    cost = sum(p.cost_usd or 0 for p in spend)

    tax = tax_service.build_year_report(session, start.year)
    tax_month = next((m for m in tax["months"] if m["month"] == label), None)

    lines = [
        f"# Relatório mensal — {label}",
        "",
        f"**Patrimônio:** {_fmt(alloc.total_value)}{month_delta}",
        f"- Renda Fixa (CDB): {_fmt(alloc.fixed_income)} ({alloc.fixed_income_pct:.1f}%)",
        f"- Ações B3: {_fmt(alloc.stocks)} ({alloc.stocks_pct:.1f}%)",
        f"- Crypto: {_fmt(alloc.crypto)} ({alloc.crypto_pct:.1f}%)",
        "",
        f"## Operações do mês ({len(trades)})",
    ]
    if trades:
        for t in trades:
            pnl = (
                f" · P&L {_fmt(float(t.realized_pnl_brl))} ({t.realized_pnl_pct:+.1f}%)"
                if t.realized_pnl_brl is not None
                else ""
            )
            lines.append(
                f"- {_local_day(t.executed_at).isoformat()} {t.side.upper()} {t.ticker}: "
                f"{float(t.quantity)} @ {_fmt(float(t.price))} = {_fmt(float(t.total_brl))}{pnl}"
            )
    else:
        lines.append("- (nenhuma)")

    lines += ["", "## IR do mês"]
    if tax_month:
        for label_cls, key in (("Ações", "stocks"), ("Crypto", "crypto")):
            data = tax_month.get(key, {})
            status = "isento" if data.get("exempt") else f"DARF {_fmt(data.get('tax_due_brl', 0))}"
            lines.append(f"- {label_cls}: vendas {_fmt(data.get('sales_brl', 0))} → {status}")
    else:
        lines.append("- Sem vendas tributáveis no mês.")

    # Router feedback loop: without this there is zero visibility on whether
    # the model router is tiering turns sensibly (or silently falling back).
    chat_rows = list(
        session.exec(
            select(ChatMessage)
            .where(ChatMessage.role == ChatRole.ASSISTANT)
            .where(ChatMessage.created_at >= datetime(start.year, start.month, 1, tzinfo=UTC))
            .where(
                ChatMessage.created_at
                < datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
            )
        ).all()
    )
    lines += ["", f"## Consultor no mês ({len(chat_rows)} respostas)"]
    if chat_rows:
        tiers: dict[str, int] = {}
        for m in chat_rows:
            key = m.tier or "sem tier (fallback/erro)"
            tiers[key] = tiers.get(key, 0) + 1
        lines.append(
            "- Tiers do roteador: " + " · ".join(f"{k}: {v}" for k, v in sorted(tiers.items()))
        )
    else:
        lines.append("- (nenhuma conversa)")

    lines += [
        "",
        f"## Custo de análise no mês: US$ {cost:.2f}",
        "",
        "_Gerado automaticamente. IR simplificado: confira com seu contador._",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Relatório mensal consolidado")
    parser.add_argument("--force", action="store_true", help="Gerar para o mês CORRENTE agora")
    args = parser.parse_args()

    init_db()
    today = date.today()
    if args.force:
        start, end = today.replace(day=1), today
    else:
        start, end = _month_bounds(today)
    title = f"Relatório mensal · {start.strftime('%Y-%m')}"

    try:
        with Session(engine) as session:
            exists = session.exec(
                select(Report).where(Report.kind == ReportKind.MONTHLY).where(Report.title == title)
            ).first()
            if exists is not None and not args.force:
                print(f"{title} já gerado — nada a fazer.")
                return 0
            asyncio.run(price_refresh_service.refresh_prices(session))
            content = build_report(session, start, end)
            report = exists or Report(kind=ReportKind.MONTHLY, title=title, content=content)
            report.content = content
            session.add(report)
            session.commit()
        notification_center.notify(content, kind=NotificationKind.REVIEW)
        print(f"{title} salvo e enviado.")
        return 0
    except Exception as exc:  # noqa: BLE001 — a broken cron must alert, not vanish
        notification_center.notify(
            notification_center.failure_text("Relatório mensal", exc),
            kind=NotificationKind.SYSTEM,
            level=NotificationLevel.ERROR,
        )
        print(f"monthly_report falhou: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
