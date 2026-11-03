"""Weekly committee reviews and per-lot maturity reviews.

Both reuse the chained-session engine in ``analysis_runner`` (auto-resume on
limits, persistence, single-session context). Results are stored as ``Report``
rows (auditable, with every step) and announced in the app.

The sell lock is PER PURCHASE LOT and PER CLASS (stocks 30d, crypto 7d, CDB
none): each asset row carries its own ``entry_date``, so two buys of the same
ticker on different dates mature independently. Reviews treat each lot
separately.
"""

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

import structlog
from sqlmodel import Session, select

from app.config import settings
from app.models.asset import Asset
from app.models.cashflow import CashflowEntry
from app.models.notification import NotificationKind
from app.models.report import Report, ReportKind
from app.models.trade import Trade
from app.services import (
    analysis_runner,
    market_data_service,
    notification_center,
    notification_service,
    order_service,
    portfolio_service,
)

logger = structlog.get_logger()

# The weekly review is the cadence everything else hangs off: the aporte reads
# it (delta mode in meeting #1) and the maturity job defers to it.
WEEKLY_INTERVAL_DAYS = 7


def _last_weekly(session: Session) -> Report | None:
    return session.exec(
        select(Report)
        .where(Report.kind == ReportKind.WEEKLY)
        .order_by(Report.created_at.desc())
        .limit(1)
    ).first()


def last_weekly_age_days(session: Session) -> int | None:
    """Whole days since the last weekly review. None when there is none yet."""
    last = _last_weekly(session)
    if last is None:
        return None
    age = datetime.now(UTC) - last.created_at.replace(tzinfo=UTC)
    return max(0, age.days)


def days_until_weekly_due(session: Session, *, interval_days: int = WEEKLY_INTERVAL_DAYS) -> float:
    """Days until the weekly review is due; 0.0 when it is due (or overdue).

    Counted in calendar days, not hours: the report is stamped when the run
    ENDS (~02:24) and the timer checks at ~02:10, so "7 x 24h" was 13 minutes
    short every week and the review slid to every 8th day — leaving the next
    contribution one day outside the macro delta window.
    """
    due_on = weekly_due_on(session, interval_days=interval_days)
    if due_on is None:
        return 0.0
    today = analysis_runner._local_date(datetime.now(UTC))
    return float(max(0, (due_on - today).days))


def weekly_due_on(session: Session, *, interval_days: int = WEEKLY_INTERVAL_DAYS) -> date | None:
    """Local calendar day the next weekly review is due (past = overdue)."""
    last = _last_weekly(session)
    if last is None:
        return None
    return analysis_runner._local_date(last.created_at) + timedelta(days=interval_days)


async def fetch_macro() -> dict[str, Any]:
    """Live macro snapshot (BCB · Yahoo · CoinGecko)."""
    return await market_data_service.build_full_context()


def has_reviewable_data(session: Session) -> bool:
    """True when the committee has ANYTHING to look at.

    Cost guard for the expensive review chain: with no position, no trade
    history and no personal ledger there is literally nothing to review, and
    a full opus run would burn dollars describing an empty book. Lives here
    (not in the callers) so every surface — timers, CLI, API — shares
    the same invariant.
    """
    for model in (Asset, Trade, CashflowEntry):
        if session.exec(select(model).limit(1)).first() is not None:
            return True
    return False


def _positions_block(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "(carteira vazia)"
    lines = [
        "ticker | classe | qtd | preço médio | preço atual | valor | P&L% | dias | status"
        " | alvo | stop | tese registrada",
    ]
    for r in rows:
        days = r.get("days_in_portfolio", 0)
        lock_left = int(r.get("lock_days_left") or 0)
        if r.get("asset_class") == "fixed_income":
            status = "liquidez diária"
        elif lock_left > 0:
            status = f"travado ({lock_left}d, trava de {r.get('lock_days_total')}d)"
        else:
            status = "LIBERADO"
        thesis = (r.get("thesis") or "—").replace("\n", " ")[:160]
        lines.append(
            f"{r['ticker']} | {r['asset_class']} | {r['quantity']} | "
            f"{r['avg_price']} | {r.get('current_price')} | {r['total_value']} | "
            f"{r.get('pnl_pct')} | {days} | {status} | "
            f"{r.get('target_price') or '—'} | {r.get('stop_price') or '—'} | {thesis}"
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
    "MANDATO: Renda Fixa = só CDB Bradesco 100% CDI liquidez diária (instrumento "
    "único e fixo — a decisão é quanto, nunca qual CDB); Ações = só equities da B3 "
    "(sem FII/ETF/BDR); "
    "Crypto = agressivo (alto upside, risco controlado). Trava de venda POR LOTE: "
    f"AÇÕES {settings.min_holding_days} dias (exigência de compliance do cliente) e "
    f"CRYPTO {settings.min_holding_days_crypto} dias; CDB tem liquidez "
    "diária (dry powder) e pode ser vendido a qualquer momento para aproveitar "
    "oportunidades."
)


# Reports are DOCUMENTS read in the app (Telegram is off since D30): the old
# "pronto para o Telegram" format put the agent's own preamble, 8-11 emoji
# headers and run-on "•" bullets on every page.
_REPORT_FORMAT = (
    "FORMATO: documento em markdown, começando DIRETO pelo conteúdo (nada de "
    '"memória atualizada" ou "segue o relatório"). Títulos com `##`, listas '
    "com `-` (um item por linha), números em pt-BR (1.234,56), sem emoji e sem "
    "travessão (—)."
)
# Machine block the app turns into the "O que fazer" strip above the prose.
_ACTIONS_BLOCK = (
    'Ao FINAL, depois de uma linha "---", um bloco ```json com '
    '{"acoes": [{"tipo": "comprar"|"vender"|"manter", "ticker": str, '
    '"classe": "cdb"|"acoes_b3"|"crypto", "valor_brl": number|null, '
    '"preco_alvo": number|null, "stop": number|null, "motivo": str}]} com '
    "SÓ o que o cliente precisa executar (vender CDB para comprar X = uma linha "
    '"vender" do CDB e uma "comprar" por ativo). Nada a fazer = '
    '{"acoes": []}. Esse bloco é lido pelo app e não aparece no texto.'
)


def parse_actions_block(text: str) -> list[dict[str, Any]]:
    """The LAST valid ``{"acoes": [...]}`` json block of a report, or []."""
    for match in reversed(order_service._JSON_BLOCK.findall(text or "")):
        try:
            data = json.loads(match)
        except json.JSONDecodeError:
            continue
        actions = data.get("acoes") if isinstance(data, dict) else None
        if isinstance(actions, list):
            return [a for a in actions if isinstance(a, dict) and a.get("ticker")]
    return []


def _weekly_steps(
    rows: list[dict[str, Any]], macro_ctx: dict[str, Any], today: date
) -> list[tuple[str, str]]:
    analysis = (
        "[REVISÃO SEMANAL DO COMITÊ — leia ./MEMORY.md antes e atualize ao final]\n"
        f"Data: {today.isoformat()}\n"
        f"{_MANDATE}\n\n"
        f"Snapshot macro capturado:\n{_macro_block(macro_ctx)}\n\n"
        f"Carteira atual (cada linha é um LOTE com sua própria maturidade):\n"
        f"{_positions_block(rows)}\n\n"
        "Como uma MESA COMPLETA nível Goldman Sachs / J.P. Morgan (economista-chefe, "
        "estrategista de alocação, equity research B3, crypto on-chain, head de RF, "
        "quant, CRO, forensic, CIO), com carta branca de pesquisa (WebSearch/WebFetch "
        "+ seus MCPs: yahoo-finance p/ B3 `.SA`, coingecko, defillama, exa, "
        "sequential-thinking, playwright, fetch — e glassnode/coinglass/messari se "
        "disponíveis), produza uma REVISÃO SEMANAL COMPLETA e profissional, com "
        "debate e decisão do CIO. Cada posição traz a TESE registrada na compra e "
        "os níveis de alvo/stop — reavalie a tese explicitamente (tese intacta / "
        "enfraquecida / quebrada):\n"
        "1. Macro completo (Brasil + global) e o que mudou na semana — com dados ao vivo.\n"
        "2. Desempenho de CADA posição: busque o preço atual real, calcule P&L, e diga "
        "se a tese segue válida.\n"
        "3. Para cada LOTE já LIBERADO (a coluna status diz quais): recomendação "
        "MANTER / VENDER / AUMENTAR com racional e gatilhos. Para lotes travados: "
        "status e plano.\n"
        "4. Riscos, alertas e oportunidades novas dentro do mandato (CDB / ações B3 / crypto).\n"
        "5. ROTAÇÃO DE DRY POWDER: o CDB tem LIQUIDEZ DIÁRIA (sem trava). Se houver uma "
        "OPORTUNIDADE de mercado RELEVANTE esta semana (ação B3 ou crypto) — entrada "
        "claramente assimétrica —, recomende VENDER parte/todo o CDB e COMPRAR o ativo, "
        "com R$, preço-alvo, tamanho e racional. Só recomende a rotação se a convicção "
        "for alta; senão, mantenha o CDB rendendo. Lembre que a NOVA compra entra em "
        f"trava de {settings.min_holding_days} dias se for ação e "
        f"{settings.min_holding_days_crypto} dias se for crypto.\n"
        "Seja rigoroso, cite números e fontes. NÃO cite corretora/exchange."
    )
    synthesis = (
        "Agora escreva o RELATÓRIO SEMANAL EXECUTIVO para o cliente, em português, "
        f"enxuto e acionável (ele lê no app, no celular). {_REPORT_FORMAT} Inclua:\n"
        "• Macro em 3-5 linhas (o que importa agora).\n"
        "• Desempenho da carteira (resumo + destaques positivos/negativos).\n"
        "• Ações sobre lotes liberados: tabela curta Ticker | Ação (manter/vender/aumentar) | "
        "motivo em 1 linha.\n"
        "• ROTAÇÃO: se houver oportunidade, ordem clara 'VENDER R$ X de CDB → COMPRAR <ativo>' "
        "com preço-alvo; se não houver, diga 'manter CDB, sem rotação esta semana'.\n"
        "• Alertas e o que observar na próxima semana.\n"
        f"{_ACTIONS_BLOCK}\n"
        "ANTES de escrever, ATUALIZE ./MEMORY.md com o que mudou. Depois entregue o relatório."
    )
    return [("Revisão semanal — análise", analysis), ("Revisão semanal — relatório", synthesis)]


# The review used to be two chained steps: analysis, then the client report.
# The second one only reformatted, yet it was a NEW process resuming the
# session, and the CLI rebuilds large tool results differently on resume: the
# whole conversation after the first big search result was re-written to the
# cache (149k tokens, US$ 1.61 of a US$ 4.08 review on 2026-10-19). One step
# that ends with both documents keeps the cache and drops that cost.
_REPORT_MARKER = "=== RELATÓRIO DO CLIENTE ==="


def _single_step(steps: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Fold [analysis, report] prompts into one step that returns both."""
    (title, analysis), (_, report) = steps
    merged = (
        f"{analysis}\n\n---\nENTREGA, numa resposta só (a sua ÚLTIMA mensagem): primeiro o "
        f"memo completo da análise; depois uma linha exatamente `{_REPORT_MARKER}`; depois "
        f"o texto para o cliente, assim:\n{report}"
    )
    return [(title, merged)]


def _split_report(final: str) -> tuple[str, str]:
    """(analysis memo, client report). Without the marker, both are the text."""
    if _REPORT_MARKER not in (final or ""):
        return final, final
    memo, report = final.split(_REPORT_MARKER, 1)
    return memo.strip(), report.strip()


def _maturity_steps(
    matured: list[dict[str, Any]], macro_ctx: dict[str, Any], today: date
) -> list[tuple[str, str]]:
    block = _positions_block(matured)
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
        "Escreva o aviso EXECUTIVO de maturidade para o app (lido no celular), em "
        f"português, curto. {_REPORT_FORMAT} "
        "para cada lote liberado, Ticker | Ação (manter/vender/aumentar) | motivo (1 linha) "
        f"| alvo. {_ACTIONS_BLOCK} Atualize ./MEMORY.md antes de responder."
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
    # The single step returns memo + client report; keep the two-document
    # shape (steps[0] = analysis) that the contribution's consult block reads.
    memo, client = _split_report(summary.final_summary)
    summary.final_summary = client
    step_cost = summary.steps[0].cost_usd if summary.steps else 0.0
    step_duration = summary.steps[0].duration_s if summary.steps else 0.0
    report = Report(
        kind=kind,
        title=title,
        content=order_service.strip_machine_block(summary.final_summary),
        actions=parse_actions_block(summary.final_summary),
        cost_usd=summary.total_cost_usd,
        session_id=summary.session_id,
        macro_snapshot=macro_ctx,
        portfolio_snapshot={"assets": portfolio_rows},
        steps=[
            {
                "title": f"{title} — análise",
                "response": memo,
                "cost_usd": step_cost,
                "duration_s": step_duration,
            },
            {
                "title": f"{title} — relatório",
                "response": client,
                "cost_usd": 0.0,
                "duration_s": 0.0,
            },
        ],
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
    fail_fast_on_limit: bool = False,
) -> Report | None:
    if not has_reviewable_data(session):
        # Empty book: never start the opus chain. Callers control whether the
        # short note reaches the client via ``notify`` (the daily timer throttles
        # it on its side).
        logger.info("weekly_review_skipped_empty")
        if notify:
            notification_center.notify(
                "📭 Carteira e ledger vazios: revisão semanal pulada. "
                "Registre uma compra ou um gasto e eu volto a revisar toda semana.",
                kind=NotificationKind.REVIEW,
            )
        return None
    today = date.today()
    rows = portfolio_service.build_portfolio_snapshot(session)
    # Lots that unlocked and were never reviewed: the weekly reads every
    # position anyway, so it ABSORBS them instead of paying for a second
    # committee run. Marked only after the review succeeds (below).
    _, maturity_keys = notification_service.pending_maturities(session)
    steps = _single_step(_weekly_steps(rows, macro_ctx, today))
    summary = analysis_runner.run_chain(
        steps,
        run_id=str(uuid4()),
        model=model,
        effort=effort,
        on_event=on_event,
        # Night timers: one short retry, never hours of in-process waiting
        # that would carry the committee past 03:00 (D50/D53).
        limit_backoff=[120] if fail_fast_on_limit else None,
    )
    report = _persist_report(
        session,
        kind=ReportKind.WEEKLY,
        title=f"Revisão semanal · {today.isoformat()}",
        summary=summary,
        macro_ctx=macro_ctx,
        portfolio_rows=rows,
    )
    if maturity_keys:
        notification_service.mark_maturities(maturity_keys)
        logger.info("weekly_review_absorbed_maturities", lots=len(maturity_keys))
    if notify:
        notification_center.notify(
            f"🗓️ Revisão semanal do comitê ({today.isoformat()})\n\n{report.content}",
            kind=NotificationKind.REVIEW,
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
    fail_fast_on_limit: bool = False,
) -> Report | None:
    if not matured_rows:
        return None
    today = date.today()
    steps = _single_step(_maturity_steps(matured_rows, macro_ctx, today))
    summary = analysis_runner.run_chain(
        steps,
        run_id=str(uuid4()),
        model=model,
        effort=effort,
        on_event=on_event,
        # Night timers: one short retry, never hours of in-process waiting
        # that would carry the committee past 03:00 (D50/D53).
        limit_backoff=[120] if fail_fast_on_limit else None,
    )
    report = _persist_report(
        session,
        kind=ReportKind.MATURITY,
        title=f"Maturidade · {today.isoformat()}",
        summary=summary,
        macro_ctx=macro_ctx,
        portfolio_rows=matured_rows,
    )
    if notify:
        notification_center.notify(
            f"🔓 Lotes liberados para venda · análise do comitê ({today.isoformat()})"
            f"\n\n{report.content}",
            kind=NotificationKind.REVIEW,
        )
    logger.info("maturity_review_done", report_id=str(report.id), assets=len(matured_rows))
    return report
