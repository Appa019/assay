"""Minimal Telegram Bot API client — notifications + locked two-way control.

All sends target the single configured chat (``settings.telegram_chat_id``);
the bot is private to one user. Messages are plain text (no parse_mode) so the
committee's markdown/tables never break Telegram's strict escaping.
"""

from typing import Any

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger()

_API = "https://api.telegram.org"
_MAX_LEN = 4000  # Telegram hard limit is 4096; leave headroom.
_TIMEOUT = 30.0


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

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            for chunk in chunk_text(text):
                resp = client.post(
                    f"{_base(token)}/sendMessage",
                    json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
                )
                payload = resp.json()
                if not payload.get("ok"):
                    raise TelegramError(f"sendMessage falhou: {payload}")
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
