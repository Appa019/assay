from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.database import get_session
from app.main import app
from app.models.asset import AssetClass
from app.models.contribution import Contribution, ContributionPrompt, ContributionStatus
from app.models.order import Order


def test_delete_contribution_with_children_and_fk_on(session: Session) -> None:
    """Regression: with PRAGMA foreign_keys=ON, deleting a contribution that
    still has prompts and orders 500'd — the ORM flushed the parent delete
    before the children (no relationships defined to order them)."""
    contribution = Contribution(amount_brl=Decimal("100"), status=ContributionStatus.COMPLETED)
    session.add(contribution)
    session.commit()
    session.refresh(contribution)
    session.add(
        ContributionPrompt(
            contribution_id=contribution.id,
            prompt_order=1,
            prompt_key="macro",
            title="t",
            description="d",
            content="c",
        )
    )
    session.add(
        Order(
            contribution_id=contribution.id,
            ticker="PETR4",
            asset_class=AssetClass.STOCKS,
            amount_brl=Decimal("100"),
        )
    )
    session.commit()

    app.dependency_overrides[get_session] = lambda: session
    try:
        client = TestClient(app)
        response = client.delete(f"/api/contributions/{contribution.id}")
        assert response.status_code == 204
        assert session.get(Contribution, contribution.id) is None
    finally:
        app.dependency_overrides.clear()
