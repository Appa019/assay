#!/usr/bin/env python3
"""Automatically resume any interrupted automatic analysis.

An analysis can stop mid-way if the Claude usage limit is hit and the process
later dies (machine off, terminal closed). This finds contributions whose
automatic run started (a session id was captured) but never produced the final
report, and resumes them — picking up exactly where they stopped.

Safe to run on a schedule: a per-contribution PID lock prevents clashing with a
live run, and a contribution still under its usage limit simply fails fast and
is retried on the next pass — so it resumes as soon as the window reopens.

Usage:
    python scripts/resume_pending.py             # one pass (for cron)
    python scripts/resume_pending.py --watch      # loop forever (every 600s)
    python scripts/resume_pending.py --watch 300  # loop every 300s
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import structlog  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.core.database import engine, init_db  # noqa: E402
from app.models.notification import NotificationKind, NotificationLevel  # noqa: E402
from app.services import analysis_runner, notification_center  # noqa: E402

logger = structlog.get_logger()


def _notify_on_resume(name: str, payload: dict[str, Any]) -> None:
    """Tell the client only once a resume actually begins (lock acquired)."""
    if name == "run_resume":
        notification_center.notify(
            f"♻️ Limite de uso liberou — retomando a análise do aporte "
            f"{payload['contribution_id']} de onde parou "
            f"(etapa {payload['from_step']}/{payload['total']}).",
            kind=NotificationKind.SYSTEM,
        )
    elif name == "run_resume_failed":
        notification_center.notify(
            f"♻️ Sessão anterior do aporte {payload['contribution_id']} expirou — "
            "refazendo a análise do zero.",
            kind=NotificationKind.SYSTEM,
            level=NotificationLevel.WARNING,
        )


def run_once() -> int:
    """Resume every pending analysis once. Returns how many completed now."""
    with Session(engine) as session:
        pending = analysis_runner.pending_resumable_ids(session)
    if not pending:
        logger.info("resume_pending_none")
        return 0

    logger.info("resume_pending_found", count=len(pending))
    completed = 0
    for contribution_id in pending:
        with Session(engine) as session:
            try:
                # fail_fast_on_limit: don't camp for hours inside a cron pass —
                # the next 15-min pass retries as soon as the window reopens.
                analysis_runner.run_analysis(
                    session,
                    contribution_id,
                    on_event=_notify_on_resume,
                    fail_fast_on_limit=True,
                )
                completed += 1
                logger.info("resume_pending_completed", contribution_id=str(contribution_id))
            except analysis_runner.AnalysisError as exc:
                # Still rate-limited, or a live run holds the lock — retry next pass.
                # (run_analysis caps consecutive failures via max_run_attempts.)
                logger.info(
                    "resume_pending_deferred",
                    contribution_id=str(contribution_id),
                    reason=str(exc),
                )
    return completed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resume interrupted automatic analyses.")
    parser.add_argument(
        "--watch",
        nargs="?",
        type=int,
        const=600,
        default=None,
        metavar="SECONDS",
        help="Loop forever, checking every SECONDS (default 600). Omit for a single pass.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    init_db()

    if args.watch is None:
        # Infrastructure failures (DB, imports) must page, not die silently:
        # this is the cron that revives interrupted paid analyses — if IT
        # breaks, resumes stop happening and nobody would know.
        try:
            run_once()
        except Exception as exc:  # noqa: BLE001 — last-resort alert, like every other cron
            logger.error("resume_pending_failed", error=str(exc))
            notification_center.notify(
                f"✖ resume_pending falhou: {exc}",
                kind=NotificationKind.SYSTEM,
                level=NotificationLevel.ERROR,
            )
            return 1
        return 0

    interval = max(60, args.watch)
    logger.info("resume_watch_start", interval_s=interval)
    while True:
        try:
            run_once()
        except Exception as exc:  # keep the watcher alive across unexpected errors
            logger.error("resume_watch_error", error=str(exc))
            notification_center.notify(
                f"✖ resume_pending (watch) falhou neste passe: {exc}",
                kind=NotificationKind.SYSTEM,
                level=NotificationLevel.ERROR,
            )
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("resume_watch_stop")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
