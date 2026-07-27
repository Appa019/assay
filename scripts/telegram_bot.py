#!/usr/bin/env python3
"""Private Telegram bot — your only interface to the investment agent.

Locked to a single chat (``TELEGRAM_CHAT_ID``); it ignores everyone else.
Long-polls Telegram and speaks Portuguese only.

Commands:
    /aporte <valor>                 cria o aporte e roda o comitê inteiro
    /comprei <ticker> <classe> <qtd> <preço>   registra uma compra
    /vender <ticker>                vende (ações/crypto após 30 dias; CDB quando quiser)
    /carteira                       lista posições + elegibilidade de venda
    /status                         alocação atual vs. alvo + cadência
    /ajuda                          esta ajuda

    python scripts/telegram_bot.py
"""

import asyncio
import atexit
import json
import os
import sys
import threading
import time
from datetime import UTC, date, datetime
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
from app.models.report import Report, ReportKind  # noqa: E402
from app.schemas.asset import AssetCreate  # noqa: E402
from app.services import (  # noqa: E402
    analysis_runner,
    contribution_service,
    portfolio_service,
    price_refresh_service,
    review_service,
    telegram_service,
)

# NOTE: no "fii" alias — FIIs are outside the mandate (B3 equities only).
_CLASS_ALIASES: dict[str, AssetClass] = {
    "rf": AssetClass.FIXED_INCOME,
    "renda_fixa": AssetClass.FIXED_INCOME,
    "rendafixa": AssetClass.FIXED_INCOME,
    "fixed_income": AssetClass.FIXED_INCOME,
    "cdb": AssetClass.FIXED_INCOME,
    "acao": AssetClass.STOCKS,
    "acoes": AssetClass.STOCKS,
    "ação": AssetClass.STOCKS,
    "ações": AssetClass.STOCKS,
    "stocks": AssetClass.STOCKS,
    "crypto": AssetClass.CRYPTO,
    "cripto": AssetClass.CRYPTO,
}

_PID_PATH = _PROJECT_ROOT / "storage" / "telegram_bot.pid"

# Pending /vender confirmation: ticker → asked-at (expires after 2 minutes).
_pending_sell: dict[str, float] = {}
_SELL_CONFIRM_TTL_S = 120

_HELP = (
    "🤖 *Agente de Investimentos*\n\n"
    "/aporte <valor> — crio o aporte e rodo o comitê inteiro (Opus · max). "
    "Te devolvo onde investir e quanto.\n"
    "/comprei <ticker> <classe> <qtd> <preço> — registro o que você comprou. "
    "Classe: rf, acoes ou crypto.\n"
    "/vender <ticker> — vendo (ações/crypto após 30 dias por lote; CDB quando "
    "quiser). Peço confirmação antes de executar.\n"
    "/carteira — suas posições e o que já pode ser vendido.\n"
    "/atualizar — atualizo os preços de mercado de todas as posições.\n"
    "/revisao — rodo agora a revisão semanal do comitê (macro + carteira).\n"
    "/relatorios — últimos relatórios (semanais e de maturidade).\n"
    "/status — carteira, análises em andamento e saúde do sistema.\n"
    "/ajuda — esta mensagem."
)

_BOT_COMMANDS = [
    {"command": "aporte", "description": "Criar aporte e rodar o comitê"},
    {"command": "comprei", "description": "Registrar uma compra executada"},
    {"command": "vender", "description": "Vender uma posição (com confirmação)"},
    {"command": "carteira", "description": "Posições e travas por lote"},
    {"command": "atualizar", "description": "Atualizar preços de mercado"},
    {"command": "revisao", "description": "Rodar a revisão semanal agora"},
    {"command": "relatorios", "description": "Últimos relatórios do comitê"},
    {"command": "status", "description": "Carteira + saúde do sistema"},
    {"command": "ajuda", "description": "Ajuda"},
]


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


def _local_date(dt: datetime) -> date:
    """Naive-UTC datetime → local calendar date (avoids off-by-one at night)."""
    aware = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return aware.astimezone().date()


def _running_analyses() -> list[str]:
    """Contribution ids whose run lock is held by a live process right now."""
    lock_dir = _PROJECT_ROOT / "storage" / "analysis_runs"
    running: list[str] = []
    for lock in lock_dir.glob("*.lock"):
        if lock.name.startswith("_"):
            continue  # global lock
        if analysis_runner._lock_is_active(lock):
            running.append(lock.stem[:8])
    return running


def _cmd_status() -> str:
    with Session(engine) as s:
        summ = portfolio_service.get_portfolio_summary(s)
        last = s.exec(
            select(Contribution).order_by(Contribution.created_at.desc()).limit(1)
        ).first()
        last_weekly = s.exec(
            select(Report)
            .where(Report.kind == ReportKind.WEEKLY)
            .order_by(Report.created_at.desc())
            .limit(1)
        ).first()
        stuck = analysis_runner.pending_resumable_ids(s)
    a = summ.allocation
    t = summ.target_allocation
    lines = [
        f"📊 *Carteira:* {_fmt_brl(summ.total_value)}",
        "",
        f"Renda Fixa (CDB): {a.fixed_income_pct:.1f}% (alvo {t['fixed_income']:.0f}%)",
        f"Ações B3: {a.stocks_pct:.1f}% (alvo {t['stocks']:.0f}%)",
        f"Crypto: {a.crypto_pct:.1f}% (alvo {t['crypto']:.0f}%)",
        "",
    ]
    if last is not None:
        days = (date.today() - _local_date(last.created_at)).days
        lines.append(f"Último aporte há {days} dia(s). Faça outro quando quiser (/aporte).")
    else:
        lines.append("Nenhum aporte ainda. Mande /aporte <valor> quando quiser começar.")
    if last_weekly is not None:
        weekly_days = (date.today() - _local_date(last_weekly.created_at)).days
        lines.append(f"Última revisão semanal há {weekly_days} dia(s).")
    running = _running_analyses()
    if running:
        lines.append(f"⏳ Análise em andamento: {', '.join(running)}")
    if stuck:
        lines.append(f"♻️ Aguardando retomada automática: {len(stuck)} análise(s).")
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
        if a.asset_class == AssetClass.FIXED_INCOME:
            lock = "🔓 liquidez diária"  # CDB has no lock
        elif days >= min_days:
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
    if asset_class == AssetClass.FIXED_INCOME:
        liquidez = "Liquidez diária — pode vender quando quiser."
    else:
        liquidez = f"Liberado para venda em {settings.min_holding_days} dias (trava por lote)."
    return (
        f"✅ Registrado: {asset.ticker} ({asset.asset_class}) — "
        f"{float(asset.quantity)} @ {_fmt_brl(float(asset.avg_price))}.\n{liquidez}"
    )


def _cmd_vender(args: list[str]) -> str:
    if not args:
        return "Uso: /vender <ticker>  (depois confirme com /vender <ticker> confirmar)"
    ticker = args[0].strip().upper()
    confirming = len(args) > 1 and args[1].lower() in {"confirmar", "sim", "confirma"}
    today = date.today()
    min_days = settings.min_holding_days
    with Session(engine) as s:
        # Lots = one row per purchase. Sell the OLDEST lot that has matured.
        lots = list(
            s.exec(select(Asset).where(Asset.ticker == ticker).order_by(Asset.entry_date)).all()
        )
        if not lots:
            return f"Não achei {ticker} na carteira."
        # CDB / fixed income = daily liquidity (no lock). Stocks/crypto: 30d per lot.
        sellable = [
            a
            for a in lots
            if a.asset_class == AssetClass.FIXED_INCOME or (today - a.entry_date).days >= min_days
        ]
        if not sellable:
            soonest = min(min_days - (today - a.entry_date).days for a in lots)
            return (
                f"🔒 {ticker} ainda travado — o lote mais próximo libera em {soonest} dia(s) "
                f"(trava de {min_days}d vale só p/ ações e crypto)."
            )
        target = sellable[0]
        days = (today - target.entry_date).days
        price = target.current_price if target.current_price is not None else target.avg_price
        value = float(target.quantity * price)

        # Two-step confirmation: selling is irreversible — never on a typo.
        asked_at = _pending_sell.get(ticker)
        ask_valid = asked_at is not None and (time.monotonic() - asked_at) <= _SELL_CONFIRM_TTL_S
        if not confirming:
            _pending_sell[ticker] = time.monotonic()
            return (
                f"⚠️ Confirma a venda do lote mais antigo de {ticker}?\n"
                f"Lote de {target.entry_date.isoformat()} ({days}d) — "
                f"{float(target.quantity)} @ {_fmt_brl(float(price))} ≈ {_fmt_brl(value)}.\n"
                f"Para executar, envie: /vender {ticker} confirmar (vale por 2 min)"
            )
        if not ask_valid:
            _pending_sell.pop(ticker, None)
            return (
                f"Pedido de confirmação expirado. Envie /vender {ticker} de novo "
                "para rever os números."
            )
        _pending_sell.pop(ticker, None)
        try:
            result = portfolio_service.sell_asset(s, target.id)
        except portfolio_service.SellLockedError as exc:
            return f"🔒 {exc}"
    remaining = len(lots) - 1
    extra = f" Restam {remaining} lote(s) de {ticker}." if remaining else ""
    return f"✅ {result.message} (lote de {target.entry_date.isoformat()}, {days}d).{extra}"


def _cmd_atualizar() -> str:
    with Session(engine) as s:
        result = asyncio.run(price_refresh_service.refresh_prices(s))
    lines = [f"💹 Preços atualizados: {result['updated']} posição(ões)."]
    for warning in result["warnings"]:
        lines.append(f"⚠️ {warning}")
    return "\n".join(lines)


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
    if cmd == "atualizar":
        return _cmd_atualizar()
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


def _acquire_single_instance() -> bool:
    """Refuse to start when another live bot process exists.

    Two pollers fighting over getUpdates produce endless Telegram 409s and
    randomly-split replies (observed: thousands of 409s in the logs).
    """
    if _PID_PATH.exists():
        try:
            other = int(json.loads(_PID_PATH.read_text(encoding="utf-8"))["pid"])
            os.kill(other, 0)  # raises if the process is gone
            return other == os.getpid()
        except (ValueError, KeyError, json.JSONDecodeError, ProcessLookupError):
            pass  # stale — reclaim below
        except PermissionError:
            return False
    _PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PID_PATH.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    atexit.register(_PID_PATH.unlink, missing_ok=True)
    return True


def _drain_backlog() -> int | None:
    """Consume EVERY queued update on startup (not just the first page)."""
    offset: int | None = None
    while True:
        backlog = telegram_service.get_updates(offset=offset, timeout=0)
        if not backlog:
            return offset
        offset = backlog[-1]["update_id"] + 1


def main() -> int:
    if not settings.telegram_enabled:
        print("Telegram não configurado. Rode scripts/telegram_setup.py primeiro.")
        return 2
    if not _acquire_single_instance():
        print("Outra instância do bot já está rodando — saindo.")
        return 3
    init_db()
    me = telegram_service.get_me()
    telegram_service.set_my_commands(_BOT_COMMANDS)
    print(f"Bot @{me.get('username')} ativo. Travado no chat {settings.telegram_chat_id}.")

    # Skip any backlog so old commands aren't replayed on startup.
    offset = _drain_backlog()

    consecutive_errors = 0
    while True:
        try:
            updates = telegram_service.get_updates(offset=offset, timeout=50)
            consecutive_errors = 0
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 — the loop must survive ANY error
            # Not just TelegramError: DNS failures, timeouts and JSON decode
            # errors used to kill the process with nothing restarting it.
            consecutive_errors += 1
            wait = min(60, 3 * consecutive_errors)
            print(f"poll error ({consecutive_errors}x): {exc} — retry em {wait}s")
            time.sleep(wait)
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
