"""Web Push: VAPID keygen persistence, the subscription lifecycle and the
best-effort sender that prunes dead endpoints instead of retrying them."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from app.models.push_subscription import PushSubscription
from app.services import webpush_service


@pytest.fixture()
def key_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    directory = tmp_path / "webpush"
    monkeypatch.setattr(webpush_service, "_KEY_DIR", directory)
    monkeypatch.setattr(webpush_service, "_PRIVATE_PEM", directory / "vapid_private.pem")
    monkeypatch.setattr(webpush_service, "_PUBLIC_KEY", directory / "vapid_public.txt")
    return directory


def test_public_key_is_generated_once_and_reused(key_dir: Path) -> None:
    first = webpush_service.get_public_key()
    second = webpush_service.get_public_key()
    assert first == second
    assert len(first) == 87  # uncompressed P-256 point, base64url
    pem = key_dir / "vapid_private.pem"
    assert pem.exists()
    assert (pem.stat().st_mode & 0o777) == 0o600


def test_subscription_upsert_and_delete(session: Session) -> None:
    webpush_service.save_subscription(session, "https://push/e1", "k1", "a1")
    webpush_service.save_subscription(session, "https://push/e1", "k2", "a2")
    rows = list(session.exec(select(PushSubscription)).all())
    assert len(rows) == 1  # re-subscribing the same device replaces, not appends
    assert rows[0].p256dh == "k2"
    assert webpush_service.delete_subscription(session, "https://push/e1") is True
    assert webpush_service.delete_subscription(session, "https://push/e1") is False


def test_notify_sends_and_prunes_gone_endpoints(
    key_dir: Path, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(webpush_service, "engine", session.get_bind())
    webpush_service.save_subscription(session, "https://push/alive", "k", "a")
    webpush_service.save_subscription(session, "https://push/gone", "k", "a")

    calls: list[str] = []

    def fake_webpush(*, subscription_info, data, **_kwargs) -> None:  # noqa: ANN003
        calls.append(subscription_info["endpoint"])
        if "gone" in subscription_info["endpoint"]:
            raise webpush_service.WebPushException(
                "gone", response=SimpleNamespace(status_code=410)
            )
        assert json.loads(data)["title"] == "Teste"

    monkeypatch.setattr(webpush_service, "webpush", fake_webpush)
    assert webpush_service.notify("Teste", "corpo") == 1
    assert len(calls) == 2
    remaining = list(session.exec(select(PushSubscription)).all())
    assert [r.endpoint for r in remaining] == ["https://push/alive"]


def test_notify_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A broken push stack must cost a log line, never the turn that fired it."""
    monkeypatch.setattr(webpush_service, "engine", None)
    assert webpush_service.notify("t", "b") == 0
