"""Turn a sentence into a cashflow entry.

"gastei 42,90 no mercado" → expense / 42.90 / mercado. The user types how they
speak; the ledger still gets clean structured rows.

Deliberately NOT the consultant: this runs in a bare workspace with no MCP
servers and a small model, because it happens while someone waits with a thumb
on the screen. The consultant (``chat_service``) is opus with a full research
toolbelt and takes minutes — wrong tool for a two-second job.
"""

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import structlog

from app.config import settings
from app.models.cashflow import CashflowKind
from app.schemas.cashflow import CashflowCreate
from app.services import analysis_runner
from app.services.analysis_runner import AnalysisError
from app.services.cashflow_service import CANONICAL_CATEGORIES, normalize_wallet

logger = structlog.get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# No .mcp.json here on purpose — its absence is what keeps the run fast.
_WORKSPACE = _PROJECT_ROOT / "storage" / "classifier_workspace"

_WEEKDAYS = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)

# Rendered from the ledger's canonical vocabulary — the consultant's orders use
# the same source, so both doors speak identical category names (no accents).
_KNOWN_CATEGORIES = ", ".join(CANONICAL_CATEGORIES)


class ClassificationError(RuntimeError):
    """The text could not be turned into an entry."""


def _prompt(text: str) -> str:
    return f"""Você classifica lançamentos financeiros pessoais em pt-BR.

Frase do usuário: "{text}"

Responda APENAS com um bloco JSON, sem nenhum texto antes ou depois:

```json
{{"kind": "expense|income", "amount_brl": 0.00, "category": "...", "description": "...", "occurred_on": "AAAA-MM-DD", "wallet": "conta|vr|va"}}
```

Regras:
- `kind`: "expense" para gastos/saídas, "income" para ganhos/entradas.
- `amount_brl`: número decimal com ponto. "42,90" vira 42.90. "1.250" vira 1250.00.
  Se a frase não tiver valor nenhum, use 0.
- `category`: UMA palavra em minúsculas e SEM acento.
  Prefira uma destas quando fizer sentido: {_KNOWN_CATEGORIES}.
  Se nada servir, invente uma curta e óbvia (também sem acento).
- `description`: a frase limpa e curta (máx. 80 caracteres), sem o valor.
  Ex.: "compra da semana", "uber pro centro". Se não houver detalhe, use "".
- `occurred_on`: a data do lançamento em AAAA-MM-DD. Resolva expressões
  relativas: "hoje" = {date.today().isoformat()}, "ontem" = o dia anterior,
  "sexta passada" = a sexta mais recente antes de hoje. Sem menção de data,
  use hoje.
- `wallet`: de onde o dinheiro saiu/entrou. "vr" se a frase citar VR ou
  vale-refeição; "va" se citar VA ou vale-alimentação. "no vale", sem
  especificar qual: "vr" para restaurante/lanche, "va" para mercado. Sem
  menção a benefício, use "conta" (banco, pix, cartão, dinheiro).
- Hoje é {date.today().isoformat()} ({_WEEKDAYS[date.today().weekday()]}).
"""


def _extract_json(raw: str) -> dict[str, object]:
    fenced = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        loose = re.search(r"\{.*\}", raw, re.DOTALL)
        candidate = loose.group(0) if loose else None
    if candidate is None:
        raise ClassificationError("O classificador não devolveu JSON.")
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ClassificationError(f"JSON inválido do classificador: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ClassificationError("O classificador devolveu algo que não é um objeto.")
    return parsed


def classify(text: str) -> CashflowCreate:
    """Best-effort structured entry from free text. Never writes to the ledger."""
    text = text.strip()
    if not text:
        raise ClassificationError("Texto vazio.")

    _WORKSPACE.mkdir(parents=True, exist_ok=True)
    try:
        result = analysis_runner._run_claude_step(
            _prompt(text),
            resume_session_id=None,
            model=settings.classifier_model,
            effort=settings.classifier_effort,
            timeout=settings.classifier_timeout,
            cwd=_WORKSPACE,
            transcript_tag=None,
        )
    except AnalysisError as exc:
        raise ClassificationError(f"Não consegui classificar: {exc}") from exc

    data = _extract_json(result.result)

    kind_raw = str(data.get("kind", "expense")).lower()
    kind = CashflowKind.INCOME if kind_raw == "income" else CashflowKind.EXPENSE

    try:
        amount = Decimal(str(data.get("amount_brl", 0))).quantize(Decimal("0.01"))
    except (ArithmeticError, ValueError) as exc:
        raise ClassificationError("Valor inválido devolvido pelo classificador.") from exc
    if amount <= 0:
        raise ClassificationError(
            "Não achei um valor na frase. Escreva algo como “gastei 42,90 no mercado”."
        )

    category = str(data.get("category") or "outros").strip().lower()[:64] or "outros"
    description = str(data.get("description") or "").strip()[:512] or None

    # A malformed date is not worth failing the whole entry over — fall back to
    # today and let the user correct it in the form.
    occurred_on: date | None = None
    raw_date = str(data.get("occurred_on") or "").strip()
    if raw_date:
        try:
            occurred_on = date.fromisoformat(raw_date)
        except ValueError:
            logger.warning("cashflow_classify_bad_date", raw=raw_date[:20])

    wallet = normalize_wallet(str(data.get("wallet") or "conta")).value

    logger.info(
        "cashflow_classified", kind=kind, amount=float(amount), category=category, wallet=wallet
    )
    return CashflowCreate(
        kind=kind,
        amount_brl=amount,
        category=category,
        description=description,
        occurred_on=occurred_on,
        wallet=wallet,
    )
