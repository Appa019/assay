"""Activation + robustness: unknown-chat warning, onboarding, busy retry,
queue feedback and the empty-book cost guard for the weekly review.

Everything here runs WITHOUT the bot's polling loop: the decisions are pure
functions (state in, decision out) and the side-effectful paths are exercised
with monkeypatched send/state seams.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlmodel import Session

import scripts.telegram_bot as bot
import scripts.weekly_review as weekly
from app.core.json_state import load_json_state, save_json_state
from app.models.asset import AssetClass
from app.models.cashflow import CashflowEntry, CashflowKind
from app.models.trade import Trade, TradeSide
from app.services import chat_service, review_service


@pytest.fixture(autouse=True)
def _drain_queue():
    yield
    while not bot._chat_queue.empty():
        bot._chat_queue.get_nowait()


@pytest.fixture()
def state_path(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Point the bot's persistent state at a throwaway file."""
    path = tmp_path / "bot_state.json"
    monkeypatch.setattr(bot, "_STATE_PATH", path)
    return path


# --- tolerant JSON state ----------------------------------------------------


def test_json_state_roundtrip(tmp_path) -> None:
    path = tmp_path / "state.json"
    assert save_json_state(path, {"onboarding_sent": True, "ids": ["1", "2"]})
    assert load_json_state(path) == {"onboarding_sent": True, "ids": ["1", "2"]}


def test_json_state_missing_file_is_empty(tmp_path) -> None:
    assert load_json_state(tmp_path / "nope.json") == {}


def test_json_state_malformed_is_empty(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{not json!!", encoding="utf-8")
    assert load_json_state(path) == {}


def test_json_state_non_dict_is_empty(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text('["a", "b"]', encoding="utf-8")
    assert load_json_state(path) == {}


def test_json_state_save_never_raises(tmp_path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file", encoding="utf-8")
    # Parent "directory" is a file → mkdir fails → best-effort False, no raise.
    assert save_json_state(blocker / "state.json", {"k": 1}) is False


# --- unknown-chat warning (owner-facing, once per chat_id) ------------------


def test_should_notify_unknown_chat_decisions() -> None:
    assert bot._should_notify_unknown_chat({}, "123")
    assert not bot._should_notify_unknown_chat({"unknown_chats_notified": ["123"]}, "123")
    assert bot._should_notify_unknown_chat({"unknown_chats_notified": ["999"]}, "123")
    # Malformed state never blocks the warning (tolerant parsing).
    assert bot._should_notify_unknown_chat({"unknown_chats_notified": "oops"}, "123")
    # Int/str mismatch (Telegram ids are ints, we store strings) still matches.
    assert not bot._should_notify_unknown_chat({"unknown_chats_notified": [123]}, "123")


def test_mark_unknown_chat_notified_is_idempotent() -> None:
    state = bot._mark_unknown_chat_notified({}, "123")
    state = bot._mark_unknown_chat_notified(state, "123")
    assert state["unknown_chats_notified"] == ["123"]
    state = bot._mark_unknown_chat_notified({"unknown_chats_notified": "oops"}, "7")
    assert state["unknown_chats_notified"] == ["7"]


def test_describe_sender_variants() -> None:
    msg = {"from": {"first_name": "Pedro", "last_name": "P", "username": "pp"}}
    assert bot._describe_sender(msg) == "Pedro P @pp"
    assert bot._describe_sender({"chat": {"username": "someone"}}) == "@someone"
    assert bot._describe_sender({}) == "sem nome"


def test_warn_unknown_chat_sends_once(monkeypatch: pytest.MonkeyPatch, state_path) -> None:
    sent: list[str] = []
    monkeypatch.setattr(bot, "_send", lambda text: sent.append(text) or True)
    msg = {"from": {"first_name": "Intruso", "username": "intruso"}}

    bot._warn_unknown_chat("555", msg)
    bot._warn_unknown_chat("555", msg)  # same chat again → silent

    assert len(sent) == 1
    assert "555" in sent[0]
    assert "@intruso" in sent[0]
    assert "telegram_setup" in sent[0]
    assert load_json_state(state_path)["unknown_chats_notified"] == ["555"]

    bot._warn_unknown_chat("777", msg)  # different chat → new warning
    assert len(sent) == 2


def test_warn_unknown_chat_retries_after_failed_send(
    monkeypatch: pytest.MonkeyPatch, state_path
) -> None:
    attempts: list[str] = []
    monkeypatch.setattr(bot, "_send", lambda text: attempts.append(text) and False)
    bot._warn_unknown_chat("555", {})
    # Send failed → NOT marked → the next message from that chat retries.
    assert "unknown_chats_notified" not in load_json_state(state_path)
    monkeypatch.setattr(bot, "_send", lambda text: attempts.append(text) or True)
    bot._warn_unknown_chat("555", {})
    assert len(attempts) == 2
    assert load_json_state(state_path)["unknown_chats_notified"] == ["555"]


# --- onboarding (empty chat_message + never sent → introduce once) ----------


def test_should_send_onboarding_decisions() -> None:
    assert bot._should_send_onboarding({}, history_empty=True)
    assert not bot._should_send_onboarding({"onboarding_sent": True}, history_empty=True)
    assert not bot._should_send_onboarding({}, history_empty=False)
    assert not bot._should_send_onboarding({"onboarding_sent": True}, history_empty=False)


def test_maybe_send_onboarding_sends_once(monkeypatch: pytest.MonkeyPatch, state_path) -> None:
    sent: list[str] = []
    monkeypatch.setattr(bot, "_chat_history_empty", lambda: True)
    monkeypatch.setattr(bot, "_send", lambda text: sent.append(text) or True)

    bot._maybe_send_onboarding()
    bot._maybe_send_onboarding()  # second boot → never resent

    assert len(sent) == 1
    assert "renda mensal" in sent[0]
    assert "gastei 42 no mercado" in sent[0]
    assert load_json_state(state_path)["onboarding_sent"] is True


def test_maybe_send_onboarding_skips_used_consultant(
    monkeypatch: pytest.MonkeyPatch, state_path
) -> None:
    sent: list[str] = []
    monkeypatch.setattr(bot, "_chat_history_empty", lambda: False)
    monkeypatch.setattr(bot, "_send", lambda text: sent.append(text) or True)
    bot._maybe_send_onboarding()
    assert sent == []
    assert not state_path.exists()


def test_maybe_send_onboarding_survives_errors(monkeypatch: pytest.MonkeyPatch, state_path) -> None:
    def boom() -> bool:
        raise RuntimeError("db down")

    monkeypatch.setattr(bot, "_chat_history_empty", boom)
    bot._maybe_send_onboarding()  # must not raise — startup goes on


# --- busy retry (ChatBusyError re-queues once, then tells the user) ---------


def test_consume_chat_item_requeues_once_on_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    requeued: list[tuple[str, str | None, int]] = []

    def busy(*a, **k) -> str:  # noqa: ANN002, ANN003
        raise chat_service.ChatBusyError("⏳ ocupado")

    monkeypatch.setattr(chat_service, "converse", busy)
    monkeypatch.setattr(bot, "_requeue_chat_later", lambda t, d, a: requeued.append((t, d, a)))

    # First attempt → silent requeue, nothing sent to the user.
    assert bot._consume_chat_item(("oi", None, 0)) is None
    assert requeued == [("oi", None, 1)]

    # Second attempt still busy → user is told, NO further requeue.
    reply = bot._consume_chat_item(("oi", None, 1))
    assert reply is not None and "ocupado" in reply
    assert len(requeued) == 1


def test_consume_chat_item_success_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_service, "converse", lambda *a, **k: "resposta")
    assert bot._consume_chat_item(("oi", None, 0)) == "resposta"

    def unavailable(*a, **k) -> str:  # noqa: ANN002, ANN003
        raise chat_service.ChatUnavailableError("limite atingido")

    monkeypatch.setattr(chat_service, "converse", unavailable)
    assert bot._consume_chat_item(("oi", None, 0)) == "limite atingido"

    def explode(*a, **k) -> str:  # noqa: ANN002, ANN003
        raise ValueError("kaboom")

    monkeypatch.setattr(chat_service, "converse", explode)
    reply = bot._consume_chat_item(("oi", None, 0))
    assert reply is not None and "kaboom" in reply  # worker never raises


def test_requeue_chat_later_puts_item_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot, "_BUSY_RETRY_DELAY_S", 0.01)
    bot._requeue_chat_later("oi", "oi", 1)
    assert bot._chat_queue.get(timeout=2) == ("oi", "oi", 1)


# --- queue feedback ("Na fila" from the FIRST message ahead) ----------------


def test_enqueue_chat_feedback_threshold() -> None:
    assert bot._enqueue_chat("primeira") is None
    queued = bot._enqueue_chat("segunda")
    assert queued is not None and "1 mensagem" in queued


# --- weekly review cost guard (empty book → no opus chain) ------------------


def test_has_reviewable_data_empty(session: Session) -> None:
    assert not review_service.has_reviewable_data(session)


def test_has_reviewable_data_with_asset(session: Session, stock_locked) -> None:
    assert review_service.has_reviewable_data(session)


def test_has_reviewable_data_with_trade_only(session: Session) -> None:
    session.add(
        Trade(
            ticker="VALE3",
            asset_class=AssetClass.STOCKS,
            side=TradeSide.SELL,
            quantity=Decimal("10"),
            price=Decimal("60"),
            total_brl=Decimal("600.00"),
        )
    )
    session.commit()
    assert review_service.has_reviewable_data(session)


def test_has_reviewable_data_with_cashflow_only(session: Session) -> None:
    session.add(CashflowEntry(kind=CashflowKind.EXPENSE, amount_brl=Decimal("42.90")))
    session.commit()
    assert review_service.has_reviewable_data(session)


def test_run_weekly_review_skips_empty_book(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("run_chain must not start on an empty book")

    monkeypatch.setattr(review_service.analysis_runner, "run_chain", never)
    sent: list[str] = []
    monkeypatch.setattr(
        review_service.notification_center,
        "notify",
        lambda t, **_kw: sent.append(t) or object(),
    )

    report = review_service.run_weekly_review(session, macro_ctx={})

    assert report is None
    assert len(sent) == 1 and "pulada" in sent[0]


def test_run_weekly_review_skip_respects_notify_flag(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[str] = []
    monkeypatch.setattr(
        review_service.notification_center,
        "notify",
        lambda t, **_kw: sent.append(t) or object(),
    )
    assert review_service.run_weekly_review(session, macro_ctx={}, notify=False) is None
    assert sent == []


def test_run_weekly_review_runs_with_data(
    session: Session, stock_locked, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _StartedError(Exception):
        pass

    def sentinel(*a, **k):  # noqa: ANN002, ANN003
        raise _StartedError

    monkeypatch.setattr(review_service.analysis_runner, "run_chain", sentinel)
    with pytest.raises(_StartedError):  # guard let the chain start
        review_service.run_weekly_review(session, macro_ctx={})


# --- weekly skip-note throttle (daily cron must not ping daily) -------------


def test_should_send_skip_note_throttles_to_seven_days() -> None:
    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    assert weekly._should_send_skip_note({}, now)
    recent = {"last_empty_skip_note": (now - timedelta(days=2)).isoformat()}
    assert not weekly._should_send_skip_note(recent, now)
    old = {"last_empty_skip_note": (now - timedelta(days=8)).isoformat()}
    assert weekly._should_send_skip_note(old, now)


def test_should_send_skip_note_tolerates_bad_state() -> None:
    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    assert weekly._should_send_skip_note({"last_empty_skip_note": "not-a-date"}, now)
    assert weekly._should_send_skip_note({"last_empty_skip_note": 12345}, now)
    # Naive timestamp from an older writer → interpreted as UTC, not a crash.
    naive = {"last_empty_skip_note": (now - timedelta(days=1)).replace(tzinfo=None).isoformat()}
    assert not weekly._should_send_skip_note(naive, now)
