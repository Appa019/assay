from datetime import date

from app.services import review_service

_REPORT = """## Carteira
- 100% CDB.

---
```json
{"acoes": [
  {"tipo": "vender", "ticker": "CDB BRADESCO 100%CDI", "classe": "cdb", "valor_brl": 3000},
  {"tipo": "comprar", "ticker": "BTC", "classe": "crypto", "valor_brl": 2100, "stop": 74000},
  {"tipo": "comprar", "classe": "crypto"}
]}
```
"""


def test_report_actions_come_out_of_the_machine_block() -> None:
    actions = review_service.parse_actions_block(_REPORT)
    assert [a["ticker"] for a in actions] == ["CDB BRADESCO 100%CDI", "BTC"]  # no ticker = dropped
    assert review_service.parse_actions_block("sem bloco") == []
    assert review_service.parse_actions_block('```json\n{"orders": []}\n```') == []


def test_report_prompts_ask_for_a_document_with_actions() -> None:
    steps = review_service._weekly_steps([], {}, date(2026, 10, 19))
    synthesis = steps[1][1]
    assert '"acoes"' in synthesis
    assert "sem emoji" in synthesis
    assert "Telegram" not in synthesis


def test_weekly_review_is_one_step_returning_memo_and_report(session, monkeypatch) -> None:  # noqa: ANN001
    """A second step meant a resumed process, which re-wrote the cache."""
    from app.models.asset import Asset, AssetClass
    from app.services import analysis_runner, notification_center

    session.add(
        Asset(
            ticker="BTC",
            asset_class=AssetClass.CRYPTO,
            quantity=1,
            avg_price=1,
            entry_date=date.today(),
        )
    )
    session.commit()
    seen: dict[str, int] = {}

    def fake_chain(steps, **_kw):  # noqa: ANN001, ANN003
        seen["steps"] = len(steps)
        final = (
            "memo com a curva DI\n"
            f"{review_service._REPORT_MARKER}\n"
            "## Carteira\n- ok\n---\n```json\n"
            '{"acoes": [{"tipo": "manter", "ticker": "BTC"}]}\n```'
        )
        return analysis_runner.RunSummary(
            run_id="r",
            steps=[
                analysis_runner.StepResult(label="x", result=final, cost_usd=2.0, duration_s=1.0)
            ],
            final_summary=final,
        )

    monkeypatch.setattr(analysis_runner, "run_chain", fake_chain)
    monkeypatch.setattr(notification_center, "notify", lambda *a, **k: None)
    report = review_service.run_weekly_review(session, macro_ctx={}, notify=False)
    assert seen["steps"] == 1
    assert report.content == "## Carteira\n- ok"
    assert report.actions == [{"tipo": "manter", "ticker": "BTC"}]
    assert report.steps[0]["response"] == "memo com a curva DI"
    assert report.cost_usd == 2.0
