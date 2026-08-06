import pytest

from app.config import settings
from app.services import model_router


@pytest.fixture(autouse=True)
def _triage_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shortcut tests must never reach the paid triage call."""
    monkeypatch.setattr(
        model_router,
        "_triage",
        lambda _text, _context="": pytest.fail("triage must not be called"),
    )


def test_greeting_short_circuits_to_fast() -> None:
    route = model_router.route("oi")
    assert route.tier is model_router.Tier.FAST
    assert route.reason == "saudação"


def test_ledger_logging_short_circuits_to_fast() -> None:
    """The product's most frequent message must never pay triage latency."""
    route = model_router.route("gastei 42,90 no mercado ontem")
    assert route.tier is model_router.Tier.FAST
    assert route.reason == "lançamento no ledger"


def test_written_amounts_hit_the_ledger_shortcut() -> None:
    """Amounts written out in words are still the product's cheapest turn."""
    route = model_router.route("gastei mil reais no mercado")
    assert route.tier is model_router.Tier.FAST
    assert route.reason == "lançamento no ledger"


def test_room_numbers_are_not_mistaken_for_tickers() -> None:
    """The B3 ticker guard is anchored to real suffixes — "sala12" is not one,
    so this stays on the free shortcut instead of paying triage."""
    route = model_router.route("paguei 300 do aluguel da sala12")
    assert route.tier is model_router.Tier.FAST
    assert route.reason == "lançamento no ledger"


def test_portfolio_purchase_is_not_mistaken_for_ledger_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "comprei 100 PETR4" is an investment statement — the market guard must
    push it through triage instead of the cheap ledger shortcut."""
    monkeypatch.setattr(model_router, "_triage", lambda _text, _context="": model_router.Tier.DEEP)
    route = model_router.route("comprei 100 PETR4 hoje")
    assert route.tier is model_router.Tier.DEEP


def test_router_disabled_pins_everything_to_deep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "chat_router_enabled", False)
    route = model_router.route("oi")
    assert route.tier is model_router.Tier.DEEP
    assert route.reason == "roteador desligado"


def test_triage_failure_falls_back_to_balanced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Routing must never be the reason a chat fails (D8)."""

    def broken(_text: str, _context: str = "") -> model_router.Tier:
        raise RuntimeError("triagem quebrou")

    monkeypatch.setattr(model_router, "_triage", broken)
    route = model_router.route("me explica juros compostos no cartão")
    assert route.tier is model_router.Tier.BALANCED
    assert "falhou" in route.reason
