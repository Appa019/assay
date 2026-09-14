"""The chat endpoint as the phone sees it: fire messages back to back while
the consultant is still answering, and watch the queue drain in order."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.services import analysis_runner, chat_service
from app.services.analysis_runner import StepResult


@pytest.fixture()
def client(
    session: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[TestClient]:
    monkeypatch.setattr(chat_service, "engine", session.get_bind())
    monkeypatch.setattr(chat_service, "CHAT_WORKSPACE", tmp_path / "chat_ws")
    monkeypatch.setattr(analysis_runner, "_RUN_LOCK_DIR", tmp_path / "locks")
    monkeypatch.setattr(analysis_runner, "_TRANSCRIPT_DIR", tmp_path / "transcripts")
    # The worker thread would race the assertions; each test drains by hand.
    monkeypatch.setattr(chat_service, "start_queue_worker", lambda: None)
    yield TestClient(app)


def test_three_messages_in_a_row_are_all_accepted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No 409 anymore: holding a thought because he is mid-answer was the bug."""
    monkeypatch.setattr(
        analysis_runner,
        "_run_claude_step",
        lambda *a, **k: StepResult(
            label="", result="ok", cost_usd=0.01, duration_s=1.0, session_id="s1"
        ),
    )
    for text in ("gastei 42 no mercado", "e 15 no uber", "quanto sobrou?"):
        assert client.post("/api/chat", json={"text": text}).status_code == 202

    state = client.get("/api/chat").json()
    assert state["queued"] == 3
    assert [m["content"] for m in state["messages"] if m["role"] == "user"] == [
        "gastei 42 no mercado",
        "e 15 no uber",
        "quanto sobrou?",
    ]
    assert all(m["status"] == "queued" for m in state["messages"] if m["role"] == "assistant")

    for _ in range(3):
        chat_service._drain_once()

    state = client.get("/api/chat").json()
    assert state["queued"] == 0
    assert [m["status"] for m in state["messages"] if m["role"] == "assistant"] == [
        "done",
        "done",
        "done",
    ]


def test_reset_refuses_to_drop_a_queued_message(client: TestClient) -> None:
    assert client.post("/api/chat", json={"text": "registra 42 no mercado"}).status_code == 202
    assert client.post("/api/chat/reset").status_code == 409
