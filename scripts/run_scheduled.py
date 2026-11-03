#!/usr/bin/env python3
"""Run the contributions the client asked for, at the hour nobody is waiting.

An aporte is the heaviest job in this system (~90 min of chained opus) and the
plan's usage limit is a rolling window SHARED with the consultant chat. Asked
for at 14h it ran at 14h, and the client then hit the limit on the very chat he
uses during the day. So ``POST /api/contributions?run=true`` now only marks
``scheduled_for``; this script is what actually starts the committee.

Division of labour with the other jobs:
  - here:            contributions that never started (``scheduled_for`` due)
  - resume_pending:  contributions already started and interrupted

``scheduled_for`` is cleared the moment a run starts, so a crash mid-run cannot
make the scheduler fire the same analysis again the next night — that case
belongs to resume_pending, which resumes the SAME chained session.

The completion notice lands in the app inbox WITHOUT a push: finishing at 2am
should not ring the client's phone. Failures still push — those need a human.

    python scripts/run_scheduled.py          # run whatever is due
    python scripts/run_scheduled.py --all    # ignore the clock, run every pending one
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlmodel import select  # noqa: E402

from app.core.database import get_session, init_db  # noqa: E402
from app.models.contribution import Contribution  # noqa: E402
from app.models.notification import NotificationKind, NotificationLevel  # noqa: E402
from app.services import analysis_runner, notification_center  # noqa: E402


def _due(session, *, ignore_clock: bool) -> list[Contribution]:
    """Scheduled contributions whose hour has come and that never ran."""
    rows = list(
        session.exec(
            select(Contribution)
            .where(Contribution.scheduled_for.is_not(None))
            .where(Contribution.final_summary.is_(None))
            .order_by(Contribution.scheduled_for)
        ).all()
    )
    if ignore_clock:
        return rows
    now = datetime.now(UTC)
    due = []
    for c in rows:
        when = c.scheduled_for
        when = when if when.tzinfo else when.replace(tzinfo=UTC)
        if when <= now:
            due.append(c)
    return due


def _printer(name: str, payload: dict) -> None:
    if name == "step_start":
        print(f"▶ etapa {payload['step']}/{payload['total']}: {payload['title']}…")
    elif name == "step_retry":
        print(f"  ⏳ limite/transitório — retry {payload['attempt']} em {payload['wait_s']}s")
    elif name == "step_done":
        print(f"  ✔ ok (US$ {payload['cost_usd']:.2f}, {payload['duration_s']:.0f}s)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run scheduled contributions")
    parser.add_argument("--all", action="store_true", help="Rodar mesmo se a hora não chegou")
    args = parser.parse_args()

    init_db()
    gen = get_session()
    session = next(gen)
    failures = 0
    try:
        pending = _due(session, ignore_clock=args.all)
        if not pending:
            print("Nenhum aporte agendado para agora.")
            return 0

        print(f"{len(pending)} aporte(s) agendado(s) para rodar.")
        for contribution in pending:
            cid = contribution.id
            if analysis_runner.is_run_active(cid):
                print(f"  {cid}: já está rodando; pulando.")
                continue
            # Claim it BEFORE the run: a crash must not re-arm the scheduler.
            # From here on the analysis belongs to resume_pending.
            contribution.scheduled_for = None
            session.add(contribution)
            session.commit()
            print(f"\n▶ aporte {cid} — R$ {contribution.amount_brl}")
            try:
                summary = analysis_runner.run_analysis(
                    session,
                    cid,
                    notify=True,
                    push_on_finish=False,  # 2am: inbox yes, phone ringing no
                    on_event=_printer,
                    # Waiting in-process for the reset would carry the committee
                    # into the morning (THE RULE in install_systemd.sh); the
                    # night-only resume timer finishes it the next night.
                    fail_fast_on_limit=True,
                )
                print(f"✓ concluído (US$ {summary.total_cost_usd:.2f})")
            except (analysis_runner.LimitError, analysis_runner.RunBusyError) as exc:
                print(f"⏸ adiado: {exc}")
                notification_center.notify(
                    f"⏸ Aporte agendado {cid} parou no limite de uso ou na fila do comitê.\n"
                    "Ele continua sozinho na próxima madrugada, de onde parou.",
                    kind=NotificationKind.SYSTEM,
                    level=NotificationLevel.WARNING,
                )
            except analysis_runner.AnalysisError as exc:
                failures += 1
                print(f"✖ falhou: {exc}")
                # resume_pending picks it up if the session survived; this is
                # only the heads-up that the night run did not finish clean.
                notification_center.notify(
                    f"✖ Aporte agendado {cid} não concluiu: {exc}\n"
                    "A retomada automática tenta de novo.",
                    kind=NotificationKind.SYSTEM,
                    level=NotificationLevel.ERROR,
                )
        return 1 if failures else 0
    except Exception as exc:  # noqa: BLE001 — a broken cron must alert, not vanish
        notification_center.notify(
            notification_center.failure_text("Aporte da madrugada", exc),
            kind=NotificationKind.SYSTEM,
            level=NotificationLevel.ERROR,
        )
        print(f"run_scheduled falhou: {exc}")
        return 1
    finally:
        gen.close()


if __name__ == "__main__":
    raise SystemExit(main())
