#!/usr/bin/env python3
"""Daily deterministic ledger insights — cheap cron, no Claude involved.

Runs the three insight rules (run-rate balance projection, per-category
anomaly, card-invoice-closed notice) via ``insight_service.run_daily``: at most the weekly budget of
pushes goes straight to Telegram, the overflow queues up for the Sunday
digest. Scheduled at 09:07 local on purpose — insights never ping at night.

    python scripts/daily_insights.py
"""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlmodel import Session  # noqa: E402

from app.core.database import engine, init_db  # noqa: E402
from app.models.notification import NotificationKind, NotificationLevel  # noqa: E402
from app.services import insight_service, notification_center  # noqa: E402


def main() -> int:
    init_db()
    try:
        with Session(engine) as session:
            result = insight_service.run_daily(session)
    except Exception as exc:  # noqa: BLE001 — a broken cron must alert, not vanish
        notification_center.notify(
            f"✖ daily_insights falhou: {exc}",
            kind=NotificationKind.SYSTEM,
            level=NotificationLevel.ERROR,
        )
        print(f"daily_insights falhou: {exc}")
        return 1
    print(
        f"{len(result['sent'])} insight(s) enviado(s), "
        f"{len(result['queued'])} na fila do digest semanal."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
