"""Two tiers: haiku books a spend, opus does everything else.

The rule the client set is "na dúvida, opus". These tests exist to keep the
fast path narrow — every case that is not provably a booking must land on the
big model, even when it looks small.
"""

import pytest

from app.config import settings
from app.services import model_router


def _tier(text: str) -> model_router.Tier:
    return model_router.route(text).tier


# --- the fast path ----------------------------------------------------------


def test_spend_booking_goes_to_haiku() -> None:
    route = model_router.route("gastei 42 no mercado")
    assert route.tier is model_router.Tier.FAST
    assert route.reason == "lançamento no ledger"


def test_written_amounts_hit_the_fast_path() -> None:
    assert _tier("gastei mil reais no mercado") is model_router.Tier.FAST


def test_benefit_spend_hits_the_fast_path() -> None:
    """ "vr"/"va" name a wallet, not a market instrument."""
    assert _tier("gastei 35 no vr hoje") is model_router.Tier.FAST


def test_receipt_event_hits_the_fast_path() -> None:
    assert _tier("recebi 120 de cashback") is model_router.Tier.FAST


def test_explicit_filing_command_hits_the_fast_path() -> None:
    assert _tier("anota 42 no mercado") is model_router.Tier.FAST


def test_room_numbers_are_not_mistaken_for_tickers() -> None:
    assert _tier("paguei 300 do aluguel da sala12") is model_router.Tier.FAST


def test_greeting_goes_to_haiku() -> None:
    route = model_router.route("oi")
    assert route.tier is model_router.Tier.FAST
    assert route.reason == "saudação"


# --- everything else is opus ------------------------------------------------


def test_recurring_benefit_declaration_goes_to_opus() -> None:
    """ "meu VR é 800" is a FACT about the client, not a transaction: it goes
    to MEMORY.md, and deciding that needs the big model."""
    assert _tier("meu vr é 800 por mês") is model_router.Tier.DEEP


def test_recurring_income_declaration_goes_to_opus() -> None:
    """Present tense "ganho" declares income. Only past-tense events book."""
    assert _tier("ganho 5000 de salário e 800 de vr") is model_router.Tier.DEEP


def test_installment_advice_goes_to_opus() -> None:
    """The client's own example: a purchase to plan, with a question about how
    far to stretch it. Amount plus a verb, but unmistakably a doubt."""
    assert (
        _tier(
            "preciso comprar algo de 3000 urgente, posso parcelar em 10x, "
            "no máximo quanto vc recomenda eu parcelar?"
        )
        is model_router.Tier.DEEP
    )


def test_booking_with_a_question_attached_goes_to_opus() -> None:
    """ "na dúvida, opus": a question rides along, so the whole turn escalates."""
    assert _tier("gastei 300 no mercado, quanto me sobrou esse mês?") is model_router.Tier.DEEP


def test_portfolio_purchase_goes_to_opus() -> None:
    """ "comprei 100 PETR4" is an investment statement, not a grocery run."""
    assert _tier("comprei 100 PETR4 hoje") is model_router.Tier.DEEP


def test_long_message_never_takes_the_fast_path() -> None:
    """A booking is one short sentence; length means extra intent."""
    long_text = "gastei 42 no mercado " + "e também precisava te contar uma coisa " * 4
    assert _tier(long_text) is model_router.Tier.DEEP


def test_open_question_goes_to_opus() -> None:
    assert _tier("me explica juros compostos no cartão") is model_router.Tier.DEEP


def test_router_disabled_pins_everything_to_opus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "chat_router_enabled", False)
    route = model_router.route("oi")
    assert route.tier is model_router.Tier.DEEP
    assert route.reason == "roteador desligado"


def test_routing_never_costs_a_model_call() -> None:
    """The whole point of the rewrite: no triage process is ever spawned, so a
    deep turn is never slower than pinning opus was."""
    assert not hasattr(model_router, "_triage")


def test_tiers_map_to_the_configured_models() -> None:
    assert model_router.route("gastei 42 no mercado").model == settings.chat_fast_model
    assert model_router.route("devo comprar PETR4?").model == settings.chat_deep_model


# --- the lookup tier --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "quanto tenho em cripto?",
        "qual o preço da PETR4?",
        "como está a carteira?",
        "quanto rendeu meu CDB?",
        "ordens pendentes",
        "quanto vale minha carteira hoje?",
        "quando destrava meu BTC?",
        "quanto gastei no mercado esse mês?",
        "qual a cotação do bitcoin?",
    ],
)
def test_factual_lookups_go_to_the_middle_tier(text: str) -> None:
    """Reading a number the app already has is retrieval, not advice."""
    route = model_router.route(text)
    assert route.tier is model_router.Tier.LOOKUP
    assert route.model == settings.chat_lookup_model


@pytest.mark.parametrize(
    "text",
    [
        "quanto tenho em cripto? devo aumentar?",  # lookup + decision
        "qual o preço da PETR4? vale a pena comprar?",
        "quanto tenho parado? qual a melhor aplicação?",
        "como está a carteira? preciso rebalancear?",
        "quanto rendeu o CDB? compensa trocar por ação?",
    ],
)
def test_a_lookup_carrying_a_decision_still_goes_to_opus(text: str) -> None:
    """The guard that keeps the middle tier honest: any advice word wins."""
    assert _tier(text) is model_router.Tier.DEEP


def test_long_lookup_falls_back_to_opus() -> None:
    """Past a certain length the message is a briefing, not a question."""
    long_text = "quanto tenho em cripto? " + "e me conta como foi a semana do mercado " * 5
    assert _tier(long_text) is model_router.Tier.DEEP


def test_lookup_tier_maps_to_the_configured_model() -> None:
    assert model_router.route("quanto tenho em cripto?").model == settings.chat_lookup_model
    assert model_router.route("quanto tenho em cripto?").reason == "consulta factual"


def test_an_attachment_never_takes_the_lookup_tier() -> None:
    """Measured on real history: every LOOKUP hit was a photo whose caption
    mentioned "carteira"/"fatura". The router cannot see the image, so it must
    not price the turn as if it were a balance read."""
    assert _tier("📎 IMG_1365.png\nEssa é minha carteira completa de cripto") is (
        model_router.Tier.DEEP
    )


# --- credit card ---------------------------------------------------------------


def test_card_purchase_still_books_fast() -> None:
    assert _tier("gastei 42 no cartão") is model_router.Tier.FAST
    assert _tier("comprei a tv em 10x de 200 no cartão") is model_router.Tier.FAST


def test_paying_the_invoice_is_never_a_booking() -> None:
    """ "paguei a fatura 3200" has a past-tense verb and an amount — the fast
    path would book a R$ 3.200 expense that double-counts every purchase
    already in the ledger. Anything about the invoice goes to opus."""
    assert _tier("paguei a fatura 3200") is model_router.Tier.DEEP
    assert _tier("paguei a fatura do nubank, 3.412,90") is model_router.Tier.DEEP


def test_invoice_questions_skip_the_lookup_tier() -> None:
    assert _tier("quanto tá minha fatura?") is model_router.Tier.DEEP
    assert _tier("qual o valor da fatura") is model_router.Tier.DEEP
