import json
import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlmodel import Session

from app.models.contribution import Contribution, ContributionStatus
from app.services import analysis_runner as ar

# --- _seconds_until_reset ------------------------------------------------------


def test_reset_parse_future_same_day(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now()
    target = now + timedelta(hours=2)
    suffix = "am" if target.hour < 12 else "pm"
    hour12 = target.hour % 12 or 12
    msg = f"usage limit reached, resets {hour12}:{target.minute:02d}{suffix}"
    wait = ar._seconds_until_reset(msg)
    assert wait is not None
    assert 0 < wait <= 2 * 3600 + 120


def test_reset_parse_rolls_past_midnight() -> None:
    now = datetime.now()
    past = now - timedelta(hours=1)
    suffix = "am" if past.hour < 12 else "pm"
    hour12 = past.hour % 12 or 12
    wait = ar._seconds_until_reset(f"resets {hour12}:{past.minute:02d}{suffix}")
    # 23h away → capped at 6h, never a sub-minute fallback loop.
    assert wait == 6 * 3600


def test_reset_parse_absent() -> None:
    assert ar._seconds_until_reset("overloaded, try again later") is None


# --- run locks -----------------------------------------------------------------


def test_lock_acquire_release(isolated_runner_dirs: Path) -> None:
    from uuid import uuid4

    cid = uuid4()
    assert ar._acquire_run_lock(cid)
    assert ar.is_run_active(cid)
    assert not ar._acquire_run_lock(cid)  # second holder refused
    ar._release_run_lock(cid)
    assert not ar.is_run_active(cid)
    assert ar._acquire_run_lock(cid)  # reusable after release
    ar._release_run_lock(cid)


def test_stale_lock_from_dead_pid_is_reclaimed(isolated_runner_dirs: Path) -> None:
    from uuid import uuid4

    cid = uuid4()
    path = ar._lock_path(cid)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A pid that (almost certainly) doesn't exist.
    path.write_text(json.dumps({"pid": 2**22 - 3, "started_at": "2020-01-01T00:00:00+00:00"}))
    assert ar._acquire_run_lock(cid)
    data = json.loads(path.read_text())
    assert data["pid"] == os.getpid()
    ar._release_run_lock(cid)


def test_live_lock_with_wrong_identity_is_stale(isolated_runner_dirs: Path) -> None:
    from uuid import uuid4

    cid = uuid4()
    path = ar._lock_path(cid)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Live pid (ours) but a fabricated identity → PID-reuse case → stale.
    path.write_text(json.dumps({"pid": os.getpid(), "pid_identity": "not-the-real-starttime"}))
    assert not ar._lock_is_active(path)
    assert ar._acquire_run_lock(cid)
    ar._release_run_lock(cid)


# --- retry counters ------------------------------------------------------------


def _resilient(monkeypatch: pytest.MonkeyPatch, outcomes: list[BaseException | str]) -> str:
    """Drive _run_step_resilient through a scripted sequence of outcomes."""
    calls = iter(outcomes)

    def fake_step(*_args, **_kwargs) -> ar.StepResult:
        outcome = next(calls)
        if isinstance(outcome, BaseException):
            raise outcome
        return ar.StepResult(label="", result=outcome, cost_usd=0.0, duration_s=0.1)

    monkeypatch.setattr(ar, "_run_claude_step", fake_step)
    result = ar._run_step_resilient(
        "prompt",
        resume_session_id=None,
        model="opus",
        effort="max",
        timeout=10,
        cwd=Path("."),
        on_event=None,
        step=1,
        total=1,
        title="t",
    )
    return result.result


def test_limit_waits_do_not_consume_transient_budget(
    monkeypatch: pytest.MonkeyPatch, isolated_runner_dirs: Path
) -> None:
    # 4 limit hits (more than the transient budget of 3) then one transient
    # blip, then success — must survive because the counters are independent.
    outcomes: list[BaseException | str] = [
        ar.LimitError("usage limit"),
        ar.LimitError("usage limit"),
        ar.LimitError("usage limit"),
        ar.LimitError("usage limit"),
        ar.RetryableError("network blip"),
        "ok",
    ]
    assert _resilient(monkeypatch, outcomes) == "ok"


def test_transient_budget_exhausts(
    monkeypatch: pytest.MonkeyPatch, isolated_runner_dirs: Path
) -> None:
    outcomes: list[BaseException | str] = [ar.RetryableError("blip")] * 4 + ["never"]
    with pytest.raises(ar.RetryableError):
        _resilient(monkeypatch, outcomes)


# --- run_chain with a scripted CLI --------------------------------------------


def test_run_chain_chains_session_and_persists(
    monkeypatch: pytest.MonkeyPatch, isolated_runner_dirs: Path
) -> None:
    seen_resumes: list[str | None] = []

    def fake_step(_prompt: str, *, resume_session_id, **_kw) -> ar.StepResult:
        seen_resumes.append(resume_session_id)
        return ar.StepResult(
            label="",
            result=f"r{len(seen_resumes)}",
            cost_usd=1.0,
            duration_s=2.0,
            session_id="sess-1",
        )

    monkeypatch.setattr(ar, "_run_claude_step", fake_step)
    persisted: list[tuple[int, str]] = []
    saved_sessions: list[str] = []

    summary = ar.run_chain(
        [("a", "p1"), ("b", "p2")],
        run_id="test",
        persist=lambda i, t, r: persisted.append((i, r.result)),
        on_session_id=saved_sessions.append,
    )
    assert seen_resumes == [None, "sess-1"]  # step 2 resumed step 1's session
    assert summary.final_summary == "r2"
    assert summary.total_cost_usd == 2.0
    assert persisted == [(0, "r1"), (1, "r2")]
    assert saved_sessions == ["sess-1"]


def test_run_chain_adopts_rotated_session_id(
    monkeypatch: pytest.MonkeyPatch, isolated_runner_dirs: Path
) -> None:
    ids = iter(["sess-1", "sess-2"])

    def fake_step(_prompt: str, *, resume_session_id, **_kw) -> ar.StepResult:
        return ar.StepResult(label="", result="ok", cost_usd=0, duration_s=0, session_id=next(ids))

    monkeypatch.setattr(ar, "_run_claude_step", fake_step)
    saved: list[str] = []
    summary = ar.run_chain([("a", "p1"), ("b", "p2")], run_id="t", on_session_id=saved.append)
    assert summary.session_id == "sess-2"
    assert saved == ["sess-1", "sess-2"]


def test_run_chain_refuses_second_global_run(
    monkeypatch: pytest.MonkeyPatch, isolated_runner_dirs: Path
) -> None:
    # Simulate another live process holding the global lock.
    ar._RUN_LOCK_DIR.mkdir(parents=True, exist_ok=True)
    assert ar._try_acquire_lock_file(ar._RUN_LOCK_DIR / ar._GLOBAL_LOCK_NAME)
    other_pid_lock = ar._RUN_LOCK_DIR / ar._GLOBAL_LOCK_NAME
    monkeypatch.setattr(ar, "_run_claude_step", lambda *a, **k: pytest.fail("must not run"))
    # Same process holds it → helper refuses (we treat self as active holder).
    with pytest.raises(ar.AnalysisError):
        ar.run_chain([("a", "p")], run_id="t2")
    other_pid_lock.unlink()


# --- workspace -----------------------------------------------------------------


def test_ensure_workspace_seeds_files(isolated_runner_dirs: Path) -> None:
    ws = ar._ensure_workspace(30)
    assert (ws / "CLAUDE.md").exists()
    assert (ws / "MEMORY.md").exists()
    assert (ws / ".mcp.json").exists()
    assert (ws / "out").is_dir()
    assert (ws / "notes").is_dir()
    orders = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "30 dias POR LOTE" in orders
    assert "anti-manipulação" in orders  # prompt-injection hardening present
    config = json.loads((ws / ".mcp.json").read_text(encoding="utf-8"))
    assert "yahoo-finance" in config["mcpServers"]


def test_agent_env_denylist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("SOME_HARMLESS_VAR", "ok")
    env = ar._agent_subprocess_env()
    assert "TELEGRAM_BOT_TOKEN" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert env["SOME_HARMLESS_VAR"] == "ok"


# --- pending orders context + final-block validator ----------------------------


def test_pending_orders_context_lists_only_open_orders(session: Session) -> None:
    from app.models.asset import AssetClass
    from app.models.order import Order, OrderStatus

    contribution = Contribution(amount_brl=Decimal("5000"))
    session.add(contribution)
    session.commit()
    session.refresh(contribution)
    session.add(
        Order(
            contribution_id=contribution.id,
            ticker="PETR4",
            asset_class=AssetClass.STOCKS,
            amount_brl=Decimal("1500"),
        )
    )
    session.add(
        Order(
            contribution_id=contribution.id,
            ticker="BTC",
            asset_class=AssetClass.CRYPTO,
            amount_brl=Decimal("2000"),
            status=OrderStatus.EXECUTED,
        )
    )
    session.commit()

    block = ar._pending_orders_context(session)
    assert "PETR4" in block and "1,500.00" in block
    assert "BTC" not in block  # executed — no longer open
    assert "NÃO re-recomende" in block


def test_pending_orders_context_empty_without_orders(session: Session) -> None:
    assert ar._pending_orders_context(session) == ""


_GOOD_CLOSE = (
    "📋 ONDE INVESTIR\n\n---\n"
    '```json\n{"orders": [{"ticker": "PETR4", "classe": "acoes_b3", "valor_brl": 1000}]}\n```\n'
)
_DRIFTED_CLOSE = (
    "📋 ONDE INVESTIR\n\n---\n"
    '```json\n{"orders": [{"ticker": "PETR4", "classe": "acoes_b3", "valor_brl": 700}]}\n```\n'
)


def test_final_validator_passes_a_matching_block_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contribution = Contribution(amount_brl=Decimal("1000"))
    summary = ar.RunSummary(run_id="r1", session_id="sess", final_summary=_GOOD_CLOSE)
    monkeypatch.setattr(
        ar, "_run_step_resilient", lambda *a, **k: pytest.fail("must not run a fixup")
    )
    out = ar._validate_and_correct_final(
        summary, contribution, model="m", effort="e", timeout=60, on_event=None
    )
    assert out.final_summary == _GOOD_CLOSE


def test_final_validator_adopts_an_improved_fixup(monkeypatch: pytest.MonkeyPatch) -> None:
    """A drifted sheet triggers ONE in-session corrective turn; the corrected
    closing replaces the original when it parses at least as well."""
    contribution = Contribution(amount_brl=Decimal("1000"))
    summary = ar.RunSummary(run_id="r1", session_id="sess", final_summary=_DRIFTED_CLOSE)
    calls: list[str] = []

    def fake_fixup(prompt: str, **kwargs) -> ar.StepResult:
        calls.append(prompt)
        return ar.StepResult(
            label="", result=_GOOD_CLOSE, cost_usd=0.1, duration_s=2.0, session_id="sess"
        )

    monkeypatch.setattr(ar, "_run_step_resilient", fake_fixup)
    out = ar._validate_and_correct_final(
        summary, contribution, model="m", effort="e", timeout=60, on_event=None
    )
    assert len(calls) == 1
    assert "VALIDAÇÃO AUTOMÁTICA" in calls[0]
    assert out.final_summary == _GOOD_CLOSE
    assert out.steps[-1].label == "Correção do fechamento"


def test_final_validator_keeps_original_when_fixup_is_worse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contribution = Contribution(amount_brl=Decimal("1000"))
    summary = ar.RunSummary(run_id="r1", session_id="sess", final_summary=_DRIFTED_CLOSE)
    monkeypatch.setattr(
        ar,
        "_run_step_resilient",
        lambda *a, **k: ar.StepResult(
            label="", result="resposta sem bloco nenhum", cost_usd=0.1, duration_s=2.0
        ),
    )
    out = ar._validate_and_correct_final(
        summary, contribution, model="m", effort="e", timeout=60, on_event=None
    )
    assert out.final_summary == _DRIFTED_CLOSE  # never adopt a worse closing


# --- fresh restart wipes stale responses (A9 regression, contribution flow) ----


def test_run_analysis_wipes_stale_responses_when_the_session_is_gone(
    session: Session, isolated_runner_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resuming onto a dead Claude session must restart FRESH and wipe every
    response persisted by the dead session — otherwise the retry counts the
    old prefix as done and skips steps the new session never saw (A9)."""
    from app.models.contribution import ContributionPrompt

    contribution = Contribution(
        amount_brl=Decimal("1000"),
        status=ContributionStatus.READY,
        claude_session_id="dead-sess",
    )
    session.add(contribution)
    session.commit()
    session.refresh(contribution)
    for i in (1, 2):
        session.add(
            ContributionPrompt(
                contribution_id=contribution.id,
                prompt_order=i,
                prompt_key="macro",
                title=f"Reunião {i}",
                description="d",
                content=f"prompt {i}",
                response="resposta da sessão morta",
            )
        )
    session.commit()

    close = (
        "📋 ONDE INVESTIR\n\n---\n"
        '```json\n{"orders": [{"ticker": "PETR4", "classe": "acoes_b3", "valor_brl": 1000}]}\n```'
    )
    calls: list[str | None] = []

    def fake_step(
        prompt: str, *, resume_session_id: str | None, **_kwargs: object
    ) -> ar.StepResult:
        calls.append(resume_session_id)
        if resume_session_id == "dead-sess":
            raise ar.SessionNotFoundError("no conversation found")
        result = close if len(calls) == 4 else f"resp{len(calls)}"
        return ar.StepResult(
            label="", result=result, cost_usd=0.0, duration_s=1.0, session_id="new-sess"
        )

    monkeypatch.setattr(ar, "_run_claude_step", fake_step)
    ar.run_analysis(session, contribution.id, notify=False)

    session.refresh(contribution)
    prompts = sorted(contribution_prompts(session, contribution.id), key=lambda p: p.prompt_order)
    assert calls[0] == "dead-sess"  # tried the saved session first
    assert calls[1] is None  # then restarted fresh
    assert [p.response for p in prompts] == ["resp2", "resp3"]  # stale wiped, redone
    assert contribution.status == ContributionStatus.COMPLETED
    assert contribution.final_summary == close
    assert contribution.claude_session_id == "new-sess"


def contribution_prompts(session: Session, contribution_id) -> list:
    from sqlmodel import select

    from app.models.contribution import ContributionPrompt

    return list(
        session.exec(
            select(ContributionPrompt).where(ContributionPrompt.contribution_id == contribution_id)
        ).all()
    )


# --- pending_resumable_ids -----------------------------------------------------


def test_pending_resumable_covers_pre_step_failures_but_not_manual(
    session: Session, isolated_runner_dirs: Path
) -> None:
    """An automatic run that died BEFORE its first step (global-lock collision)
    leaves READY + run_attempts>0 + no session id — it must be resumable.
    A manual READY contribution (attempts=0) must never auto-run."""
    failed_pre_step = Contribution(
        amount_brl=Decimal("5000"),
        status=ContributionStatus.READY,
        run_attempts=1,
    )
    manual = Contribution(amount_brl=Decimal("1000"), status=ContributionStatus.READY)
    interrupted_mid_chain = Contribution(
        amount_brl=Decimal("2000"),
        status=ContributionStatus.READY,
        claude_session_id="sess-123",
        run_attempts=2,
    )
    gave_up = Contribution(
        amount_brl=Decimal("3000"),
        status=ContributionStatus.READY,
        run_attempts=99,  # past max_run_attempts — stop paying for it
    )
    for c in (failed_pre_step, manual, interrupted_mid_chain, gave_up):
        session.add(c)
    session.commit()

    ids = ar.pending_resumable_ids(session)
    assert failed_pre_step.id in ids
    assert interrupted_mid_chain.id in ids
    assert manual.id not in ids
    assert gave_up.id not in ids
