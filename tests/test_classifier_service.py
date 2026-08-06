"""The free-text classifier: the draft entry must carry the wallet the
sentence names, and unknown/missing wallets must degrade to "conta"."""

import json
from types import SimpleNamespace

import pytest

from app.services import analysis_runner, classifier_service


def _stub_step(monkeypatch: pytest.MonkeyPatch, payload: dict) -> None:
    def fake(prompt: str, **_kwargs) -> SimpleNamespace:  # noqa: ANN003
        return SimpleNamespace(result=f"```json\n{json.dumps(payload)}\n```")

    monkeypatch.setattr(analysis_runner, "_run_claude_step", fake)


def test_classify_carries_the_wallet(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_step(
        monkeypatch,
        {
            "kind": "expense",
            "amount_brl": 35.0,
            "category": "restaurante",
            "description": "almoço",
            "occurred_on": "2026-08-06",
            "wallet": "vr",
        },
    )
    draft = classifier_service.classify("almocei por 35 no vr")
    assert draft.wallet == "vr"
    assert draft.category == "restaurante"


def test_classify_without_wallet_defaults_to_conta(monkeypatch: pytest.MonkeyPatch) -> None:
    """Old-shaped model output (no wallet key) must keep working unchanged."""
    _stub_step(
        monkeypatch,
        {"kind": "expense", "amount_brl": 10.0, "category": "mercado", "description": ""},
    )
    draft = classifier_service.classify("gastei 10 no mercado")
    assert draft.wallet == "conta"


def test_classify_folds_a_creative_wallet_spelling(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_step(
        monkeypatch,
        {
            "kind": "expense",
            "amount_brl": 90.0,
            "category": "mercado",
            "wallet": "Vale Alimentação",
        },
    )
    draft = classifier_service.classify("feira no vale alimentação, 90")
    assert draft.wallet == "va"


def test_prompt_teaches_the_wallet_field() -> None:
    prompt = classifier_service._prompt("gastei 42 no mercado")
    assert '"wallet"' in prompt
    assert "vale-refeição" in prompt
