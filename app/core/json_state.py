"""Tolerant JSON state files — small persistent flags for the bot and crons.

State here is convenience (dedup flags, notification throttles), never data:
a missing, corrupt or wrong-shaped file must NEVER break a caller. Reads fall
back to an empty dict; writes are atomic (tmp + replace) and best-effort.
"""

import json
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()


def load_json_state(path: Path) -> dict[str, Any]:
    """Read a state dict; missing, corrupt or non-dict content is empty state."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_json_state(path: Path, state: dict[str, Any]) -> bool:
    """Atomically persist a state dict. Best-effort: returns False on failure.

    Atomic replace so a crash mid-write can't leave a truncated file behind
    (which the tolerant reader would then silently discard, resetting flags).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return True
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("json_state_save_failed", path=str(path), error=str(exc))
        return False
