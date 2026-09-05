"""Delivery to the app: the inbox is the durable leg, push is best effort."""

import pytest
from sqlmodel import Session, select

from app.config import settings
from app.models.notification import Notification, NotificationKind, NotificationLevel
from app.services import notification_center


@pytest.fixture(autouse=True)
def _isolated_delivery(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[str, str, str]]:
    """Point the inbox write at the test engine and capture Web Push.

    ``notify`` opens its own Session on the module-level engine (call sites are
    crons and services with no session in hand), so the fixture's in-memory
    engine has to be swapped in explicitly.
    """
    monkeypatch.setattr(notification_center, "engine", session.get_bind())

    sent: list[tuple[str, str, str]] = []
    from app.services import webpush_service

    monkeypatch.setattr(
        webpush_service,
        "notify",
        lambda title, body, url="/consultor": sent.append((title, body, url)) or 1,
    )
    return sent


def test_notification_is_stored_in_the_inbox(session: Session) -> None:
    notification_center.notify("🗓️ Revisão semanal\n\nCorpo do relatório.")
    rows = list(session.exec(select(Notification)).all())
    assert len(rows) == 1
    assert rows[0].title == "🗓️ Revisão semanal"
    assert "Corpo do relatório." in rows[0].body


def test_first_line_becomes_the_title(session: Session) -> None:
    record = notification_center.notify("✖ Falhou: coisa\ndetalhe longo aqui")
    assert record is not None
    assert record.title == "✖ Falhou: coisa"
    assert record.body == "detalhe longo aqui"


def test_single_line_message_repeats_as_body(session: Session) -> None:
    """A one-liner still needs a body: the push payload has both fields."""
    record = notification_center.notify("📭 Carteira vazia")
    assert record is not None
    assert record.title == "📭 Carteira vazia"
    assert record.body == "📭 Carteira vazia"


def test_kind_picks_the_deep_link(session: Session) -> None:
    record = notification_center.notify("nova folha", kind=NotificationKind.ORDERS)
    assert record is not None
    assert record.url == "/investimentos?aba=carteira"


def test_push_receives_a_trimmed_body(
    session: Session, _isolated_delivery: list[tuple[str, str, str]]
) -> None:
    notification_center.notify("Título\n" + "x" * 500, kind=NotificationKind.REVIEW)
    title, body, url = _isolated_delivery[0]
    assert title == "Título"
    assert len(body) <= 180
    assert url == "/investimentos?aba=analises"


def test_telegram_stays_silent_unless_the_mirror_is_on(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The client does not use Telegram; nothing may reach it by default."""
    from app.services import telegram_service

    calls: list[str] = []
    monkeypatch.setattr(telegram_service, "notify", lambda t: calls.append(t) or True)
    monkeypatch.setattr(settings, "telegram_mirror_enabled", False)
    notification_center.notify("qualquer coisa")
    assert calls == []

    monkeypatch.setattr(settings, "telegram_mirror_enabled", True)
    notification_center.notify("agora espelha")
    assert calls == ["agora espelha"]


def test_a_failed_push_still_leaves_the_inbox_row(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole reason the inbox is written first: a dropped buzz is not a
    lost alert."""
    from app.services import webpush_service

    def boom(*_args: object, **_kwargs: object) -> int:
        raise RuntimeError("push service fora do ar")

    monkeypatch.setattr(webpush_service, "notify", boom)
    record = notification_center.notify("⚠️ Alerta importante")
    assert record is not None
    assert len(list(session.exec(select(Notification)).all())) == 1


def test_unread_count_and_mark_read(session: Session) -> None:
    notification_center.notify("um")
    notification_center.notify("dois", level=NotificationLevel.WARNING)
    assert notification_center.unread_count(session) == 2

    first = notification_center.list_notifications(session)[0]
    notification_center.mark_read(session, first.id)
    assert notification_center.unread_count(session) == 1

    assert notification_center.mark_all_read(session) == 1
    assert notification_center.unread_count(session) == 0


def test_unread_only_filter(session: Session) -> None:
    notification_center.notify("lida")
    notification_center.notify("nao lida")
    rows = notification_center.list_notifications(session)
    notification_center.mark_read(session, rows[-1].id)
    unread = notification_center.list_notifications(session, unread_only=True)
    assert [r.title for r in unread] == ["nao lida"]


def test_mark_read_on_a_missing_row_raises_lookup(session: Session) -> None:
    from uuid import uuid4

    with pytest.raises(LookupError):
        notification_center.mark_read(session, uuid4())
