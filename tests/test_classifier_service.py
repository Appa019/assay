"""The free-text classifier: the draft entry must carry the wallet the
sentence names, and unknown/missing wallets must degrade to "conta"."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import analysis_runner, classifier_service


@pytest.fixture(autouse=True)
def _tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # classify() creates its workspace; on the Pi storage/ is the client's data disk
    monkeypatch.setattr(classifier_service, "_WORKSPACE", tmp_path / "classifier_workspace")


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


def test_classify_carries_card_and_installments(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_step(
        monkeypatch,
        {
            "kind": "expense",
            "amount_brl": 2000.0,
            "category": "lazer",
            "description": "tv",
            "occurred_on": "2026-09-10",
            "wallet": "conta",
            "card": "nubank",
            "installments": 10,
        },
    )
    draft = classifier_service.classify("comprei uma tv em 10x de 200 no nubank")
    assert draft.card == "nubank"
    assert draft.installments == 10


def test_classify_auto_card_becomes_none_and_bad_installments_fall_to_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_step(
        monkeypatch,
        {
            "kind": "expense",
            "amount_brl": 10.0,
            "category": "mercado",
            "card": "auto",
            "installments": "99",
        },
    )
    draft = classifier_service.classify("gastei 10 no mercado")
    assert draft.card is None
    assert draft.installments == 1


def test_classify_old_shape_defaults_card_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_step(monkeypatch, {"kind": "expense", "amount_brl": 10.0, "category": "mercado"})
    draft = classifier_service.classify("gastei 10 no mercado")
    assert draft.card is None
    assert draft.installments == 1
