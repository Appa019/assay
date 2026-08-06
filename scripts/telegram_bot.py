#!/usr/bin/env python3
"""Private Telegram bot — your only interface to the investment agent.

Locked to a single chat (``TELEGRAM_CHAT_ID``); it ignores everyone else.
Long-polls Telegram and speaks Portuguese only.

Any NON-command text is a live conversation with the financial consultant
(a chained Claude session with its own fixed memory — see chat_service).
Photos and documents (≤20 MB) are downloaded into the consultant's inbox and
read by it (vision for images, parsing for PDF/CSV) — a receipt photo becomes
a registered expense.

Commands:
    /aporte <valor>                 cria o aporte e roda o comitê inteiro
    /comprei <ticker> <classe> <qtd> <preço>   registra uma compra
    /vender <ticker>                vende (ações/crypto após 30 dias; CDB quando quiser)
    /gasto <valor> [descrição #categoria]      registra um gasto no ledger
    /ganho <valor> [descrição #categoria]      registra um ganho no ledger
    /financas [YYYY-MM]             resumo do mês (gastos × ganhos × saldo)
    /carteira                       lista posições + elegibilidade de venda
    /status                         alocação atual vs. alvo + cadência
    /ajuda                          esta ajuda

    python scripts/telegram_bot.py
"""

import asyncio
import atexit
import queue
import re
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
from app.models.cashflow import CashflowKind, CashflowSource  # noqa: E402
from app.models.chat import ChatChannel  # noqa: E402
from app.models.contribution import Contribution  # noqa: E402
from app.models.order import OrderStatus  # noqa: E402
from app.models.report import Report, ReportKind  # noqa: E402
from app.schemas.asset import AssetCreate  # noqa: E402
from app.schemas.cashflow import CashflowCreate  # noqa: E402
from app.services import (  # noqa: E402
    analysis_runner,
    cashflow_service,
    chat_service,
    contribution_service,
    order_service,
    portfolio_service,
    price_refresh_service,
    review_service,
    tax_service,
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
    "💬 *Me mande qualquer mensagem sem /* e eu respondo como seu consultor "
    "financeiro em tempo real: dúvidas de tickers, cripto, CDB, carteira, IR — "
    'e registro gastos e ganhos que você me contar ("gastei 80 no mercado"). '
    "Eu lembro das conversas (memória fixa).\n"
    "📎 Pode mandar *foto* (cupom, nota, print) ou *arquivo* (PDF, CSV, "
    "planilha, até 20 MB): eu leio, analiso e registro o que for gasto/ganho.\n\n"
    "/gasto <valor> [descrição #categoria] — registro rápido de um gasto.\n"
    "/ganho <valor> [descrição #categoria] — registro rápido de um ganho.\n"
    "/financas [AAAA-MM] — resumo do mês: gastos × ganhos × saldo por categoria.\n"
    "/resetchat — começo uma conversa nova (a memória fixa permanece).\n\n"
    "/aporte <valor> — crio o aporte e rodo o comitê inteiro (Opus · max). "
    "Te devolvo onde investir e quanto.\n"
    "/ordens — folha de ordens pendente do último aporte.\n"
    "/executei <ticker> <qtd> <preço> — confirmo a execução de uma ordem "
    "(o lote herda tese, alvo e stop do comitê).\n"
    "/comprei <ticker> <classe> <qtd> <preço> — registro uma compra avulsa. "
    "Classe: rf, acoes ou crypto.\n"
    "/vender <ticker> — vendo (ações/crypto após 30 dias por lote; CDB quando "
    "quiser). Peço confirmação antes de executar.\n"
    "/carteira — suas posições e o que já pode ser vendido.\n"
    "/atualizar — atualizo os preços de mercado de todas as posições.\n"
    "/revisao — rodo agora a revisão semanal do comitê (macro + carteira).\n"
    "/relatorios — últimos relatórios (semanais e de maturidade).\n"
    "/ir [ano] — apuração simplificada de IR (DARF por mês).\n"
    "/status — carteira, análises em andamento e saúde do sistema.\n"
    "/ajuda — esta mensagem."
)

_BOT_COMMANDS = [
    {"command": "gasto", "description": "Registrar um gasto (valor + descrição)"},
    {"command": "ganho", "description": "Registrar um ganho (valor + descrição)"},
    {"command": "financas", "description": "Resumo do mês: gastos × ganhos"},
    {"command": "resetchat", "description": "Recomeçar a conversa do consultor"},
    {"command": "aporte", "description": "Criar aporte e rodar o comitê"},
    {"command": "ordens", "description": "Folha de ordens pendente"},
    {"command": "executei", "description": "Confirmar execução de uma ordem"},
    {"command": "comprei", "description": "Registrar uma compra avulsa"},
    {"command": "vender", "description": "Vender uma posição (com confirmação)"},
    {"command": "carteira", "description": "Posições e travas por lote"},
    {"command": "atualizar", "description": "Atualizar preços de mercado"},
    {"command": "revisao", "description": "Rodar a revisão semanal agora"},
    {"command": "relatorios", "description": "Últimos relatórios do comitê"},
    {"command": "ir", "description": "Apuração simplificada de IR"},
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


# --- consultant chat (free text → chained Claude session) -------------------

# (prompt sent to the consultant, human-readable line for the shared transcript)
_chat_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()


def _typing_loop(stop: threading.Event) -> None:
    """Keep the "typing…" indicator alive while a turn runs (it expires in ~5s)."""
    while not stop.is_set():
        telegram_service.send_chat_action("typing")
        stop.wait(5)


def _chat_worker() -> None:
    """Serial consumer: one consultant turn at a time, in message order."""
    while True:
        text, display = _chat_queue.get()
        stop = threading.Event()
        threading.Thread(target=_typing_loop, args=(stop,), daemon=True).start()
        try:
            # converse() persists both sides so the website shows this exchange.
            reply = chat_service.converse(text, ChatChannel.TELEGRAM, display=display)
        except (chat_service.ChatBusyError, chat_service.ChatUnavailableError) as exc:
            reply = str(exc)
        except Exception as exc:  # noqa: BLE001 — the worker must survive anything
            reply = f"✖ Erro inesperado no chat: {exc}"
        finally:
            stop.set()
        _send(reply)
        _chat_queue.task_done()


def _enqueue_chat(text: str, display: str | None = None) -> str | None:
    backlog = _chat_queue.qsize()
    _chat_queue.put((text, display))
    if backlog >= 2:
        return f"📥 Na fila — ainda estou respondendo {backlog} mensagem(ns) antes dessa."
    return None  # the worker replies when the turn finishes


# --- incoming media (photos + documents → consultant inbox) -----------------

_MAX_FILE_BYTES = 20 * 1024 * 1024  # Telegram's download ceiling for bots
_UNSUPPORTED_MEDIA_KEYS = (
    "voice",
    "audio",
    "video",
    "video_note",
    "sticker",
    "animation",
    "location",
    "contact",
)


def _safe_filename(name: str, fallback: str) -> str:
    """Basename with only ASCII word chars, dots and dashes (path-traversal safe)."""
    base = re.sub(r"[^\w.\-]", "_", Path(name or "").name, flags=re.ASCII).strip("._")
    return base[:80] or fallback


def _extract_media(msg: dict) -> tuple[str, str, str, int] | None:
    """(kind, file_id, filename, size) for a photo or document message."""
    doc = msg.get("document")
    if doc:
        name = _safe_filename(doc.get("file_name") or "", "documento.bin")
        return ("arquivo", doc["file_id"], name, int(doc.get("file_size") or 0))
    photos = msg.get("photo") or []
    if photos:
        best = photos[-1]  # Telegram lists sizes ascending; last = largest
        return ("imagem", best["file_id"], "foto.jpg", int(best.get("file_size") or 0))
    return None


def _media_turn_text(kind: str, path: Path, caption: str) -> str:
    return chat_service.media_turn_text(kind, path, caption, "pelo Telegram")


def _unsupported_media(msg: dict) -> str | None:
    """Notice for media kinds the consultant can't read; None for service msgs."""
    if any(key in msg for key in _UNSUPPORTED_MEDIA_KEYS):
        return (
            "🎤 Esse tipo de mídia eu ainda não leio — me manda texto, imagem "
            "(foto/print) ou arquivo (PDF, CSV, planilha)."
        )
    return None


def _handle_media(msg: dict) -> str:
    kind, file_id, name, size = _extract_media(msg)  # caller guarantees media
    if size > _MAX_FILE_BYTES:
        return "📎 Arquivo grande demais — o Telegram só me deixa baixar até 20 MB."
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    inbox = chat_service.CHAT_WORKSPACE / "inbox"
    try:
        path = telegram_service.download_file(file_id, inbox, preferred_name=f"{stamp}_{name}")
    except telegram_service.TelegramError as exc:
        return f"✖ Não consegui baixar o arquivo: {exc}"
    caption = (msg.get("caption") or "").strip()
    display = f"📎 {name}" + (f"\n{caption}" if caption else "")
    queued = _enqueue_chat(_media_turn_text(kind, path, caption), display)
    ack = f"📎 Recebi {'a imagem' if kind == 'imagem' else 'o arquivo'} — analisando…"
    return f"{queued}\n{ack}" if queued else ack


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


def _cmd_ordens() -> str:
    with Session(engine) as s:
        pending = order_service.list_orders(s, status=OrderStatus.PENDING)
    if not pending:
        return "Nenhuma ordem pendente. Rode /aporte para o comitê gerar uma folha nova."
    lines = ["📋 *Ordens pendentes:*", ""]
    for o in pending:
        levels = []
        if o.target_price is not None:
            levels.append(f"alvo {_fmt_brl(float(o.target_price))}")
        if o.stop_price is not None:
            levels.append(f"stop {_fmt_brl(float(o.stop_price))}")
        suffix = f" ({', '.join(levels)})" if levels else ""
        lines.append(f"• {o.ticker} ({o.asset_class}) — {_fmt_brl(float(o.amount_brl))}{suffix}")
        if o.thesis:
            lines.append(f"  _{o.thesis[:120]}_")
    lines.append("")
    lines.append("Executou? Confirme com /executei <ticker> <qtd> <preço>.")
    return "\n".join(lines)


def _cmd_executei(args: list[str]) -> str:
    if len(args) < 3:
        return "Uso: /executei <ticker> <qtd> <preço>\nEx: /executei PETR4 100 38,50"
    ticker = args[0].strip().upper()
    try:
        qty = Decimal(args[1].replace(",", "."))
        price = _parse_amount(args[2])
    except (InvalidOperation, ValueError):
        return "Quantidade ou preço inválidos."
    if qty <= 0 or price <= 0:
        return "Quantidade e preço devem ser maiores que zero."
    with Session(engine) as s:
        order = order_service.pending_order_for_ticker(s, ticker)
        if order is None:
            return (
                f"Não achei ordem pendente de {ticker}. Veja /ordens — "
                "para compra fora da folha, use /comprei."
            )
        order = order_service.execute_order(s, order.id, quantity=qty, price=price)
    total = _fmt_brl(float(qty * price))
    planned = _fmt_brl(float(order.amount_brl))
    return (
        f"✅ Ordem executada: {ticker} — {float(qty)} @ {_fmt_brl(float(price))} = {total} "
        f"(planejado {planned}).\nO lote herdou a tese, o alvo e o stop do comitê; "
        f"trava de {settings.min_holding_days}d se ação/crypto."
    )


def _parse_cashflow(args: list[str]) -> tuple[Decimal, str, str | None]:
    """``<valor> [descrição ... #categoria]`` → (amount, category, description)."""
    amount = _parse_amount(args[0])
    if amount <= 0:
        raise InvalidOperation("valor deve ser positivo")
    category = "outros"
    words: list[str] = []
    for token in args[1:]:
        if token.startswith("#") and len(token) > 1:
            category = token[1:].lower()
        else:
            words.append(token)
    return amount, category, " ".join(words) or None


def _register_cashflow(kind: CashflowKind, args: list[str], usage: str) -> str:
    if not args:
        return usage
    try:
        amount, category, description = _parse_cashflow(args)
    except (InvalidOperation, ValueError):
        return f"Valor inválido: {args[0]}\n{usage}"
    with Session(engine) as s:
        entry = cashflow_service.add_entry(
            s,
            CashflowCreate(
                kind=kind,
                amount_brl=amount,
                category=category,
                description=description,
                source=CashflowSource.BOT,
            ),
        )
        summ = cashflow_service.month_summary(s)
    label = "Gasto" if kind == CashflowKind.EXPENSE else "Ganho"
    desc = f" — {entry.description}" if entry.description else ""
    return (
        f"✅ {label}: {_fmt_brl(float(entry.amount_brl))} ({entry.category}){desc}.\n"
        f"Mês: gastos {_fmt_brl(summ.expense_brl)} · ganhos {_fmt_brl(summ.income_brl)} "
        f"· saldo {_fmt_brl(summ.net_brl)}."
    )


def _cmd_gasto(args: list[str]) -> str:
    return _register_cashflow(
        CashflowKind.EXPENSE, args, "Uso: /gasto <valor> [descrição #categoria]"
    )


def _cmd_ganho(args: list[str]) -> str:
    return _register_cashflow(
        CashflowKind.INCOME, args, "Uso: /ganho <valor> [descrição #categoria]"
    )


def _cmd_financas(args: list[str]) -> str:
    month = args[0] if args else None
    with Session(engine) as s:
        try:
            summ = cashflow_service.month_summary(s, month)
        except ValueError:
            return "Uso: /financas [AAAA-MM]  ·  Ex: /financas 2026-07"
    if not summ.entries:
        return (
            f"Nenhum lançamento em {summ.month}. Registre com /gasto, /ganho "
            "ou simplesmente me conte no chat."
        )
    lines = [
        f"💸 *Finanças {summ.month}*",
        "",
        f"Gastos: {_fmt_brl(summ.expense_brl)}",
        f"Ganhos: {_fmt_brl(summ.income_brl)}",
        f"Saldo: {_fmt_brl(summ.net_brl)}",
        "",
    ]
    expenses = [c for c in summ.by_category if c.kind == CashflowKind.EXPENSE][:6]
    if expenses:
        lines.append("Maiores gastos por categoria:")
        for c in expenses:
            lines.append(f"• {c.category}: {_fmt_brl(c.total_brl)} ({c.count}x)")
    lines.append("")
    lines.append(f"{summ.entries} lançamento(s) no mês.")
    return "\n".join(lines)


def _cmd_resetchat() -> str:
    chat_service.reset_session()
    return (
        "🧹 Conversa reiniciada. A memória fixa sobre você permanece — "
        "só o histórico da sessão foi descartado."
    )


def _cmd_ir(args: list[str]) -> str:
    year = date.today().year
    if args:
        try:
            year = int(args[0])
        except ValueError:
            return "Uso: /ir [ano]  ·  Ex: /ir 2026"
    with Session(engine) as s:
        report = tax_service.build_year_report(s, year)
    if not report["months"]:
        return f"Sem vendas em {year} — nada a apurar. (Posições e compras não geram IR.)"
    lines = [f"🧾 *IR {year} (simplificado)*", ""]
    for m in report["months"]:
        for label, key in (("Ações", "stocks"), ("Crypto", "crypto")):
            data = m.get(key) or {}
            if not data.get("sales_brl"):
                continue
            status = (
                "isento" if data.get("exempt") else f"DARF {_fmt_brl(data.get('tax_due_brl', 0.0))}"
            )
            lines.append(f"• {m['month']} {label}: vendas {_fmt_brl(data['sales_brl'])} → {status}")
    lines.append("")
    lines.append(f"Total DARF no ano: {_fmt_brl(report['total_darf_brl'])}")
    carry = report["loss_carryforward_brl"]
    if carry["stocks"] or carry["crypto"]:
        lines.append(
            f"Prejuízo a compensar: ações {_fmt_brl(carry['stocks'])} · "
            f"crypto {_fmt_brl(carry['crypto'])}"
        )
    lines.append("_Apuração simplificada — confira com seu contador._")
    return "\n".join(lines)


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
        lines.append(f"• {_local_date(r.created_at).isoformat()} — {r.kind} — {r.title}")
    lines.append("\n(os relatórios também ficam salvos e entram como consulta nos aportes)")
    return "\n".join(lines)


def _handle(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    # Free text (no leading slash) = live conversation with the consultant.
    if not stripped.startswith("/"):
        return _enqueue_chat(stripped)
    parts = stripped.split()
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
    if cmd == "ordens":
        return _cmd_ordens()
    if cmd == "executei":
        return _cmd_executei(args)
    if cmd == "ir":
        return _cmd_ir(args)
    if cmd == "gasto":
        return _cmd_gasto(args)
    if cmd == "ganho":
        return _cmd_ganho(args)
    if cmd in {"financas", "finanças"}:
        return _cmd_financas(args)
    if cmd == "resetchat":
        return _cmd_resetchat()
    if cmd == "comprei":
        return _cmd_comprei(args)
    if cmd == "vender":
        return _cmd_vender(args)
    if cmd == "aporte":
        return _cmd_aporte(args)
    return (
        "Não conheço esse comando — mande /ajuda para a lista. "
        "(Texto sem / vai direto para o consultor.)"
    )


def _acquire_single_instance() -> bool:
    """Refuse to start when another live bot process exists.

    Two pollers fighting over getUpdates produce endless Telegram 409s and
    randomly-split replies (observed: thousands of 409s in the logs).

    Uses the shared process-identity lock (atomic O_EXCL create + pid AND
    /proc starttime): a pid recycled after a reboot can't hold the bot in a
    Restart=always failure loop, and two racing starters can't both win —
    the exact invariant already fixed twice (runner A7, chat A25).
    """
    _PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not analysis_runner._try_acquire_lock_file(_PID_PATH):
        return False
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
    threading.Thread(target=_chat_worker, daemon=True).start()
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
                if _extract_media(msg) is not None:
                    reply = _handle_media(msg)
                elif text.strip():
                    reply = _handle(text)
                else:
                    reply = _unsupported_media(msg)
            except Exception as exc:  # noqa: BLE001
                reply = f"Erro: {exc}"
            if reply:
                _send(reply)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nBot encerrado.")
