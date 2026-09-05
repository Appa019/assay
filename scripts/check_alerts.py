#!/usr/bin/env python3
"""Price alerts on the committee's own levels — cheap cron, no Claude.

Refreshes prices, then compares each lot's current price against the
target/stop the committee registered on it (``Asset.target_price`` /
``stop_price``, filled by executing an Order or by hand). Alerts once per
crossing: the state resets when the price re-enters the band, so a level
re-crossed later alerts again — without spamming every run.

    python scripts/check_alerts.py
"""

import asyncio
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlmodel import Session, select  # noqa: E402

from app.core.database import engine, init_db  # noqa: E402
from app.models.asset import Asset  # noqa: E402
from app.models.notification import NotificationKind, NotificationLevel  # noqa: E402
from app.services import notification_center, price_refresh_service  # noqa: E402

_STATE_PATH = _PROJECT_ROOT / "storage" / "alerts_state.json"


def _load_state() -> dict[str, bool]:
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict[str, bool]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=1), encoding="utf-8")


def main() -> int:
    init_db()
    try:
        state = _load_state()
        alerts: list[str] = []
        with Session(engine) as session:
            asyncio.run(price_refresh_service.refresh_prices(session))
            assets = list(session.exec(select(Asset)).all())
            for asset in assets:
                price = asset.current_price
                if price is None:
                    continue
                for kind, level, hit, emoji, verb in (
                    (
                        "target",
                        asset.target_price,
                        price >= (asset.target_price or 0),
                        "🎯",
                        "atingiu o ALVO",
                    ),
                    (
                        "stop",
                        asset.stop_price,
                        asset.stop_price is not None and price <= asset.stop_price,
                        "🛑",
                        "rompeu o STOP",
                    ),
                ):
                    if level is None:
                        continue
                    key = f"{asset.id}:{kind}"
                    if hit and not state.get(key):
                        state[key] = True
                        alerts.append(
                            f"{emoji} {asset.ticker} {verb}: preço R$ {float(price):,.2f} "
                            f"vs nível R$ {float(level):,.2f} "
                            f"(lote de {asset.entry_date.isoformat()}). "
                            "Considere acionar o comitê (/revisao) ou vender (/vender)."
                        )
                    elif not hit and state.get(key):
                        state[key] = False  # re-armed for the next crossing
        _save_state(state)
        if alerts:
            notification_center.notify(
                "\n\n".join(alerts), kind=NotificationKind.ALERT, level=NotificationLevel.WARNING
            )
        print(f"{len(alerts)} alerta(s) disparado(s).")
        return 0
    except Exception as exc:  # noqa: BLE001 — a broken cron must alert, not vanish
        notification_center.notify(
            f"✖ check_alerts falhou: {exc}",
            kind=NotificationKind.SYSTEM,
            level=NotificationLevel.ERROR,
        )
        print(f"check_alerts falhou: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
