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
