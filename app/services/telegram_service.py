"""Minimal Telegram Bot API client — notifications + locked two-way control.

All sends target the single configured chat (``settings.telegram_chat_id``);
the bot is private to one user. The committee's markdown is converted to
Telegram HTML (``parse_mode=HTML``): bold/headers become <b>, and since
Telegram has no tables, markdown tables are rendered as aligned monospace
<pre> blocks. If an HTML send is ever rejected, we fall back to plain text so
a message is never lost.
"""

import html as _html
import re
from typing import Any

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger()

_API = "https://api.telegram.org"
_MAX_LEN = 4000  # Telegram hard limit is 4096; leave headroom.
_TIMEOUT = 30.0

# --- markdown → Telegram HTML --------------------------------------------------
_BOLD2 = re.compile(r"\*\*(.+?)\*\*")
_BOLD1 = re.compile(r"(?<!\*)\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\*)")
_CODE = re.compile(r"`([^`\n]+)`")
_HEADER = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
_HR = re.compile(r"^\s*([-*_])\1{2,}\s*$")
_BULLET = re.compile(r"^(\s*)[-*]\s+(.*)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_TABLE_SEP_CELL = re.compile(r"^:?-{1,}:?$")


def _inline(s: str) -> str:
    """Escape HTML then apply inline bold/code markdown."""
    s = _html.escape(s, quote=False)
    s = _BOLD2.sub(r"<b>\1</b>", s)
    s = _BOLD1.sub(r"<b>\1</b>", s)
    s = _CODE.sub(r"<code>\1</code>", s)
    return s


def _is_table_row(line: str) -> bool:
    return line.strip().startswith("|") and line.count("|") >= 2


def _render_table(block: list[str]) -> str:
    """Render a markdown table as mobile-friendly Telegram blocks.

    Wide tables (a long 'Racional' column) overflow Telegram's narrow mobile
    view as monospace. Instead, transpose each data row into a labeled stanza
    using the header as field names — reads cleanly on a phone, no scrolling.
    """

    def _clean(cell: str) -> str:
        return cell.strip().replace("**", "").replace("`", "")

    rows = [[_clean(c) for c in ln.strip().strip("|").split("|")] for ln in block]
    data = [r for r in rows if not all(_TABLE_SEP_CELL.match(c or "-") for c in r)]
    if not data:
        return ""
    ncol = max(len(r) for r in data)
    data = [r + [""] * (ncol - len(r)) for r in data]
    header, records = data[0], data[1:]
    if not records:  # header-only → single line
        return _inline(" · ".join(c for c in header if c))

    def esc(s: str) -> str:
        return _html.escape(s, quote=False)

    blocks: list[str] = []
    for rec in records:
        if ncol == 2:  # two columns → "label: value"
            label, value = rec[0], rec[1]
            blocks.append(f"<b>{esc(label)}</b>: {esc(value)}" if label else esc(value))
            continue
        lines = [f"<b>{esc(rec[0])}</b>"] if rec[0] else []
        for i in range(1, ncol):
            if rec[i]:
                lines.append(f"• {esc(header[i])}: {esc(rec[i])}")
        blocks.append("\n".join(lines))
    # Blank line between multi-line stanzas; compact for 2-col rows.
    joiner = "\n" if ncol == 2 else "\n\n"
    return joiner.join(blocks)


def format_for_telegram(text: str) -> str:
    """Convert the committee's markdown to Telegram-safe HTML."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _is_table_row(line):
            block: list[str] = []
            while i < len(lines) and _is_table_row(lines[i]):
                block.append(lines[i])
                i += 1
            out.append(_render_table(block) if len(block) >= 2 else _inline(block[0]))
            continue
        header = _HEADER.match(line)
        if header:
            out.append("<b>" + _html.escape(header.group(1), quote=False) + "</b>")
        elif _HR.match(line):
            out.append("──────────")
        elif bullet := _BULLET.match(line):
            out.append(bullet.group(1) + "• " + _inline(bullet.group(2)))
        elif quote := _QUOTE.match(line):
            out.append(_inline(quote.group(1)))
        else:
            out.append(_inline(line))
        i += 1
    return "\n".join(out)


class TelegramError(RuntimeError):
    """A Telegram API call failed."""


def _base(token: str) -> str:
    return f"{_API}/bot{token}"


def is_enabled() -> bool:
    return settings.telegram_enabled


def chunk_text(text: str, limit: int = _MAX_LEN) -> list[str]:
    """Split long text into <=limit chunks, preferring line boundaries."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            # A single line longer than the limit: hard-split it.
            while len(line) > limit:
                chunks.append(line[:limit])
                line = line[limit:]
        current += line
    if current:
        chunks.append(current)
    return chunks


def get_me(token: str | None = None) -> dict[str, Any]:
    token = token or settings.telegram_bot_token
    if not token:
        raise TelegramError("TELEGRAM_BOT_TOKEN não configurado")
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.get(f"{_base(token)}/getMe")
    data = resp.json()
    if not data.get("ok"):
        raise TelegramError(f"getMe falhou: {data}")
    return data["result"]


def get_updates(
    offset: int | None = None,
    timeout: int = 0,
    token: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch updates (long-poll when timeout > 0)."""
    token = token or settings.telegram_bot_token
    if not token:
        raise TelegramError("TELEGRAM_BOT_TOKEN não configurado")
    params: dict[str, Any] = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    with httpx.Client(timeout=_TIMEOUT + timeout) as client:
        resp = client.get(f"{_base(token)}/getUpdates", params=params)
    data = resp.json()
    if not data.get("ok"):
        raise TelegramError(f"getUpdates falhou: {data}")
    return data["result"]


def send_message(
    text: str,
    *,
    chat_id: str | None = None,
    token: str | None = None,
) -> bool:
    """Send a (possibly chunked) message to the configured chat.

    Returns False (and logs) when Telegram isn't configured, so callers can
    fire-and-forget without guarding every call site.
    """
    token = token or settings.telegram_bot_token
    chat_id = chat_id or settings.telegram_chat_id
    if not token or not chat_id:
        logger.warning("telegram_not_configured", has_token=bool(token), has_chat=bool(chat_id))
        return False

    url = f"{_base(token)}/sendMessage"
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            for chunk in chunk_text(text):
                html_text = format_for_telegram(chunk)
                resp = client.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": html_text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
                if resp.json().get("ok"):
                    continue
                # HTML rejected → never lose the message: resend as plain text.
                logger.warning("telegram_html_rejected_fallback_plain")
                resp = client.post(
                    url,
                    json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
                )
                if not resp.json().get("ok"):
                    raise TelegramError(f"sendMessage falhou: {resp.json()}")
        return True
    except (httpx.HTTPError, TelegramError) as exc:
        logger.error("telegram_send_failed", error=str(exc))
        return False


def notify(text: str) -> bool:
    """Convenience: send to the configured chat if Telegram is enabled."""
    if not is_enabled():
        logger.info("telegram_disabled_skip_notify")
        return False
    return send_message(text)
