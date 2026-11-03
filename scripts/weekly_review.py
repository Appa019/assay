#!/usr/bin/env python3
"""Weekly committee review: macro + holdings performance + per-lot maturity.

Self-gating: only runs if 7+ days passed since the last weekly review (so it can
be scheduled daily and still fire "a cada 7 dias"). Saves a Report (auditable,
consultable on aportes) and announces it in the app.

    python scripts/weekly_review.py            # run if due
    python scripts/weekly_review.py --force     # run now
    python scripts/weekly_review.py --force --model haiku --effort low  # cheap test
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.core.database import get_session, init_db  # noqa: E402
from app.core.json_state import load_json_state, save_json_state  # noqa: E402
from app.models.notification import NotificationKind, NotificationLevel  # noqa: E402
from app.services import (  # noqa: E402
    analysis_runner,
    notification_center,
    review_service,
)

_STATE_PATH = _PROJECT_ROOT / "storage" / "weekly_review_state.json"
_SKIP_NOTE_KEY = "last_empty_skip_note"
_SKIP_NOTE_INTERVAL = timedelta(days=7)

_EMPTY_SKIP_NOTE = (
    "📭 Carteira e ledger vazios — revisão semanal pulada. "
    "Registre uma compra ou um gasto e eu volto a revisar toda semana."
)


def _should_send_skip_note(state: dict, now: datetime) -> bool:
    """Throttle the 'skipped: empty' note to the review cadence.

    The cron runs DAILY (self-gated to 7 days by the last WEEKLY report), but
    a skip writes no Report row — without this throttle an empty book would
    ping the owner every single day.
    """
    raw = state.get(_SKIP_NOTE_KEY)
    if not isinstance(raw, str):
        return True
    try:
        last = datetime.fromisoformat(raw)
    except ValueError:
        return True  # corrupt state: prefer one extra note over silence
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return now - last >= _SKIP_NOTE_INTERVAL


def _is_due(session) -> bool:
    """Shared with check_cadence, which defers maturity runs to a due weekly."""
    return review_service.days_until_weekly_due(session) <= 0


def _printer(name: str, payload: dict) -> None:
    if name == "step_start":
        print(f"▶ etapa {payload['step']}/{payload['total']}: {payload['title']}…")
    elif name == "step_retry":
        print(f"  ⏳ limite/transitório — retry {payload['attempt']} em {payload['wait_s']}s")
    elif name == "step_done":
        print(f"  ✔ ok (US$ {payload['cost_usd']:.2f}, {payload['duration_s']:.0f}s)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Weekly committee review")
    parser.add_argument("--force", action="store_true", help="Rodar mesmo se não vencido")
    parser.add_argument("--model", default=analysis_runner.DEFAULT_MODEL)
    parser.add_argument("--effort", default=analysis_runner.DEFAULT_EFFORT)
    parser.add_argument("--no-notify", action="store_true", help="Não avisar no app (inbox + push)")
    args = parser.parse_args()

    init_db()
    gen = get_session()
    session = next(gen)
    try:
        if not args.force and not _is_due(session):
            print("Revisão semanal ainda não venceu (menos de 7 dias). Use --force.")
            return 0
        if not review_service.has_reviewable_data(session):
            # Cost guard: no assets, no trades, no cashflow — skip the whole
            # opus chain (and the price/macro fetches) instead of paying to
            # describe an empty book.
            print("Carteira e ledger vazios — revisão semanal pulada.")
            now = datetime.now(UTC)
            state = load_json_state(_STATE_PATH)
            if not args.no_notify and _should_send_skip_note(state, now):
                notification_center.notify(_EMPTY_SKIP_NOTE, kind=NotificationKind.REVIEW)
                state[_SKIP_NOTE_KEY] = now.isoformat()
                save_json_state(_STATE_PATH, state)
            return 0
        print("Atualizando preços…")
        try:
            from sqlmodel import Session

            from app.core.database import engine
            from app.services import price_refresh_service

            with Session(engine) as ps:
                asyncio.run(price_refresh_service.refresh_prices(ps))
        except Exception as exc:  # noqa: BLE001 — stale prices beat no review
            print(f"  aviso: refresh de preços falhou ({exc}); usando os últimos salvos.")
        print("Capturando macro…")
        macro = asyncio.run(review_service.fetch_macro())
        report = review_service.run_weekly_review(
            session,
            macro_ctx=macro,
            model=args.model,
            effort=args.effort,
            notify=not args.no_notify,
            on_event=_printer,
        )
        if report is None:
            # Backstop: the service re-checks the same guard (data could have
            # been deleted between our check and the run); it already notified.
            print("Carteira e ledger vazios — revisão semanal pulada.")
            return 0
        print(f"\n✓ Revisão semanal salva (id {report.id}, US$ {report.cost_usd:.2f}).")
        print("─" * 60)
        print(report.content)
        return 0
    except analysis_runner.AnalysisError as exc:
        # "another run holds the global lock" is a normal defer, not a failure.
        if "em andamento" in str(exc):
            print(f"Adiada: {exc}")
            return 0
        notification_center.notify(
            notification_center.failure_text("Revisão semanal", exc),
            kind=NotificationKind.SYSTEM,
            level=NotificationLevel.ERROR,
        )
        print(f"Erro na revisão semanal: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 — a broken cron must alert, not vanish
        notification_center.notify(
            notification_center.failure_text("Revisão semanal", exc),
            kind=NotificationKind.SYSTEM,
            level=NotificationLevel.ERROR,
        )
        print(f"Erro na revisão semanal: {exc}")
        return 1
    finally:
        gen.close()


if __name__ == "__main__":
    raise SystemExit(main())
