import json
from pathlib import Path

import pytest

from app.config import settings
from app.services import analysis_runner, chat_service
from app.services.analysis_runner import (
    LimitError,
    RetryableError,
    SessionNotFoundError,
    StepResult,
)


@pytest.fixture()
def chat_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(chat_service, "CHAT_WORKSPACE", tmp_path / "chat_ws")
    monkeypatch.setattr(analysis_runner, "WORKSPACE", tmp_path / "agent_ws")
    monkeypatch.setattr(analysis_runner, "_RUN_LOCK_DIR", tmp_path / "locks")
    monkeypatch.setattr(analysis_runner, "_TRANSCRIPT_DIR", tmp_path / "transcripts")
    return tmp_path


def _step(result: str = "olá!", session_id: str = "sess-1") -> StepResult:
    return StepResult(label="", result=result, cost_usd=0.01, duration_s=1.0, session_id=session_id)


def test_ensure_workspace_seeds_and_preserves_memory(chat_dirs: Path) -> None:
    ws = chat_service._ensure_chat_workspace()
    assert (ws / "CLAUDE.md").exists()
    assert (ws / ".mcp.json").exists()
    memory = ws / "MEMORY.md"
    memory.write_text("memória do cliente", encoding="utf-8")
    chat_service._ensure_chat_workspace()
    # Standing orders refresh every call; the agent's memory is never clobbered.
    assert memory.read_text(encoding="utf-8") == "memória do cliente"
    orders = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert str(settings.min_holding_days) in orders
    assert "/api/cashflow" in orders


def test_first_turn_starts_fresh_and_persists_session(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_step(prompt: str, *, resume_session_id, **kwargs) -> StepResult:
        seen["prompt"] = prompt
        seen["resume"] = resume_session_id
        return _step()

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)
    reply, route = chat_service.run_chat_turn("quanto está o BTC?")
    assert reply == "olá!"
    assert route.model  # the router always picks something

    assert seen["resume"] is None
    assert "Nova sessão" in str(seen["prompt"])
    assert "quanto está o BTC?" in str(seen["prompt"])
    state = json.loads((chat_service.CHAT_WORKSPACE / "session.json").read_text())
    assert state["session_id"] == "sess-1"
    assert state["turns"] == 1


def test_second_turn_resumes_same_session(chat_dirs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chat_service._ensure_chat_workspace()
    chat_service._save_state("sess-1", 3)
    seen: dict[str, object] = {}

    def fake_step(prompt: str, *, resume_session_id, **kwargs) -> StepResult:
        seen["prompt"] = prompt
        seen["resume"] = resume_session_id
        return _step(result="resumido", session_id="sess-1")

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)
    assert chat_service.run_chat_turn("e a PETR4?")[0] == "resumido"
    assert seen["resume"] == "sess-1"
    assert "Nova sessão" not in str(seen["prompt"])
    assert chat_service._load_state()["turns"] == 4


def test_session_rotates_after_max_turns(chat_dirs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chat_service._ensure_chat_workspace()
    chat_service._save_state("sess-old", settings.chat_max_turns)
    seen: dict[str, object] = {}

    def fake_step(prompt: str, *, resume_session_id, **kwargs) -> StepResult:
        seen["prompt"] = prompt
        seen["resume"] = resume_session_id
        return _step(session_id="sess-new")

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)
    chat_service.run_chat_turn("oi")
    assert seen["resume"] is None  # rotated — fresh session
    assert "MESMA conversa" in str(seen["prompt"])
    state = chat_service._load_state()
    assert state["session_id"] == "sess-new"
    assert state["turns"] == 1


def test_vanished_session_restarts_fresh_once(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat_service._ensure_chat_workspace()
    chat_service._save_state("sess-gone", 2)
    calls: list[str | None] = []

    def fake_step(prompt: str, *, resume_session_id, **kwargs) -> StepResult:
        calls.append(resume_session_id)
        if resume_session_id is not None:
            raise SessionNotFoundError("no conversation found")
        return _step(result="recomecei", session_id="sess-new")

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)
    assert chat_service.run_chat_turn("oi")[0] == "recomecei"
    assert calls == ["sess-gone", None]
    assert chat_service._load_state()["session_id"] == "sess-new"


@pytest.mark.parametrize(
    "error",
    [LimitError("usage limit reached"), RetryableError("timeout")],
)
def test_failures_surface_as_unavailable(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def fake_step(prompt: str, *, resume_session_id, **kwargs) -> StepResult:
        raise error

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)
    with pytest.raises(chat_service.ChatUnavailableError):
        chat_service.run_chat_turn("oi")
    # A failed turn must not corrupt the (empty) session state.
    assert chat_service._load_state() == {}


def test_busy_lock_raises_chat_busy(chat_dirs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analysis_runner, "_try_acquire_lock_file", lambda _p: False)
    with pytest.raises(chat_service.ChatBusyError):
        chat_service.run_chat_turn("oi")


def test_lock_released_after_turn(chat_dirs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analysis_runner, "_run_claude_step", lambda *a, **k: _step())
    chat_service.run_chat_turn("oi")
    assert not chat_service._chat_lock_path().exists()


def test_converse_persists_both_sides_of_the_turn(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch, session
) -> None:
    """D7: every caller goes through converse() precisely because it is what
    writes the shared transcript — both rows, whichever door was used."""
    from sqlmodel import select

    from app.models.chat import ChatChannel, ChatMessage, ChatRole, ChatTurnStatus

    monkeypatch.setattr(chat_service, "engine", session.get_bind())
    monkeypatch.setattr(analysis_runner, "_run_claude_step", lambda *a, **k: _step("resposta!"))

    reply = chat_service.converse("quanto está o BTC hoje?", ChatChannel.WEB)
    assert reply == "resposta!"

    rows = list(session.exec(select(ChatMessage).order_by(ChatMessage.created_at)).all())
    assert [r.role for r in rows] == [ChatRole.USER, ChatRole.ASSISTANT]
    assert all(r.channel == ChatChannel.WEB for r in rows)
    assert rows[0].content == "quanto está o BTC hoje?"
    assert rows[1].content == "resposta!"
    assert rows[1].status == ChatTurnStatus.DONE
    assert rows[1].model  # the route taken is recorded on the message


def test_converse_records_the_failure_on_the_pending_row(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch, session
) -> None:
    from sqlmodel import select

    from app.models.chat import ChatChannel, ChatMessage, ChatRole, ChatTurnStatus

    monkeypatch.setattr(chat_service, "engine", session.get_bind())

    def fake_step(*_a: object, **_k: object) -> StepResult:
        raise LimitError("usage limit reached")

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)
    with pytest.raises(chat_service.ChatUnavailableError):
        chat_service.converse("oi, tudo bem?", ChatChannel.TELEGRAM)

    rows = list(session.exec(select(ChatMessage).order_by(ChatMessage.created_at)).all())
    assert rows[-1].role == ChatRole.ASSISTANT
    assert rows[-1].status == ChatTurnStatus.FAILED
    assert "limite" in rows[-1].content.lower()


def test_reset_session_drops_state(chat_dirs: Path) -> None:
    chat_service._ensure_chat_workspace()
    chat_service._save_state("sess-1", 5)
    chat_service.reset_session()
    assert chat_service._load_state() == {}


def test_fresh_session_is_seeded_with_recent_transcript(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rotated/fresh session must carry the conversation tail from the DB —
    MEMORY.md alone loses whatever was being discussed at rotation time."""
    from app.models.chat import ChatChannel, ChatMessage, ChatRole, ChatTurnStatus

    fake_history = [
        ChatMessage(
            role=ChatRole.USER,
            content="quanto rende meu CDB?",
            channel=ChatChannel.TELEGRAM,
            status=ChatTurnStatus.DONE,
        ),
        ChatMessage(
            role=ChatRole.ASSISTANT,
            content="Rende CDI, ~14% ao ano.",
            channel=ChatChannel.TELEGRAM,
            status=ChatTurnStatus.DONE,
        ),
        # The copy of the message being answered NOW — must be dropped.
        ChatMessage(
            role=ChatRole.USER,
            content="e depois de impostos?",
            channel=ChatChannel.WEB,
            status=ChatTurnStatus.DONE,
        ),
    ]
    monkeypatch.setattr(chat_service, "history", lambda limit=60: fake_history)
    seen: dict[str, object] = {}

    def fake_step(prompt: str, *, resume_session_id, **kwargs) -> StepResult:
        seen["prompt"] = prompt
        return _step()

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)
    chat_service.run_chat_turn("e depois de impostos?")
    prompt = str(seen["prompt"])
    assert "Cliente: quanto rende meu CDB?" in prompt
    assert "Consultor: Rende CDI" in prompt
    # The just-recorded copy of the current message isn't echoed as history.
    assert prompt.count("e depois de impostos?") == 1


def test_resumed_turn_carries_no_transcript_block(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat_service._ensure_chat_workspace()
    chat_service._save_state("sess-1", 3)
    seen: dict[str, object] = {}

    def fake_step(prompt: str, *, resume_session_id, **kwargs) -> StepResult:
        seen["prompt"] = prompt
        return _step(session_id="sess-1")

    monkeypatch.setattr(
        chat_service, "history", lambda limit=60: pytest.fail("resume must not read history")
    )
    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)
    chat_service.run_chat_turn("continua")
    assert "Últimos turnos" not in str(seen["prompt"])


def test_is_busy_ignores_a_lock_left_by_a_dead_process(chat_dirs: Path) -> None:
    """A hard kill mid-turn must not brick the website chat forever.

    The lock file survives a SIGKILL (the releasing ``finally`` never runs), so
    checking existence alone would 409 every web message and every /reset until
    someone deleted the file by hand.
    """
    lock = chat_service._chat_lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(
        json.dumps({"pid": 999_999, "pid_identity": "1", "started_at": "x"}), encoding="utf-8"
    )

    assert lock.exists()
    assert chat_service.is_busy() is False

    # A live holder still reports busy.
    assert analysis_runner._try_acquire_lock_file(lock)
    assert chat_service.is_busy() is True
    analysis_runner._release_lock_file(lock)
