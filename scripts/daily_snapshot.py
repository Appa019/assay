#!/usr/bin/env python3
"""Record today's portfolio valuation (equity-curve datapoint) — cron daily.

Refreshes prices first so the snapshot is marked to market, then upserts the
day's row (idempotent). Powers GET /api/portfolio/history and the dashboard
equity curve.

    python scripts/daily_snapshot.py
"""

import asyncio
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlmodel import Session  # noqa: E402

from app.core.database import engine, init_db  # noqa: E402
from app.models.notification import NotificationKind, NotificationLevel  # noqa: E402
from app.services import (  # noqa: E402
    notification_center,
    portfolio_service,
    price_refresh_service,
)


def main() -> int:
    init_db()
    try:
        with Session(engine) as session:
            refresh = asyncio.run(price_refresh_service.refresh_prices(session))
            snapshot = portfolio_service.record_daily_snapshot(session)
    except Exception as exc:  # noqa: BLE001 — a broken cron must alert, not vanish
        notification_center.notify(
            notification_center.failure_text("Snapshot da carteira", exc),
            kind=NotificationKind.SYSTEM,
            level=NotificationLevel.ERROR,
        )
        print(f"daily_snapshot falhou: {exc}")
        return 1
    print(
        f"Snapshot de {snapshot.snapshot_date.isoformat()} gravado "
        f"(total R$ {float(snapshot.total_value):,.2f}; "
        f"{refresh['updated']} preço(s) atualizados)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
