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
    monkeypatch.setattr(chat_service, "_AUX_WORKSPACE", tmp_path / "aux_ws")
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
    assert "/api/cards" in orders
    assert "PAGAMENTO DE FATURA NÃO É GASTO" in orders
    assert '"installments"' in orders


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


def test_a_drained_turn_persists_both_sides(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch, session
) -> None:
    """D7: callers go through enqueue() because it is what writes the
    transcript — the client's row and the reply the worker settles."""
    from sqlmodel import select

    from app.models.chat import ChatChannel, ChatMessage, ChatRole, ChatTurnStatus

    monkeypatch.setattr(chat_service, "engine", session.get_bind())
    monkeypatch.setattr(chat_service, "start_queue_worker", lambda: None)
    monkeypatch.setattr(analysis_runner, "_run_claude_step", lambda *a, **k: _step("resposta!"))

    chat_service.enqueue("quanto está o BTC hoje?", ChatChannel.WEB)
    chat_service._drain_once()

    rows = list(session.exec(select(ChatMessage).order_by(ChatMessage.created_at)).all())
    assert [r.role for r in rows] == [ChatRole.USER, ChatRole.ASSISTANT]
    assert all(r.channel == ChatChannel.WEB for r in rows)
    assert rows[0].content == "quanto está o BTC hoje?"
    assert rows[1].content == "resposta!"
    assert rows[1].status == ChatTurnStatus.DONE
    assert rows[1].model  # the route taken is recorded on the message


def test_a_crashed_turn_is_recorded_on_the_pending_row(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch, session
) -> None:
    from sqlmodel import select

    from app.models.chat import ChatChannel, ChatMessage, ChatRole, ChatTurnStatus

    monkeypatch.setattr(chat_service, "engine", session.get_bind())
    monkeypatch.setattr(chat_service, "start_queue_worker", lambda: None)

    def fake_step(*_a: object, **_k: object) -> StepResult:
        raise RuntimeError("cli exploded")

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)
    chat_service.enqueue("oi, tudo bem?", ChatChannel.WEB)
    chat_service._drain_once()

    rows = list(session.exec(select(ChatMessage).order_by(ChatMessage.created_at)).all())
    assert rows[-1].role == ChatRole.ASSISTANT
    assert rows[-1].status == ChatTurnStatus.FAILED
    assert "cli exploded" in rows[-1].content


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
    # Assert the ACTION the user must take, not a particular noun: the copy
    # covers both an expired login and a revoked plan, so it no longer says
    # "autenticação" in so many words.
    assert "renove o login" in message
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


def test_web_turn_completion_fires_a_push(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch, session
) -> None:
    """An opus/max reply takes minutes; a turn asked through the SITE must buzz
    the phone when it lands. Other channels (old Telegram rows) never push."""
    from app.models.chat import ChatChannel
    from app.services import webpush_service

    monkeypatch.setattr(chat_service, "engine", session.get_bind())
    monkeypatch.setattr(analysis_runner, "_run_claude_step", lambda *a, **k: _step("pronto!"))
    pushed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        webpush_service,
        "notify",
        lambda title, body, url="/consultor": pushed.append((title, body)),
    )

    monkeypatch.setattr(chat_service, "start_queue_worker", lambda: None)
    chat_service.enqueue("como está o mês?", ChatChannel.WEB)
    chat_service._drain_once()
    assert len(pushed) == 1
    assert "respondeu" in pushed[0][0].lower()
    assert pushed[0][1] == "pronto!"

    pushed.clear()
    chat_service.enqueue("e agora?", ChatChannel.TELEGRAM)
    chat_service._drain_once()
    assert pushed == []


def test_attachment_group_becomes_one_turn(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Up to 3 files ride in ONE message: a receipt front and back is one
    purchase, and the prompt must tell the model to read them as a set."""
    from app.models.chat import ChatChannel

    captured: dict[str, object] = {}

    def fake_start(prompt: str, channel, *, display=None) -> None:  # noqa: ANN001
        captured.update(prompt=prompt, display=display)

    monkeypatch.setattr(chat_service, "start_turn", fake_start)
    front = tmp_path / "20260806T1_frente.jpg"
    back = tmp_path / "20260806T1_verso.jpg"
    front.write_bytes(b"x")
    back.write_bytes(b"x")

    chat_service.start_attachments_turn([front, back], "cupom do mercado", ChatChannel.WEB)
    prompt = str(captured["prompt"])
    assert str(front) in prompt and str(back) in prompt
    assert "CONJUNTO" in prompt
    assert "resuma e registre" not in prompt
    assert "concilie" in prompt
    assert str(captured["display"]).startswith("📎 frente.jpg · verso.jpg")

    with pytest.raises(chat_service.ChatUnavailableError):
        chat_service.start_attachments_turn([front] * 4, "", ChatChannel.WEB)


def test_media_turn_text_tells_model_to_reconcile_invoices(tmp_path: Path) -> None:
    """A single-file attachment turn must never ask the model to book the
    invoice: it must reconcile against cashflow and skip the invoice payment."""
    prompt = chat_service.media_turn_text(
        "arquivo", tmp_path / "fatura.pdf", "fatura do cartão", "pelo site"
    )
    assert "resuma e registre" not in prompt
    assert "concilie" in prompt


# ── Durable queue: several messages in a row, and coming back after a limit ───


def test_enqueue_records_the_job_without_running_it(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch, session
) -> None:
    from sqlmodel import select

    from app.models.chat import ChatChannel, ChatMessage, ChatRole, ChatTurnStatus

    monkeypatch.setattr(chat_service, "engine", session.get_bind())
    monkeypatch.setattr(chat_service, "start_queue_worker", lambda: None)

    chat_service.enqueue("gastei 42 no mercado", ChatChannel.WEB)

    rows = list(session.exec(select(ChatMessage).order_by(ChatMessage.created_at)).all())
    assert [r.role for r in rows] == [ChatRole.USER, ChatRole.ASSISTANT]
    assert rows[1].status == ChatTurnStatus.QUEUED
    # What the model receives is stored apart from what the client reads.
    assert rows[1].prompt == "gastei 42 no mercado"
    assert chat_service.queued_count() == 1


def test_queue_answers_messages_in_the_order_they_were_sent(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch, session
) -> None:
    """The client may fire three messages without waiting; the consultant
    reads them one at a time, in order, on the same chained session."""
    from sqlmodel import select

    from app.models.chat import ChatChannel, ChatMessage, ChatRole, ChatTurnStatus

    monkeypatch.setattr(chat_service, "engine", session.get_bind())
    monkeypatch.setattr(chat_service, "start_queue_worker", lambda: None)
    seen: list[str] = []

    def fake_step(prompt: str, *_a: object, **_k: object) -> StepResult:
        # Chained turns carry a date stamp before the text; keep just the message.
        seen.append(prompt.rsplit("Mensagem do cliente: ", 1)[-1].split("] ")[-1])
        return _step(f"ok {len(seen)}")

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)

    for text in ("gastei 42 no mercado", "e 15 no uber", "quanto sobrou?"):
        chat_service.enqueue(text, ChatChannel.WEB)
    for _ in range(3):
        chat_service._drain_once()

    assert seen == ["gastei 42 no mercado", "e 15 no uber", "quanto sobrou?"]
    replies = [
        r.content
        for r in session.exec(select(ChatMessage).order_by(ChatMessage.created_at)).all()
        if r.role == ChatRole.ASSISTANT
    ]
    assert replies == ["ok 1", "ok 2", "ok 3"]
    assert chat_service.queued_count() == 0
    assert all(
        r.status == ChatTurnStatus.DONE
        for r in session.exec(select(ChatMessage)).all()
        if r.role == ChatRole.ASSISTANT
    )


def test_usage_limit_keeps_the_job_and_reschedules_it(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch, session
) -> None:
    """The whole point: a limit must not throw the message away."""
    from sqlmodel import select

    from app.models.chat import ChatChannel, ChatMessage, ChatRole, ChatTurnStatus

    monkeypatch.setattr(chat_service, "engine", session.get_bind())
    monkeypatch.setattr(chat_service, "start_queue_worker", lambda: None)
    monkeypatch.setattr(
        analysis_runner,
        "_run_claude_step",
        lambda *a, **k: (_ for _ in ()).throw(LimitError("usage limit reached, resets 4am")),
    )

    chat_service.enqueue("registra 42 no mercado", ChatChannel.WEB)
    chat_service._drain_once()

    job = [
        r
        for r in session.exec(select(ChatMessage).order_by(ChatMessage.created_at)).all()
        if r.role == ChatRole.ASSISTANT
    ][-1]
    session.refresh(job)
    assert job.status == ChatTurnStatus.QUEUED  # still ours, not discarded
    assert job.attempts == 1
    assert job.retry_kind == "limit"
    assert job.run_after is not None
    assert job.prompt == "registra 42 no mercado"  # the message survived intact
    assert "não precisa reenviar" in job.content


def test_the_consultant_comes_back_by_himself_when_credit_returns(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch, session
) -> None:
    from datetime import UTC, datetime

    from sqlmodel import select

    from app.models.chat import ChatChannel, ChatMessage, ChatRole, ChatTurnStatus

    monkeypatch.setattr(chat_service, "engine", session.get_bind())
    monkeypatch.setattr(chat_service, "start_queue_worker", lambda: None)
    calls = {"n": 0}

    def flaky(prompt: str, *_a: object, **_k: object) -> StepResult:
        calls["n"] += 1
        if calls["n"] == 1:
            raise LimitError("usage limit reached, resets 4am")
        assert "[RETOMADA AUTOMÁTICA]" in prompt  # guards against a double write
        return _step("registrado!")

    monkeypatch.setattr(analysis_runner, "_run_claude_step", flaky)

    chat_service.enqueue("registra 42 no mercado", ChatChannel.WEB)
    chat_service._drain_once()  # hits the limit, defers

    job = [
        r
        for r in session.exec(select(ChatMessage).order_by(ChatMessage.created_at)).all()
        if r.role == ChatRole.ASSISTANT
    ][-1]
    # The window reopened: nothing else needed to happen, no resend.
    job.run_after = datetime.now(UTC)
    session.add(job)
    session.commit()

    chat_service._drain_once()
    session.refresh(job)
    assert job.status == ChatTurnStatus.DONE
    assert job.content == "registrado!"
    assert calls["n"] == 2


def test_queue_does_not_jump_ahead_of_a_waiting_message(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch, session
) -> None:
    """Strict FIFO: answering the second message while the first waits out the
    limit would reorder the conversation, and it would hit the same wall."""
    from app.models.chat import ChatChannel, ChatTurnStatus

    monkeypatch.setattr(chat_service, "engine", session.get_bind())
    monkeypatch.setattr(chat_service, "start_queue_worker", lambda: None)
    monkeypatch.setattr(
        analysis_runner,
        "_run_claude_step",
        lambda *a, **k: (_ for _ in ()).throw(LimitError("usage limit reached, resets 4am")),
    )

    chat_service.enqueue("primeira", ChatChannel.WEB)
    chat_service.enqueue("segunda", ChatChannel.WEB)
    chat_service._drain_once()  # first one defers

    assert chat_service._claim_next_job() is None  # the second one waits its turn
    assert chat_service._seconds_until_due() > 1
    assert chat_service.queued_count() == 2
    assert chat_service.has_pending_turns() is True
    del ChatTurnStatus


def test_auth_failure_is_not_retried(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch, session
) -> None:
    """Renewing the login is a human's job — queueing it forever would hide it."""
    from sqlmodel import select

    from app.models.chat import ChatChannel, ChatMessage, ChatRole, ChatTurnStatus

    monkeypatch.setattr(chat_service, "engine", session.get_bind())
    monkeypatch.setattr(chat_service, "start_queue_worker", lambda: None)
    monkeypatch.setattr(
        analysis_runner,
        "_run_claude_step",
        lambda *a, **k: (_ for _ in ()).throw(AuthError("OAuth token expired")),
    )

    chat_service.enqueue("oi", ChatChannel.WEB)
    chat_service._drain_once()

    job = [
        r
        for r in session.exec(select(ChatMessage).order_by(ChatMessage.created_at)).all()
        if r.role == ChatRole.ASSISTANT
    ][-1]
    assert job.status == ChatTurnStatus.FAILED
    assert chat_service.queued_count() == 0


def test_restart_puts_the_interrupted_turn_back_in_the_queue(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch, session
) -> None:
    from sqlmodel import select

    from app.models.chat import ChatChannel, ChatMessage, ChatRole, ChatTurnStatus

    monkeypatch.setattr(chat_service, "engine", session.get_bind())
    monkeypatch.setattr(chat_service, "start_queue_worker", lambda: None)

    chat_service.enqueue("registra 42 no mercado", ChatChannel.WEB)
    claimed = chat_service._claim_next_job()
    assert claimed is not None  # now RUNNING, and the process "dies" here

    assert chat_service.reconcile_orphan_turns() == 1

    job = [
        r
        for r in session.exec(select(ChatMessage).order_by(ChatMessage.created_at)).all()
        if r.role == ChatRole.ASSISTANT
    ][-1]
    session.refresh(job)
    assert job.status == ChatTurnStatus.QUEUED
    assert job.prompt == "registra 42 no mercado"
    assert job.attempts == 1


# ── Cost: what keeps a chained session from getting expensive ────────────────


def test_session_rotates_when_context_gets_big(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Size, not age, is what makes a session expensive: every later turn
    re-reads the whole context on every iteration. Measured on the real chat,
    it crossed 200k tokens by turn 14 — the turn counter never saw it."""
    chat_service._ensure_chat_workspace()
    chat_service._save_state("sess-fat", 3, settings.chat_max_context_tokens + 1)
    seen: dict[str, object] = {}

    def fake_step(prompt: str, *, resume_session_id, **kwargs) -> StepResult:
        seen["resume"] = resume_session_id
        return _step(session_id="sess-new")

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)
    chat_service.run_chat_turn("oi")
    assert seen["resume"] is None  # rotated on size, well before chat_max_turns
    assert chat_service._load_state()["turns"] == 1


def test_small_context_keeps_resuming(chat_dirs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chat_service._ensure_chat_workspace()
    chat_service._save_state("sess-1", 3, 10_000)
    seen: dict[str, object] = {}

    def fake_step(prompt: str, *, resume_session_id, **kwargs) -> StepResult:
        seen["resume"] = resume_session_id
        return StepResult(
            label="",
            result="ok",
            cost_usd=0.01,
            duration_s=1.0,
            session_id="sess-1",
            context_tokens=55_000,
        )

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)
    chat_service.run_chat_turn("e a PETR4?")
    assert seen["resume"] == "sess-1"
    # The measured size rides into the state so the NEXT turn can decide.
    assert chat_service._load_state()["context_tokens"] == 55_000


def _fake_inbox_file(name: str = "20260918T1_cupom.png") -> Path:
    inbox = chat_service.CHAT_WORKSPACE / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / name
    path.write_bytes(b"\x89PNG fake")
    return path


def test_attachment_is_transcribed_outside_the_chained_session(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The photo's bytes must never enter the chained session: a throwaway
    session reads it once and only the text travels on."""
    chat_service._ensure_chat_workspace()
    path = _fake_inbox_file()
    calls: list[dict[str, object]] = []

    def fake_step(prompt: str, *, resume_session_id, **kwargs) -> StepResult:
        calls.append({"prompt": prompt, "resume": resume_session_id, **kwargs})
        if kwargs.get("model") == settings.chat_vision_model:
            return StepResult(
                label="",
                result="Cupom fiscal — MERCADO X | 18/09 | R$ 42,90",
                cost_usd=0.02,
                duration_s=3.0,
                session_id="vision-1",
            )
        return _step(result="registrei", session_id="sess-1")

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)
    reply, _route, step = chat_service.run_chat_turn(
        chat_service.media_turn_text("imagem", path, "cupom", "pelo site")
    )

    assert reply == "registrei"
    vision, turn = calls[0], calls[1]
    assert vision["resume"] is None  # disposable: never resumes the conversation
    assert vision["cwd"] == chat_service._AUX_WORKSPACE  # and no MCP servers boot
    assert str(path) in str(vision["prompt"])

    consultant_prompt = str(turn["prompt"])
    assert "[[ANEXOS:" not in consultant_prompt  # the marker is gone
    assert "R$ 42,90" in consultant_prompt  # replaced by what the file says
    # Both calls are what this answer cost the plan.
    assert step.cost_usd == 0.03


def test_transcription_failure_falls_back_to_reading_the_file(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Losing the receipt the client just photographed is worse than paying
    for it in context."""
    from app.services.analysis_runner import AnalysisError

    chat_service._ensure_chat_workspace()
    path = _fake_inbox_file()
    prompts: list[str] = []

    def fake_step(prompt: str, *, resume_session_id, **kwargs) -> StepResult:
        prompts.append(prompt)
        if kwargs.get("model") == settings.chat_vision_model:
            raise AnalysisError("vision step blew up")
        return _step(result="li eu mesmo")

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)
    reply, _route, _step_result = chat_service.run_chat_turn(
        chat_service.media_turn_text("imagem", path, "", "pelo site")
    )
    assert reply == "li eu mesmo"
    assert "Leia você mesmo" in prompts[-1] and str(path) in prompts[-1]


def test_marker_only_reads_files_inside_the_inbox(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The prompt comes from the database and client messages are free text:
    a hand-typed marker must not turn the reader loose on the filesystem."""
    chat_service._ensure_chat_workspace()
    secret = chat_dirs / "segredo.env"
    secret.write_text("TOKEN=abc", encoding="utf-8")
    calls: list[dict[str, object]] = []

    def fake_step(prompt: str, *, resume_session_id, **kwargs) -> StepResult:
        calls.append({"prompt": prompt, "model": kwargs.get("model")})
        return _step()

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)
    chat_service.run_chat_turn(f"olha isso [[ANEXOS:{secret}]]")
    assert len(calls) == 1  # no transcription step ran at all
    assert calls[0]["model"] != settings.chat_vision_model
    assert "TOKEN=abc" not in str(calls[0]["prompt"])
    assert "não está mais disponível" in str(calls[0]["prompt"])


def test_transcription_is_cached_across_a_retried_turn(
    chat_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A turn that died on a usage limit comes back with the same prompt: the
    photo must not be paid for twice on the way back."""
    chat_service._ensure_chat_workspace()
    path = _fake_inbox_file()
    vision_calls = 0

    def fake_step(prompt: str, *, resume_session_id, **kwargs) -> StepResult:
        nonlocal vision_calls
        if kwargs.get("model") == settings.chat_vision_model:
            vision_calls += 1
            return StepResult(
                label="", result="Cupom | 18/09 | R$ 42,90", cost_usd=0.02, duration_s=3.0
            )
        return _step()

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake_step)
    prompt = chat_service.media_turn_text("imagem", path, "", "pelo site")
    _reply, _route, first = chat_service.run_chat_turn(prompt)
    _reply, _route, second = chat_service.run_chat_turn(prompt)

    assert vision_calls == 1
    assert first.cost_usd == 0.03  # turn + transcription
    assert second.cost_usd == 0.01  # turn only: the transcription was cached


def test_reply_keeps_the_answer_written_before_the_memory_edit() -> None:
    answer = "Opa, para um pouco. Você guardou 80% do que ganhou em setembro. " * 3
    step = _step(result="Tô aqui. 👍")
    step.texts = [answer, "Tô aqui. 👍"]
    assert chat_service._reply_text(step) == f"{answer}\n\nTô aqui. 👍"
    # A short preamble before tools ("deixa eu ver") never replaces the answer.
    step = _step(result="resposta completa e longa")
    step.texts = ["deixa eu ver", "resposta completa e longa"]
    assert chat_service._reply_text(step) == "resposta completa e longa"


def test_cold_fat_session_rotates_but_cold_thin_one_resumes() -> None:
    from datetime import UTC, datetime, timedelta

    old = (datetime.now(UTC) - timedelta(seconds=chat_service._CACHE_TTL_S + 60)).isoformat()
    fresh = datetime.now(UTC).isoformat()
    fat = settings.chat_max_context_tokens // 2
    assert chat_service._should_rotate("s", 3, fat, old)
    assert not chat_service._should_rotate("s", 3, fat, fresh)
    assert not chat_service._should_rotate("s", 3, fat - 1, old)
    assert not chat_service._should_rotate("s", 3, fat, None)
    naive_old = old.replace("+00:00", "")
    assert chat_service._should_rotate("s", 3, fat, naive_old)  # no TypeError
