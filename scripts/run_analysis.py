#!/usr/bin/env python3
"""Add a contribution and run the full multi-meeting analysis end to end.

Usage:
    python scripts/run_analysis.py --amount 5000
    python scripts/run_analysis.py --amount 5000 --notes "aporte de maio"
    python scripts/run_analysis.py --contribution-id <uuid>   # re-run existing
    python scripts/run_analysis.py --amount 100 --model haiku --effort low  # cheap dry test

You only type the amount. It captures the macro + portfolio snapshot, renders
every committee prompt, runs them in order through the Claude CLI (a single
chained session, --dangerously-skip-permissions, --effort max), shows progress
step by step, and prints the final "where to invest and how much".
"""

import argparse
import asyncio
import sys
import textwrap
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.core.database import get_session, init_db  # noqa: E402
from app.models.contribution import Contribution  # noqa: E402
from app.services import analysis_runner, contribution_service  # noqa: E402

# --- tiny ANSI helpers (no external deps) -----------------------------------
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_CYAN = "\033[36m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_RESET = "\033[0m"


def _c(text: str, color: str) -> str:
    return f"{color}{text}{_RESET}" if sys.stdout.isatty() else text


def _brl(value: float) -> str:
    integer, decimals = f"{value:,.2f}".split(".")
    return f"R$ {integer.replace(',', '.')},{decimals}"


def _make_event_printer() -> Any:
    def on_event(name: str, payload: dict[str, Any]) -> None:
        if name == "run_start":
            print()
            print(_c("━" * 70, _DIM))
            print(
                _c("Iniciando análise", _BOLD)
                + f"  ·  {payload['total_steps']} etapas  ·  "
                + f"modelo {_c(payload['model'], _CYAN)}  ·  effort {_c(payload['effort'], _CYAN)}"
            )
            print(_c("━" * 70, _DIM))
        elif name == "step_retry":
            kind = "limite de uso" if payload.get("kind") == "limit" else "erro transitório"
            print(
                _c(
                    f"  ⏳ {kind} — retomando (tentativa {payload['attempt']}) "
                    f"em {payload['wait_s']}s…",
                    _YELLOW,
                )
            )
        elif name == "step_start":
            print()
            print(
                _c(f"▶ Etapa {payload['step']}/{payload['total']}", _BOLD)
                + _c(f"  {payload['title']}", _CYAN)
            )
            print(_c("  rodando claude (pode levar minutos)…", _DIM))
        elif name == "step_done":
            print(
                _c("  ✔ concluída", _GREEN)
                + _c(
                    f"  ·  {_brl(payload['cost_usd']).replace('R$', 'US$')}"
                    f"  ·  {payload['duration_s']:.0f}s",
                    _DIM,
                )
            )
            preview = textwrap.shorten(
                payload.get("result", "").replace("\n", " "), width=240, placeholder=" […]"
            )
            print(_c(f"  {preview}", _DIM))
        elif name == "run_error":
            print()
            print(_c(f"✖ Falhou: {payload['error']}", _RED))
        elif name == "run_done":
            print()
            print(_c("═" * 70, _GREEN))
            print(_c("ANÁLISE CONCLUÍDA — onde investir e quanto", _BOLD))
            print(
                _c(
                    f"custo total US$ {payload['total_cost_usd']:.2f}"
                    f"  ·  tempo total {payload['total_duration_s'] / 60:.1f} min",
                    _DIM,
                )
            )
            print(_c("═" * 70, _GREEN))
            print()
            print(payload["final_summary"])
            print()

    return on_event


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full contribution analysis cycle.")
    parser.add_argument("--amount", type=str, help="Valor do aporte em BRL (ex: 5000 ou 5000.50)")
    parser.add_argument("--notes", type=str, default=None, help="Observação opcional do aporte")
    parser.add_argument(
        "--contribution-id", type=str, default=None, help="Rodar sobre um aporte já existente"
    )
    parser.add_argument("--model", type=str, default=analysis_runner.DEFAULT_MODEL)
    parser.add_argument("--effort", type=str, default=analysis_runner.DEFAULT_EFFORT)
    parser.add_argument(
        "--step-timeout",
        type=int,
        default=analysis_runner.DEFAULT_STEP_TIMEOUT,
        help="Timeout por etapa, em segundos",
    )
    parser.add_argument("-y", "--yes", action="store_true", help="Não pedir confirmação")
    parser.add_argument(
        "--no-telegram", action="store_true", help="Não enviar a recomendação ao Telegram"
    )
    return parser.parse_args()


def _confirm(amount: float, n_prompts: int, model: str, effort: str) -> bool:
    print()
    print(_c("Plano de execução", _BOLD))
    print(f"  aporte:   {_brl(amount)}")
    print(f"  etapas:   {n_prompts} reuniões + 1 fechamento")
    print(f"  modelo:   {model}  ·  effort: {effort}")
    print(
        _c(
            "  custo:    cada etapa é uma chamada real à API (opus/max em prompt grande "
            "pode custar alguns dólares e levar dezenas de minutos no total).",
            _YELLOW,
        )
    )
    answer = input(_c("Confirmar e rodar? [s/N] ", _BOLD)).strip().lower()
    return answer in {"s", "sim", "y", "yes"}


def main() -> int:
    args = _parse_args()

    if not args.amount and not args.contribution_id:
        print(_c("Informe --amount <valor> ou --contribution-id <uuid>.", _RED))
        return 2

    init_db()
    session_gen = get_session()
    session = next(session_gen)
    try:
        if args.contribution_id:
            contribution = session.get(Contribution, UUID(args.contribution_id))
            if contribution is None:
                print(_c(f"Aporte {args.contribution_id} não encontrado.", _RED))
                return 1
            n_prompts = len(contribution_prompts(session, contribution.id))
            amount = float(contribution.amount_brl)
        else:
            try:
                amount_dec = Decimal(args.amount)
            except (InvalidOperation, ValueError):
                print(_c(f"Valor inválido: {args.amount!r}", _RED))
                return 2
            if amount_dec <= 0:
                print(_c("O aporte deve ser maior que zero.", _RED))
                return 2
            print(_c("Capturando snapshot de mercado e portfólio…", _DIM))
            contribution, prompts = asyncio.run(
                contribution_service.create_contribution_with_prompts(
                    session, amount_brl=amount_dec, notes=args.notes
                )
            )
            n_prompts = len(prompts)
            amount = float(amount_dec)

        if not args.yes and not _confirm(amount, n_prompts, args.model, args.effort):
            print(
                _c(
                    "Cancelado. O aporte foi salvo e pode ser rodado depois com "
                    f"--contribution-id {contribution.id}",
                    _DIM,
                )
            )
            return 0

        analysis_runner.run_analysis(
            session,
            contribution.id,
            model=args.model,
            effort=args.effort,
            step_timeout=args.step_timeout,
            notify=not args.no_telegram,
            on_event=_make_event_printer(),
        )
        return 0
    except analysis_runner.AnalysisError as exc:
        print(_c(f"Erro na análise: {exc}", _RED))
        return 1
    except KeyboardInterrupt:
        print(
            _c(
                "\nInterrompido. Estado parcial salvo; retome com "
                f"--contribution-id {args.contribution_id or ''}",
                _YELLOW,
            )
        )
        return 130
    finally:
        session_gen.close()


def contribution_prompts(session: Any, contribution_id: UUID) -> list[Any]:
    from sqlmodel import select

    from app.models.contribution import ContributionPrompt

    return list(
        session.exec(
            select(ContributionPrompt).where(ContributionPrompt.contribution_id == contribution_id)
        ).all()
    )


if __name__ == "__main__":
    raise SystemExit(main())
