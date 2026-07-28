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
    reply = chat_service.run_chat_turn("quanto está o BTC?")
    assert reply == "olá!"
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
    assert chat_service.run_chat_turn("e a PETR4?") == "resumido"
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
    assert chat_service.run_chat_turn("oi") == "recomecei"
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


def test_reset_session_drops_state(chat_dirs: Path) -> None:
    chat_service._ensure_chat_workspace()
    chat_service._save_state("sess-1", 5)
    chat_service.reset_session()
    assert chat_service._load_state() == {}
