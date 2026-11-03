"""One place every message to the client goes through.

The system used to fire everything at Telegram: cron failures, the weekly
review, target/stop alerts, the monthly report, a finished order sheet. The
client does not use Telegram, so the app is the destination now.

Delivery is fan-out with one durable leg:

1. **The inbox** (``Notification`` row) — always written, first. This is what
   makes the whole thing trustworthy: Web Push fails silently in a dozen
   ordinary ways (permission revoked, phone offline, VAPID rotated, no device
   subscribed yet) and a dropped buzz must never mean a lost alert.
2. **Web Push** — best effort, so the phone buzzes without the app open.

The Telegram mirror is gone with the bot (D47).

Nothing here raises. A notification is a side effect of work that already
succeeded, and it must never be the reason that work reports failure.
"""

from __future__ import annotations

import structlog
from sqlmodel import Session, col, func, select

from app.core.database import engine
from app.models.notification import Notification, NotificationKind, NotificationLevel

logger = structlog.get_logger()

# Telegram bodies were written for a chat window; the push payload is a
# lock-screen line. Keep the push short and let the inbox carry the full text.
_PUSH_BODY_CHARS = 180
_TITLE_CHARS = 200


def _default_url(kind: NotificationKind) -> str:
    return {
        NotificationKind.ORDERS: "/investimentos?aba=carteira",
        NotificationKind.REVIEW: "/investimentos?aba=analises",
        NotificationKind.ALERT: "/investimentos?aba=carteira",
        NotificationKind.LEDGER: "/extrato",
        NotificationKind.CHAT: "/consultor",
        NotificationKind.SYSTEM: "/",
    }[kind]


def _split_title(text: str) -> tuple[str, str]:
    """First line becomes the title, the rest the body.

    Call sites write one blob (they used to hand it straight to Telegram), and
    a push needs the two separated. The first line is already a headline in
    practice — "⚠️ Revisão semanal falhou: ...".
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return ("Assay", "")
    head, _, rest = cleaned.partition("\n")
    head = head.strip()
    if len(head) > _TITLE_CHARS:
        return (head[: _TITLE_CHARS - 1].rstrip() + "…", cleaned)
    return (head, rest.strip() or head)


def failure_text(task: str, exc: BaseException) -> str:
    """A cron failure as the client should read it: what stopped and what
    happens next on the first line (the inbox title), raw detail below.

    Matched by class NAME so this module never imports the runner.
    """
    kind = type(exc).__name__
    detail = str(exc).strip()
    lower = detail.lower()
    if kind == "LimitError":
        plain = "o plano bateu no limite de uso. Tento de novo sozinho quando liberar."
    elif kind == "AuthError":
        plain = "o login do Claude expirou no servidor. Precisa renovar no Pi."
    elif "connect" in lower or "timed out" in lower or "enotimp" in lower:
        plain = "sem conexão com o serviço externo. Tento de novo na próxima janela."
    else:
        plain = "parou com um erro. Tento de novo na próxima janela."
    return f"✖ {task}: {plain}\n\nDetalhe técnico: {detail[:400]}"


def notify(
    text: str,
    *,
    kind: NotificationKind = NotificationKind.SYSTEM,
    level: NotificationLevel = NotificationLevel.INFO,
    url: str | None = None,
    push: bool = True,
) -> Notification | None:
    """Deliver one message to the client. Returns the stored row, or None if
    even the inbox write failed (logged, never raised)."""
    title, body = _split_title(text)
    target = url or _default_url(kind)

    record: Notification | None = None
    try:
        with Session(engine) as session:
            record = Notification(kind=kind, level=level, title=title, body=body, url=target)
            session.add(record)
            session.commit()
            session.refresh(record)
    except Exception:  # noqa: BLE001 — never break the caller's work
        logger.warning("notification_store_failed", exc_info=True)

    if push:
        try:
            from app.services import webpush_service

            webpush_service.notify(title, body[:_PUSH_BODY_CHARS], url=target)
        except Exception:  # noqa: BLE001
            logger.warning("notification_push_failed", exc_info=True)

    logger.info("notification_sent", kind=kind.value, level=level.value, title=title[:60])
    return record


def list_notifications(
    session: Session, *, limit: int = 50, unread_only: bool = False
) -> list[Notification]:
    stmt = select(Notification).order_by(col(Notification.created_at).desc()).limit(limit)
    if unread_only:
        stmt = stmt.where(col(Notification.read_at).is_(None))
    return list(session.exec(stmt).all())


def unread_count(session: Session) -> int:
    return int(
        session.exec(
            select(func.count())
            .select_from(Notification)
            .where(col(Notification.read_at).is_(None))
        ).one()
    )


def mark_read(session: Session, notification_id: object) -> Notification:
    record = session.get(Notification, notification_id)
    if record is None:
        raise LookupError("notificação não encontrada")
    if record.read_at is None:
        from datetime import UTC, datetime

        record.read_at = datetime.now(UTC)
        session.add(record)
        session.commit()
        session.refresh(record)
    return record


def mark_all_read(session: Session) -> int:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    pending = list(
        session.exec(select(Notification).where(col(Notification.read_at).is_(None))).all()
    )
    for record in pending:
        record.read_at = now
        session.add(record)
    if pending:
        session.commit()
    return len(pending)
