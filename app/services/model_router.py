"""Pick the model for each chat turn. Two tiers, decided without asking a model.

The consultant answers on opus. The single exception is booking a spend or a
receipt — "gastei 42 no mercado" — which is the most frequent message in the
product, needs no reasoning, and runs on haiku in roughly half the time.

Everything else is opus, deliberately. A question, a doubt, a fact about the
client to remember, a purchase to plan: **when in doubt, opus.**

There used to be a haiku triage step deciding between three tiers. On the Pi
each triage is a fresh CLI process — measured at 5.6s, not the ~1s the design
assumed — so it made every investment question SLOWER than pinning opus. The
rules below cost nothing and are strict: the fast path has to be proven, not
guessed.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

import structlog

from app.config import settings

logger = structlog.get_logger()


class Tier(StrEnum):
    FAST = "fast"
    DEEP = "deep"


@dataclass(frozen=True)
class Route:
    tier: Tier
    model: str
    effort: str
    reason: str


def _route_for(tier: Tier, reason: str) -> Route:
    if tier is Tier.FAST:
        return Route(
            tier=tier,
            model=settings.chat_fast_model,
            effort=settings.chat_fast_effort,
            reason=reason,
        )
    return Route(
        tier=tier,
        model=settings.chat_deep_model,
        effort=settings.chat_deep_effort,
        reason=reason,
    )


# Greetings, thanks and one-word acks. Unambiguous, and the only other place
# where a big model buys nothing at all.
_TRIVIAL_RE = re.compile(
    r"^(oi+|ola|olá|eae|opa|bom dia|boa tarde|boa noite|tudo bem\??|"
    r"obrigad[oa]|valeu|vlw|ok|okay|blz|beleza|certo|entendi|show|"
    r"tchau|até|abraço)[!.?\s]*$",
    re.IGNORECASE,
)

# PAST-TENSE events only, plus the explicit filing commands. Present-tense
# forms are deliberately absent: "ganho 5000 de salário", "meu VR é 800" and
# "recebo 800 de benefício" declare a RECURRING fact about the client. That is
# something the consultant has to reason about and write to MEMORY.md, not a
# line to book — so it falls through to opus like everything else.
_LEDGER_EVENT_RE = re.compile(
    r"\b(gastei|gastamos|paguei|pagamos|comprei|compramos|torrei|"
    r"recebi|recebemos|ganhei|ganhamos|caiu|entrou|"
    r"anota|anote|lan[çc]a|lance|registra|registre|adiciona|adicione)\b",
    re.IGNORECASE,
)

# Digits, or the amounts people actually type out ("gastei mil reais no
# mercado" must hit the fast path too).
_HAS_AMOUNT_RE = re.compile(
    r"\d|\b(mil|cem|duzentos|trezentos|quatrocentos|quinhentos|seiscentos|"
    r"setecentos|oitocentos|novecentos|vinte|trinta|quarenta|cinquenta|"
    r"sessenta|setenta|oitenta|noventa)\b",
    re.IGNORECASE,
)

# Anything that ASKS instead of stating. "gastei 300 no mercado, quanto me
# sobrou?" books a line AND wants advice — that is a doubt, so it is opus.
_ASKS_RE = re.compile(
    r"\?|\b(quanto|quanta|quantos|quantas|qual|quais|como|onde|quando|"
    r"por que|porqu[êe]|pq|"
    r"devo|deveria|posso|poderia|consigo|vale a pena|compensa|"
    r"recomenda|recomendas|recomendaria|sugere|sugest[ãa]o|acha|achas|"
    r"melhor|pior|ajuda|explica|explique|dica|opini[ãa]o|"
    r"parcel\w*|financi\w*|juros|d[íi]vida|empr[ée]stimo)\b",
    re.IGNORECASE,
)

# Market words mean the answer needs live data and real reasoning. The ticker
# shape is anchored to real B3 suffixes (3/4/5/6/11) so "sala12" is not one.
_MARKET_RE = re.compile(
    r"\b(a[çc][ãa]o|a[çc][õo]es|ativo|carteira|aporte|investi|investir|"
    r"invisto|invista|aplico|aplicar|aplique|"
    r"bitcoin|btc|eth|cripto|crypto|cdb|cdi|selic|ipca|tesouro|dividendo|"
    r"rebalance|tese|valuation|[a-z]{4}(?:3|4|5|6|11))\b",
    re.IGNORECASE,
)

# A booking is one short sentence. Anything longer is carrying extra intent.
_LEDGER_MAX_CHARS = 120


def route(text: str) -> Route:
    """Choose a model for this message. Never raises."""
    text = text.strip()

    if not settings.chat_router_enabled:
        return _route_for(Tier.DEEP, "roteador desligado")

    if len(text) <= 24 and _TRIVIAL_RE.match(text):
        return _route_for(Tier.FAST, "saudação")

    if (
        len(text) <= _LEDGER_MAX_CHARS
        and _LEDGER_EVENT_RE.search(text)
        and _HAS_AMOUNT_RE.search(text)
        and not _ASKS_RE.search(text)
        and not _MARKET_RE.search(text)
    ):
        logger.info("model_router_pick", tier=Tier.FAST.value, chars=len(text))
        return _route_for(Tier.FAST, "lançamento no ledger")

    return _route_for(Tier.DEEP, "padrão")
