"""Weekly committee reviews and per-lot maturity reviews.

Both reuse the chained-session engine in ``analysis_runner`` (auto-resume on
limits, persistence, single-session context). Results are stored as ``Report``
rows (auditable, with every step) and pushed to Telegram.

The 30-day sell lock is PER PURCHASE LOT: each asset row carries its own
``entry_date``, so two buys of the same ticker on different dates mature
independently. Reviews treat each lot separately.
"""

from datetime import date
from typing import Any
from uuid import uuid4

import structlog
from sqlmodel import Session

from app.config import settings
from app.models.report import Report, ReportKind
from app.services import analysis_runner, market_data_service, portfolio_service, telegram_service

logger = structlog.get_logger()


async def fetch_macro() -> dict[str, Any]:
    """Live macro snapshot (BCB · Yahoo · CoinGecko)."""
    return await market_data_service.build_full_context()


def _positions_block(rows: list[dict[str, Any]], min_days: int) -> str:
    if not rows:
        return "(carteira vazia)"
    lines = [
        "ticker | classe | qtd | preço médio | preço atual | valor | P&L% | dias | status",
    ]
    for r in rows:
        days = r.get("days_in_portfolio", 0)
        status = "LIBERADO" if days >= min_days else f"travado ({min_days - days}d)"
        lines.append(
            f"{r['ticker']} | {r['asset_class']} | {r['quantity']} | "
            f"{r['avg_price']} | {r.get('current_price')} | {r['total_value']} | "
            f"{r.get('pnl_pct')} | {days} | {status}"
        )
    return "\n".join(lines)


def _macro_block(macro_ctx: dict[str, Any]) -> str:
    macro = macro_ctx.get("macro", {})
    ibov = macro_ctx.get("ibovespa", {})
    cg = macro_ctx.get("crypto_global", {})
    return (
        f"Selic={macro.get('selic')} | IPCA12m={macro.get('ipca_12m')} | "
        f"CDI={macro.get('cdi')} | USD/BRL={macro.get('usd_brl')} | "
        f"Ibov={ibov.get('level')} ({ibov.get('month_return_pct')}% 30d) | "
        f"BTC dom={cg.get('btc_dominance')}% | F&G={macro_ctx.get('fear_greed_index')}"
    )


_MANDATE = (
    "MANDATO: Renda Fixa = 100% CDB; Ações = só equities da B3 (sem FII/ETF/BDR); "
    "Crypto = agressivo (alto upside, risco controlado). Trava de venda é POR LOTE "
    f"({settings.min_holding_days} dias a partir da data de cada compra)."
)


def _weekly_steps(
    rows: list[dict[str, Any]], macro_ctx: dict[str, Any], today: date
) -> list[tuple[str, str]]:
    min_days = settings.min_holding_days
    analysis = (
        "[REVISÃO SEMANAL DO COMITÊ — leia ./MEMORY.md antes e atualize ao final]\n"
        f"Data: {today.isoformat()}\n"
        f"{_MANDATE}\n\n"
        f"Snapshot macro capturado:\n{_macro_block(macro_ctx)}\n\n"
        f"Carteira atual (cada linha é um LOTE com sua própria maturidade):\n"
        f"{_positions_block(rows, min_days)}\n\n"
        "Como uma MESA COMPLETA nível Goldman Sachs / J.P. Morgan (economista-chefe, "
        "estrategista de alocação, equity research B3, crypto on-chain, head de RF, "
        "quant, CRO, forensic, CIO), com carta branca de pesquisa (WebSearch/WebFetch "
        "+ seus MCPs: sequential-thinking, playwright, fetch), produza uma REVISÃO "
        "SEMANAL COMPLETA e profissional, com debate e decisão do CIO:\n"
        "1. Macro completo (Brasil + global) e o que mudou na semana — com dados ao vivo.\n"
        "2. Desempenho de CADA posição: busque o preço atual real, calcule P&L, e diga "
        "se a tese segue válida.\n"
        f"3. Para cada LOTE já LIBERADO (≥{min_days} dias): recomendação MANTER / VENDER / "
        "AUMENTAR com racional e gatilhos. Para lotes travados: status e plano.\n"
        "4. Riscos, alertas e oportunidades novas dentro do mandato (CDB / ações B3 / crypto).\n"
        "Seja rigoroso, cite números e fontes. NÃO cite corretora/exchange."
    )
    synthesis = (
        "Agora escreva o RELATÓRIO SEMANAL EXECUTIVO para o cliente, em português, "
        "enxuto e acionável (vai pro Telegram). Inclua:\n"
        "• Macro em 3-5 linhas (o que importa agora).\n"
        "• Desempenho da carteira (resumo + destaques positivos/negativos).\n"
        "• Ações sobre lotes liberados: tabela curta Ticker | Ação (manter/vender/aumentar) | "
        "motivo em 1 linha.\n"
        "• Alertas e o que observar na próxima semana.\n"
        "ANTES de escrever, ATUALIZE ./MEMORY.md com o que mudou. Depois entregue o relatório."
    )
    return [("Revisão semanal — análise", analysis), ("Revisão semanal — relatório", synthesis)]


def _maturity_steps(
    matured: list[dict[str, Any]], macro_ctx: dict[str, Any], today: date
) -> list[tuple[str, str]]:
    block = _positions_block(matured, settings.min_holding_days)
    analysis = (
        "[ANÁLISE DE MATURIDADE — lotes que acabaram de completar a trava]\n"
        f"Data: {today.isoformat()}\n"
        f"{_MANDATE}\n\n"
        f"Snapshot macro:\n{_macro_block(macro_ctx)}\n\n"
        f"Lotes recém-liberados para venda:\n{block}\n\n"
        "Leia ./MEMORY.md. Como mesa completa nível Goldman Sachs / J.P. Morgan "
        "(equity research, crypto, quant, CRO, CIO), com pesquisa ao vivo (WebSearch/"
        "WebFetch + MCPs), avalie CADA lote liberado: preço atual real vs. entrada, "
        "P&L, tese ainda válida? Recomendação clara MANTER / VENDER / AUMENTAR, com "
        "racional, preço-alvo e gatilhos de saída."
    )
    synthesis = (
        "Escreva o aviso EXECUTIVO de maturidade para o Telegram, em português, curto: "
        "para cada lote liberado, Ticker | Ação (manter/vender/aumentar) | motivo (1 linha) "
        "| alvo. Atualize ./MEMORY.md antes de responder."
    )
    return [("Maturidade — análise", analysis), ("Maturidade — aviso", synthesis)]


def _persist_report(
    session: Session,
    *,
    kind: ReportKind,
    title: str,
    summary: analysis_runner.RunSummary,
    macro_ctx: dict[str, Any],
    portfolio_rows: list[dict[str, Any]],
) -> Report:
    report = Report(
        kind=kind,
        title=title,
        content=summary.final_summary,
        cost_usd=summary.total_cost_usd,
        session_id=summary.session_id,
        macro_snapshot=macro_ctx,
        portfolio_snapshot={"assets": portfolio_rows},
        steps=[{"title": s.label, "response": s.result} for s in summary.steps],
    )
    session.add(report)
    session.commit()
    session.refresh(report)
    return report


def run_weekly_review(
    session: Session,
    *,
    macro_ctx: dict[str, Any],
    model: str = analysis_runner.DEFAULT_MODEL,
    effort: str = analysis_runner.DEFAULT_EFFORT,
    notify: bool = True,
    on_event: analysis_runner.EventCallback | None = None,
) -> Report:
    today = date.today()
    rows = portfolio_service.build_portfolio_snapshot(session)
    steps = _weekly_steps(rows, macro_ctx, today)
    summary = analysis_runner.run_chain(
        steps, run_id=str(uuid4()), model=model, effort=effort, on_event=on_event
    )
    report = _persist_report(
        session,
        kind=ReportKind.WEEKLY,
        title=f"Revisão semanal — {today.isoformat()}",
        summary=summary,
        macro_ctx=macro_ctx,
        portfolio_rows=rows,
    )
    if notify and telegram_service.is_enabled():
        telegram_service.notify(
            f"🗓️ Revisão semanal do comitê ({today.isoformat()})\n\n{summary.final_summary}"
        )
    logger.info("weekly_review_done", report_id=str(report.id), cost_usd=summary.total_cost_usd)
    return report


def run_maturity_review(
    session: Session,
    matured_rows: list[dict[str, Any]],
    *,
    macro_ctx: dict[str, Any],
    model: str = analysis_runner.DEFAULT_MODEL,
    effort: str = analysis_runner.DEFAULT_EFFORT,
    notify: bool = True,
    on_event: analysis_runner.EventCallback | None = None,
) -> Report | None:
    if not matured_rows:
        return None
    today = date.today()
    steps = _maturity_steps(matured_rows, macro_ctx, today)
    summary = analysis_runner.run_chain(
        steps, run_id=str(uuid4()), model=model, effort=effort, on_event=on_event
    )
    report = _persist_report(
        session,
        kind=ReportKind.MATURITY,
        title=f"Maturidade — {today.isoformat()}",
        summary=summary,
        macro_ctx=macro_ctx,
        portfolio_rows=matured_rows,
    )
    if notify and telegram_service.is_enabled():
        telegram_service.notify(
            f"🔓 Lotes liberados para venda — análise do comitê ({today.isoformat()})"
            f"\n\n{summary.final_summary}"
        )
    logger.info("maturity_review_done", report_id=str(report.id), assets=len(matured_rows))
    return report
