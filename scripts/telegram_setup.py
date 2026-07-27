#!/usr/bin/env python3
"""Detect your Telegram chat_id and lock the bot to it.

Run this once: it prints a one-time pairing code, and ONLY the chat that
sends that exact code becomes the owner — a stranger messaging the bot during
the setup window can no longer hijack it. The chat_id is written to .env and
a confirmation is sent. From then on the bot talks only to you.

    python scripts/telegram_setup.py
"""

import secrets
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.services import telegram_service  # noqa: E402

_ENV_PATH = _PROJECT_ROOT / ".env"
_WAIT_SECONDS = 180


def _set_env_var(key: str, value: str) -> None:
    """Upsert KEY=value in .env, preserving everything else."""
    lines = _ENV_PATH.read_text(encoding="utf-8").splitlines() if _ENV_PATH.exists() else []
    out: list[str] = []
    found = False
    for line in lines:
        if line.startswith(f"{key}="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    _ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    if not settings.telegram_bot_token:
        print("TELEGRAM_BOT_TOKEN não configurado no .env.")
        return 2

    try:
        me = telegram_service.get_me()
    except telegram_service.TelegramError as exc:
        print(f"Token inválido: {exc}")
        return 1
    pairing_code = f"{secrets.randbelow(1_000_000):06d}"
    print(f"Bot: @{me.get('username')} (id {me.get('id')})")
    print(f"Abra https://t.me/{me.get('username')} e envie EXATAMENTE este código:")
    print(f"\n    {pairing_code}\n")
    print(f"Só o chat que enviar o código vira o dono. Aguardando (até {_WAIT_SECONDS}s)…")

    deadline = time.monotonic() + _WAIT_SECONDS
    offset: int | None = None
    chat_id: str | None = None
    while time.monotonic() < deadline:
        try:
            updates = telegram_service.get_updates(offset=offset, timeout=20)
        except telegram_service.TelegramError as exc:
            print(f"Erro ao buscar updates: {exc}")
            return 1
        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message") or {}
            chat = msg.get("chat") or {}
            text = (msg.get("text") or "").strip()
            if chat.get("id") is None:
                continue
            if text != pairing_code:
                print(f"Ignorado chat {chat.get('id')} (não enviou o código de pareamento).")
                continue
            chat_id = str(chat["id"])
            name = chat.get("first_name") or chat.get("username") or "?"
            print(f"Código correto — chat_id={chat_id} ({name}).")
            break
        if chat_id:
            break

    if not chat_id:
        print("Código não recebido. Envie o código exibido acima e rode de novo.")
        return 1

    _set_env_var("TELEGRAM_CHAT_ID", chat_id)
    print(f"Salvo TELEGRAM_CHAT_ID={chat_id} em .env")

    telegram_service.send_message(
        "✅ Bot conectado. A partir de agora falo só com você. "
        "Mande /ajuda para ver o que posso fazer.",
        chat_id=chat_id,
    )
    print("Mensagem de confirmação enviada. Pronto!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
