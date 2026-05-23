"""Create a contribution and render its prompt sequence.

Shared by the HTTP router and the terminal orchestrator so both build the
exact same snapshot + prompts from a single source of truth.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import structlog
from sqlmodel import Session

from app.models.contribution import Contribution, ContributionPrompt, ContributionStatus
from app.services import market_data_service, portfolio_service, prompt_generator

logger = structlog.get_logger()


async def create_contribution_with_prompts(
    session: Session,
    *,
    amount_brl: Decimal,
    notes: str | None = None,
) -> tuple[Contribution, list[ContributionPrompt]]:
    """Capture the macro + portfolio snapshot and render every prompt.

    Returns the persisted contribution and its prompts ordered by ``prompt_order``.
    """
    today = date.today()

    summary = portfolio_service.get_portfolio_summary(session)
    portfolio_rows = portfolio_service.build_portfolio_snapshot(session)
    macro_ctx = await market_data_service.build_full_context()

    allocation_current = {
        "fixed_income_pct": summary.allocation.fixed_income_pct,
        "stocks_pct": summary.allocation.stocks_pct,
        "crypto_pct": summary.allocation.crypto_pct,
    }

    contribution = Contribution(
        amount_brl=amount_brl,
        status=ContributionStatus.READY,
        notes=notes,
        macro_snapshot=macro_ctx,
        portfolio_snapshot={
            "total_value": float(summary.total_value),
            "allocation_current": allocation_current,
            "allocation_target": summary.target_allocation,
            "allocation_deviation": summary.deviation,
            "assets": portfolio_rows,
        },
    )
    session.add(contribution)
    session.commit()
    session.refresh(contribution)

    render_ctx = prompt_generator.build_render_context(
        contribution_id=str(contribution.id),
        amount_brl=float(amount_brl),
        contribution_date=today,
        portfolio_total=float(summary.total_value),
        allocation_current=allocation_current,
        allocation_target=summary.target_allocation,
        allocation_deviation=summary.deviation,
        assets=portfolio_rows,
        macro=macro_ctx.get("macro", {}),
        ibovespa=macro_ctx.get("ibovespa", {}),
        crypto_global=macro_ctx.get("crypto_global", {}),
        fear_greed_index=macro_ctx.get("fear_greed_index"),
        warnings=macro_ctx.get("warnings", []),
        captured_at=macro_ctx.get("captured_at", datetime.now(UTC).isoformat()),
    )

    prompts_data = prompt_generator.render_all_prompts(render_ctx)
    prompt_rows: list[ContributionPrompt] = []
    for data in prompts_data:
        row = ContributionPrompt(
            contribution_id=contribution.id,
            prompt_order=data["prompt_order"],
            prompt_key=data["prompt_key"],
            title=data["title"],
            description=data["description"],
            content=data["content"],
        )
        session.add(row)
        prompt_rows.append(row)
    session.commit()
    for row in prompt_rows:
        session.refresh(row)

    prompt_rows.sort(key=lambda r: r.prompt_order)

    logger.info(
        "contribution_created",
        contribution_id=str(contribution.id),
        amount=str(amount_brl),
        prompts=len(prompt_rows),
    )
    return contribution, prompt_rows
