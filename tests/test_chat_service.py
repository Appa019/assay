import json
from pathlib import Path

import pytest

from app.config import settings
from app.services import analysis_runner, chat_service
from app.services.analysis_runner import (
    AuthError,
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


def test_chat_mcp_profile_is_lean(chat_dirs: Path) -> None:
    """Chat turns boot every configured MCP server as a subprocess on the Pi;
    the chat profile must keep only the financial-data set."""
    ws = chat_service._ensure_chat_workspace()
    servers = set(json.loads((ws / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"])
    assert {"coingecko", "yahoo-finance", "defillama", "exa", "fetch", "memory"} <= servers
    assert not {"playwright", "filesystem", "context7", "sequential-thinking"} & servers


def test_committee_baseline_has_no_time_or_git_servers() -> None:
    servers = analysis_runner._baseline_mcp_servers()
    assert "time" not in servers and "git" not in servers  # Bash covers both
    assert "playwright" in servers  # the committee keeps the research stack


def test_first_turn_starts_fresh_and_persists_session(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_step(prompt: str, *, resume_session_id, **kwargs) -> StepResult:
        seen["prompt"] = prompt
        seen["resume"] = resume_session_id
        return _step()

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)
    reply, route, step = chat_service.run_chat_turn("quanto está o BTC?")
    assert reply == "olá!"
    assert route.model  # the router always picks something
    assert step.cost_usd == 0.01  # the step result rides along for persistence

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
    # Keep the restart deterministic: no transcript tail and no rotation
    # summary, whatever the local dev database happens to contain.
    monkeypatch.setattr(chat_service, "history", lambda limit=60: [])
    calls: list[str | None] = []

    def fake_step(prompt: str, *, resume_session_id, **kwargs) -> StepResult:
        calls.append(resume_session_id)
        if resume_session_id is not None:
            raise SessionNotFoundError("no conversation found")
        return _step(result="recomecei", session_id="sess-new")

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)
    assert chat_service.run_chat_turn("oi")[0] == "recomecei"
    assert calls == ["sess-gone", None]
    state = chat_service._load_state()
    assert state["session_id"] == "sess-new"
    # The reborn session must start counting from zero — inheriting the dead
    # session's counter would rotate it again on the very next message.
    assert state["turns"] == 1


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


def test_rotation_builds_structured_summary(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A long conversation being rotated gets a structured summary in the new
    session's first prompt — the truncated verbatim tail alone drops decisions
    and exact figures from earlier in the session."""
    from app.models.chat import ChatChannel, ChatMessage, ChatRole, ChatTurnStatus

    fake_history = [
        ChatMessage(
            role=ChatRole.USER if i % 2 == 0 else ChatRole.ASSISTANT,
            content=f"mensagem {i} sobre a carteira",
            channel=ChatChannel.TELEGRAM,
            status=ChatTurnStatus.DONE,
        )
        for i in range(14)
    ]
    monkeypatch.setattr(chat_service, "history", lambda limit=60: fake_history)
    chat_service._ensure_chat_workspace()
    chat_service._save_state("sess-old", settings.chat_max_turns)
    prompts: list[str] = []

    def fake_step(prompt: str, *, resume_session_id, **kwargs) -> StepResult:
        prompts.append(prompt)
        if prompt.startswith("Você vai receber a transcrição"):
            return _step(result="## Números exatos\n- PETR4 a R$ 38,20")
        return _step(session_id="sess-new")

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)
    chat_service.run_chat_turn("bora continuar")
    turn_prompt = prompts[-1]
    assert "Resumo do estado da conversa" in turn_prompt
    assert "PETR4 a R$ 38,20" in turn_prompt


def test_resumed_turn_carries_no_transcript_block(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat_service._ensure_chat_workspace()
    chat_service._save_state("sess-1", 3)
    seen: dict[str, object] = {}

    def fake_step(prompt: str, *, resume_session_id, **kwargs) -> StepResult:
        seen["prompt"] = prompt
        return _step(session_id="sess-1")

    # History may be read for triage context, but a resumed turn's PROMPT must
    # not re-inject the transcript — the session already carries it.
    monkeypatch.setattr(chat_service, "history", lambda limit=60: [])
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


def test_auth_failure_tells_the_truth(chat_dirs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An expired CLI login is NOT transient: the reply must say the login
    needs renewing instead of asking the user to resend the message."""

    def fake_step(prompt: str, *, resume_session_id, **kwargs) -> StepResult:
        raise AuthError("Failed to authenticate: OAuth session expired")

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)
    with pytest.raises(chat_service.ChatUnavailableError) as excinfo:
        chat_service.run_chat_turn("oi")
    message = str(excinfo.value)
    assert "autenticação" in message
    assert "manda a mensagem de novo" not in message


def test_reset_clears_the_visible_history(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch, session
) -> None:
    """ "Nova sessão" must restart the SCREEN blank: history() hides everything
    before the reset while the rows stay in chat_message (cost/tier stats)."""
    from datetime import UTC, datetime, timedelta

    from sqlmodel import select

    from app.models.chat import ChatChannel, ChatMessage, ChatRole, ChatTurnStatus

    monkeypatch.setattr(chat_service, "engine", session.get_bind())
    before = datetime.now(UTC) - timedelta(minutes=1)
    for role, content in ((ChatRole.USER, "oi"), (ChatRole.ASSISTANT, "olá!")):
        session.add(
            ChatMessage(
                role=role,
                content=content,
                channel=ChatChannel.WEB,
                status=ChatTurnStatus.DONE,
                created_at=before,
            )
        )
    session.commit()
    assert len(chat_service.history()) == 2

    chat_service.reset_session()
    assert chat_service.history() == []

    session.add(
        ChatMessage(
            role=ChatRole.USER,
            content="recomeço",
            channel=ChatChannel.WEB,
            status=ChatTurnStatus.DONE,
            created_at=datetime.now(UTC) + timedelta(seconds=1),
        )
    )
    session.commit()
    assert [m.content for m in chat_service.history()] == ["recomeço"]
    # The old rows are hidden, not deleted.
    assert len(list(session.exec(select(ChatMessage)).all())) == 3
