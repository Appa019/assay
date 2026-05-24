#!/usr/bin/env python3
"""Daily maturity job (idempotent — safe to run every day via cron).

Newly matured stock/crypto lots (crossed the 30-day lock) → run a committee
maturity review (saved + sent to Telegram). Contributions are ad-hoc, so there
is no scheduled aporte reminder — the recurring touchpoint is the weekly review.

Install with ``scripts/install_cron.sh``.

    python scripts/check_cadence.py
"""

import asyncio
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.core.database import get_session, init_db  # noqa: E402
from app.services import notification_service, review_service  # noqa: E402


def main() -> int:
    if not settings.telegram_enabled:
        print("Telegram não configurado (rode scripts/telegram_setup.py). Nada a fazer.")
        return 0
    init_db()
    gen = get_session()
    session = next(gen)
    try:
        # 1) Maturity reviews for lots that just unlocked.
        matured, keys = notification_service.pending_maturities(session)
        if matured:
            print(f"Lotes recém-liberados: {len(matured)} — rodando análise de maturidade…")
            macro = asyncio.run(review_service.fetch_macro())
            review_service.run_maturity_review(session, matured, macro_ctx=macro)
            notification_service.mark_maturities(keys)
            print("  análise de maturidade enviada e marcada.")
        else:
            print("Nenhum lote novo liberado.")
        return 0
    finally:
        gen.close()


if __name__ == "__main__":
    raise SystemExit(main())
