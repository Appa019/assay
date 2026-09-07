"""Pick the model for each chat turn. Three tiers, decided without asking a model.

Cheapest first:

- **fast** (haiku): booking a spend or a receipt — "gastei 42 no mercado". The
  most frequent message in the product, needs no reasoning.
- **lookup** (sonnet): a FACTUAL question about data the app already owns or a
  live quote — "quanto tenho em cripto?", "qual o preço da PETR4?". This is
  retrieval plus one line of formatting; measured at ~US$ 1.67/turn on opus,
  which is what a full investment opinion should cost, not a balance read.
- **deep** (opus): everything else. A doubt, an opinion, a purchase to plan, a
  fact about the client to remember: **when in doubt, opus.**

The lookup tier is deliberately narrow: it needs a positive match on a
retrieval phrasing AND no advice word anywhere. "quanto tenho em cripto, devo
aumentar?" carries a decision, so it is deep — the cheap tier has to be proven,
never guessed.

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
    LOOKUP = "lookup"
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
    if tier is Tier.LOOKUP:
        return Route(
            tier=tier,
            model=settings.chat_lookup_model,
            effort=settings.chat_lookup_effort,
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

# Judgment words. ANY of these anywhere sends the turn to opus, whatever else
# the message looks like — this is the guard that keeps the middle tier honest.
# "vale a pena" is here; bare "vale" is NOT, because "quanto vale minha
# carteira" is a balance read.
_ADVICE_RE = re.compile(
    r"\b(devo|deveria|posso|poderia|consigo|vale a pena|compensa|"
    r"recomend\w*|sugere|sugest\w*|ach[oa]|achas|melhor|pior|opini\w*|"
    r"explica\w*|explique|por que|porqu[êe]|pq|dica|"
    r"estrat[ée]gi\w*|tese|valuation|analis\w*|avali\w*|"
    r"compr\w*|vend\w*|aport\w*|investi\w*|invist\w*|aplic\w*|"
    r"rebalanc\w*|risco|arrisc\w*|proje[çc]\w*|previs\w*|futuro|"
    r"tend[êe]ncia|parcel\w*|financi\w*|juros|d[íi]vida|empr[ée]stimo)\b",
    re.IGNORECASE,
)

# Retrieval phrasings: reading state the app already has, or a live quote.
_LOOKUP_RE = re.compile(
    r"\bquanto (eu )?(tenho|tem|possuo|apliquei|gastei|ganhei|sobrou|"
    r"rendeu|rende|custa|vale)\b"
    r"|\bquant[oa]s? (a[çc][õo]es|cotas|unidades|lotes|reais)\b"
    r"|\bqual (?:[éeh]+ )?(?:o |a )?(pre[çc]o|cota[çc][ãa]o|saldo|"
    r"patrim[ôo]nio|posi[çc][ãa]o|total|valor)\b"
    r"|\b(pre[çc]o|cota[çc][ãa]o) (d[oae]|atual)\b"
    r"|\bcomo (est[áa]|t[áa]) (a|o|minha|meu)\b"
    r"|\bordens? pendentes?\b"
    r"|\b(meu|minha) (saldo|extrato|patrim[ôo]nio|carteira|posi[çc][ãa]o)\b"
    r"|\bquando (destrava|libera|vence)\b"
    r"|\b(extrato|resumo) d[eo] m[êe]s\b"
    r"|\bquanto (de )?(ir|darf|imposto)\b",
    re.IGNORECASE,
)

# An attachment (photo of a receipt, a statement, a portfolio print) carries
# content the router cannot see. Booking one is still fast — haiku reads a
# receipt fine — but it is never a "lookup": measured against real history,
# every LOOKUP match was an image whose caption happened to say "carteira".
_ATTACHMENT_MARK = "📎"

# A booking is one short sentence. Anything longer is carrying extra intent.
_LEDGER_MAX_CHARS = 120
# A lookup is still one question, not a briefing.
_LOOKUP_MAX_CHARS = 160


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

    if (
        len(text) <= _LOOKUP_MAX_CHARS
        and _ATTACHMENT_MARK not in text
        and _LOOKUP_RE.search(text)
        and not _ADVICE_RE.search(text)
    ):
        logger.info("model_router_pick", tier=Tier.LOOKUP.value, chars=len(text))
        return _route_for(Tier.LOOKUP, "consulta factual")

    return _route_for(Tier.DEEP, "padrão")
