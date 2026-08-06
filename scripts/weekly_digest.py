#!/usr/bin/env python3
"""Weekly personal-finance digest — cheap cron, no Claude involved.

Builds a deterministic summary of the month so far (balance, top spending
categories, invested wealth — both halves of the money together) plus every
insight the weekly push budget queued up, and sends it to Telegram.
Self-gating: skips when this ISO week's digest already went out (``--force``
re-sends) and stays silent when the month's ledger is empty.

    python scripts/weekly_digest.py [--force]
"""

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlmodel import Session  # noqa: E402

from app.core.database import engine, init_db  # noqa: E402
from app.services import insight_service, telegram_service  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Digest financeiro semanal")
    parser.add_argument(
        "--force",
        action="store_true",
        help="reenvia mesmo que o digest desta semana já tenha saído",
    )
    args = parser.parse_args()

    init_db()
    try:
        if not args.force and insight_service.digest_already_sent():
            print("Digest desta semana já enviado — nada a fazer (use --force).")
            return 0
        with Session(engine) as session:
            text = insight_service.build_weekly_digest(session)
    except Exception as exc:  # noqa: BLE001 — a broken cron must alert, not vanish
        telegram_service.notify(f"✖ weekly_digest falhou: {exc}")
        print(f"weekly_digest falhou: {exc}")
        return 1
    if not text:
        print("Ledger do mês vazio — sem digest.")
        return 0
    # Success side-effects stay OUTSIDE the failure path above: only a real
    # delivery (or Telegram intentionally disabled, e.g. on the desktop)
    # drains the queue and stamps the week.
    delivered = telegram_service.notify(text)
    if delivered or not telegram_service.is_enabled():
        insight_service.mark_digest_sent()
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
