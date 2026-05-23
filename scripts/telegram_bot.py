#!/usr/bin/env python3
"""Private Telegram bot — your only interface to the investment agent.

Locked to a single chat (``TELEGRAM_CHAT_ID``); it ignores everyone else.
Long-polls Telegram and speaks Portuguese only.

Commands:
    /aporte <valor>                 cria o aporte e roda o comitê inteiro
    /comprei <ticker> <classe> <qtd> <preço>   registra uma compra
    /vender <ticker>                vende (respeita a trava de 30 dias)
    /carteira                       lista posições + elegibilidade de venda
    /status                         alocação atual vs. alvo + cadência
    /ajuda                          esta ajuda

    python scripts/telegram_bot.py
"""

import asyncio
import sys
import threading
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlmodel import Session, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.core.database import engine, init_db  # noqa: E402
from app.models.asset import Asset, AssetClass  # noqa: E402
from app.models.contribution import Contribution  # noqa: E402
from app.models.report import Report  # noqa: E402
from app.schemas.asset import AssetCreate  # noqa: E402
from app.services import (  # noqa: E402
    analysis_runner,
    contribution_service,
    portfolio_service,
    review_service,
    telegram_service,
)

_CLASS_ALIASES: dict[str, AssetClass] = {
    "rf": AssetClass.FIXED_INCOME,
    "renda_fixa": AssetClass.FIXED_INCOME,
    "rendafixa": AssetClass.FIXED_INCOME,
    "fixed_income": AssetClass.FIXED_INCOME,
    "acao": AssetClass.STOCKS,
    "acoes": AssetClass.STOCKS,
    "ação": AssetClass.STOCKS,
    "ações": AssetClass.STOCKS,
    "fii": AssetClass.STOCKS,
    "stocks": AssetClass.STOCKS,
    "crypto": AssetClass.CRYPTO,
    "cripto": AssetClass.CRYPTO,
}

_HELP = (
    "🤖 *Agente de Investimentos*\n\n"
    "/aporte <valor> — crio o aporte e rodo o comitê inteiro (Opus · max). "
    "Te devolvo onde investir e quanto.\n"
    "/comprei <ticker> <classe> <qtd> <preço> — registro o que você comprou. "
    "Classe: rf, acoes ou crypto.\n"
    "/vender <ticker> — vendo (só após 30 dias de posse, por lote).\n"
    "/carteira — suas posições e o que já pode ser vendido.\n"
    "/revisao — rodo agora a revisão semanal do comitê (macro + carteira).\n"
    "/relatorios — últimos relatórios (semanais e de maturidade).\n"
    "/status — alocação atual vs. alvo + quando é o próximo aporte.\n"
    "/ajuda — esta mensagem."
)


def _fmt_brl(value: float) -> str:
    integer, decimals = f"{value:,.2f}".split(".")
    return f"R$ {integer.replace(',', '.')},{decimals}"


def _parse_amount(raw: str) -> Decimal:
    s = raw.strip().replace("R$", "").replace(" ", "")
    if "," in s and "." in s:  # pt-BR: 5.000,50
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:  # 5000,50
        s = s.replace(",", ".")
    return Decimal(s)


def _send(text: str) -> None:
    telegram_service.send_message(text, chat_id=settings.telegram_chat_id)


# --- command handlers -------------------------------------------------------


def _cmd_status() -> str:
    with Session(engine) as s:
        summ = portfolio_service.get_portfolio_summary(s)
        last = s.exec(
            select(Contribution).order_by(Contribution.created_at.desc()).limit(1)
        ).first()
    a = summ.allocation
    t = summ.target_allocation
    lines = [
        f"📊 *Carteira:* {_fmt_brl(summ.total_value)}",
        "",
        f"Renda Fixa (CDB): {a.fixed_income_pct:.1f}% (alvo {t['fixed_income']:.0f}%)",
        f"Ações B3: {a.stocks_pct:.1f}% (alvo {t['stocks']:.0f}%)",
        f"Crypto: {a.crypto_pct:.1f}% (alvo {t['crypto']:.0f}%)",
    ]
    if last is not None:
        days = (date.today() - last.created_at.date()).days
        restante = settings.contribution_interval_days - days
        lines.append("")
        lines.append(
            f"Último aporte há {days} dias."
            + (f" Próximo em {restante} dias." if restante > 0 else " Aporte já está na hora! 📅")
        )
    else:
        lines.append("")
        lines.append("Nenhum aporte ainda. Mande /aporte <valor> para começar.")
    return "\n".join(lines)


def _cmd_carteira() -> str:
    today = date.today()
    min_days = settings.min_holding_days
    with Session(engine) as s:
        assets = portfolio_service.list_assets(s)
    if not assets:
        return "Carteira vazia. Use /comprei depois de investir."
    lines = ["📁 *Posições:*", ""]
    for a in assets:
        days = (today - a.entry_date).days
        price = a.current_price if a.current_price is not None else a.avg_price
        value = float(a.quantity * price)
        if days >= min_days:
            lock = "🔓 liberado"
        else:
            lock = f"🔒 faltam {min_days - days}d"
        lines.append(f"• {a.ticker} ({a.asset_class}) — {_fmt_brl(value)} — {days}d — {lock}")
    return "\n".join(lines)


def _cmd_comprei(args: list[str]) -> str:
    if len(args) < 4:
        return "Uso: /comprei <ticker> <classe> <qtd> <preço>\nEx: /comprei PETR4 acoes 100 38,50"
    ticker, classe_raw, qtd_raw, preco_raw = args[0], args[1], args[2], args[3]
    asset_class = _CLASS_ALIASES.get(classe_raw.lower())
    if asset_class is None:
        return "Classe inválida. Use: rf, acoes ou crypto."
    try:
        qty = Decimal(qtd_raw.replace(",", "."))
        price = _parse_amount(preco_raw)
    except (InvalidOperation, ValueError):
        return "Quantidade ou preço inválidos."
    with Session(engine) as s:
        asset = portfolio_service.create_asset(
            s,
            AssetCreate(
                ticker=ticker,
                asset_class=asset_class,
                quantity=qty,
                avg_price=price,
                entry_date=date.today(),
            ),
        )
    return (
        f"✅ Registrado: {asset.ticker} ({asset.asset_class}) — "
        f"{float(asset.quantity)} @ {_fmt_brl(float(asset.avg_price))}.\n"
        f"Liberado para venda em {settings.min_holding_days} dias."
    )


def _cmd_vender(args: list[str]) -> str:
    if not args:
        return "Uso: /vender <ticker>"
    ticker = args[0].strip().upper()
    today = date.today()
    min_days = settings.min_holding_days
    with Session(engine) as s:
        # Lots = one row per purchase. Sell the OLDEST lot that has matured.
        lots = list(
            s.exec(select(Asset).where(Asset.ticker == ticker).order_by(Asset.entry_date)).all()
        )
        if not lots:
            return f"Não achei {ticker} na carteira."
        matured = [a for a in lots if (today - a.entry_date).days >= min_days]
        if not matured:
            soonest = min(min_days - (today - a.entry_date).days for a in lots)
            return (
                f"🔒 {ticker} ainda travado — o lote mais próximo libera em {soonest} dia(s) "
                f"(trava de {min_days}d, por lote)."
            )
        target = matured[0]
        days = (today - target.entry_date).days
        result = portfolio_service.sell_asset(s, target.id)
    remaining = len(lots) - 1
    extra = f" Restam {remaining} lote(s) de {ticker}." if remaining else ""
    return f"✅ {result.message} (lote de {target.entry_date.isoformat()}, {days}d).{extra}"


def _run_aporte_async(amount: Decimal) -> None:
    """Heavy: create the contribution and run the full committee (minutes)."""
    try:
        with Session(engine) as s:
            contribution, _ = asyncio.run(
                contribution_service.create_contribution_with_prompts(s, amount_brl=amount)
            )
            # run_analysis pushes the final recommendation to Telegram itself.
            analysis_runner.run_analysis(s, contribution.id)
    except Exception as exc:  # noqa: BLE001 — report any failure back to the user
        _send(f"✖ A análise falhou: {exc}")


def _cmd_aporte(args: list[str]) -> str:
    if not args:
        return "Uso: /aporte <valor>\nEx: /aporte 5000"
    try:
        amount = _parse_amount(args[0])
    except (InvalidOperation, ValueError):
        return f"Valor inválido: {args[0]}"
    if amount <= 0:
        return "O aporte deve ser maior que zero."
    threading.Thread(target=_run_aporte_async, args=(amount,), daemon=True).start()
    return (
        f"🔄 Rodando o comitê inteiro para um aporte de {_fmt_brl(float(amount))} "
        "(Opus · max · carta branca). Pode levar dezenas de minutos — te aviso aqui "
        "quando a folha de ordens ficar pronta."
    )


def _run_weekly_async() -> None:
    """Heavy: run the weekly committee review (it pushes the report to Telegram)."""
    try:
        with Session(engine) as s:
            macro = asyncio.run(review_service.fetch_macro())
            review_service.run_weekly_review(s, macro_ctx=macro)
    except Exception as exc:  # noqa: BLE001
        _send(f"✖ A revisão semanal falhou: {exc}")


def _cmd_revisao() -> str:
    threading.Thread(target=_run_weekly_async, daemon=True).start()
    return (
        "🗓️ Rodando a revisão semanal do comitê (macro + desempenho + maturidade). "
        "Pode levar minutos — te mando o relatório aqui quando ficar pronto."
    )


def _cmd_relatorios() -> str:
    with Session(engine) as s:
        reports = list(s.exec(select(Report).order_by(Report.created_at.desc()).limit(8)).all())
    if not reports:
        return "Nenhum relatório ainda. Use /revisao para gerar o primeiro."
    lines = ["📄 *Últimos relatórios:*", ""]
    for r in reports:
        lines.append(f"• {r.created_at.date().isoformat()} — {r.kind} — {r.title}")
    lines.append("\n(os relatórios também ficam salvos e entram como consulta nos aportes)")
    return "\n".join(lines)


def _handle(text: str) -> str | None:
    parts = text.strip().split()
    if not parts:
        return None
    cmd = parts[0].lower().lstrip("/")
    cmd = cmd.split("@")[0]  # strip @botname in group-style mentions
    args = parts[1:]
    if cmd in {"start", "ajuda", "help"}:
        return _HELP
    if cmd == "status":
        return _cmd_status()
    if cmd == "carteira":
        return _cmd_carteira()
    if cmd in {"revisao", "revisão"}:
        return _cmd_revisao()
    if cmd in {"relatorios", "relatórios"}:
        return _cmd_relatorios()
    if cmd == "comprei":
        return _cmd_comprei(args)
    if cmd == "vender":
        return _cmd_vender(args)
    if cmd == "aporte":
        return _cmd_aporte(args)
    return "Não entendi. Mande /ajuda para ver os comandos."


def main() -> int:
    if not settings.telegram_enabled:
        print("Telegram não configurado. Rode scripts/telegram_setup.py primeiro.")
        return 2
    init_db()
    me = telegram_service.get_me()
    print(f"Bot @{me.get('username')} ativo. Travado no chat {settings.telegram_chat_id}.")

    # Skip any backlog so old commands aren't replayed on startup.
    backlog = telegram_service.get_updates(timeout=0)
    offset = (backlog[-1]["update_id"] + 1) if backlog else None

    while True:
        try:
            updates = telegram_service.get_updates(offset=offset, timeout=50)
        except telegram_service.TelegramError as exc:
            print(f"poll error: {exc}")
            time.sleep(3)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue
            chat_id = str((msg.get("chat") or {}).get("id"))
            if chat_id != str(settings.telegram_chat_id):
                # Locked: only the owner can talk to this bot. Ignore (no reply)
                # and log the attempt for auditability.
                print(f"ignored message from unauthorized chat {chat_id}")
                continue
            text = msg.get("text") or ""
            try:
                reply = _handle(text)
            except Exception as exc:  # noqa: BLE001
                reply = f"Erro: {exc}"
            if reply:
                _send(reply)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nBot encerrado.")
