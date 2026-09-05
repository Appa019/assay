#!/usr/bin/env python3
"""Mark every lot to market (stocks · crypto · CDB accrual) — cron-friendly.

Cheap (no Claude involved): Yahoo + CoinGecko + BCB only. Run a few times a
day so the dashboard, the reviews and the committee always see real prices.

    python scripts/refresh_prices.py
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
from app.services import notification_center, price_refresh_service  # noqa: E402


def main() -> int:
    init_db()
    try:
        with Session(engine) as session:
            result = asyncio.run(price_refresh_service.refresh_prices(session))
    except Exception as exc:  # noqa: BLE001 — a broken cron must alert, not vanish
        notification_center.notify(
            f"✖ refresh_prices falhou: {exc}",
            kind=NotificationKind.SYSTEM,
            level=NotificationLevel.ERROR,
        )
        print(f"refresh_prices falhou: {exc}")
        return 1
    print(f"Preços atualizados: {result['updated']} ativo(s).")
    for warning in result["warnings"]:
        print(f"  aviso: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
