#!/usr/bin/env python3
"""Count what still uses the legacy values, before the commit that removes them.

Migration step (docs/pi-deploy.md): run on the Pi against the real database.
Exit 0 = nothing uses them, the removal commit can go in. Exit 1 = some rows or
the chat memory still do: keep the legacy code and report the counts.

SQLModel stores an enum by its NAME, so a row left with a removed member makes
every read of that table fail with LookupError. That is why this runs first.
Read-only: the database opens with mode=ro and nothing is written.

    .venv/bin/python scripts/count_legacy.py [--db storage/portfolio.db]
"""

import argparse
import sqlite3
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# (table, column, enum NAME as stored, what it was)
CHECKS = (
    ("chat_message", "channel", "TELEGRAM", "ChatChannel.TELEGRAM (mensagens do bot)"),
    ("cashflow_entry", "source", "BOT", "CashflowSource.BOT (lançamentos do bot)"),
    ("contribution_prompt", "prompt_key", "RESEARCH", "PromptKey.RESEARCH (aporte pré-split)"),
)


def count_rows(db: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        out: dict[str, int] = {}
        for table, column, name, label in CHECKS:
            # name or value, any case: robust to how an old version wrote it
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE upper({column}) = ?",  # noqa: S608 — constants above
                (name,),
            ).fetchone()
            out[label] = int(row[0])
        return out
    finally:
        conn.close()


def memory_is_legacy_seed(memory: Path) -> bool:
    """True if the consultant's MEMORY.md is still an untouched OLD seed."""
    if not memory.exists():
        return False
    sys.path.insert(0, str(_PROJECT_ROOT))
    from app.services import chat_service

    seeds = getattr(chat_service, "_LEGACY_CHAT_MEMORY_SEEDS", ())
    return memory.read_text(encoding="utf-8") in seeds


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=_PROJECT_ROOT / "storage" / "portfolio.db")
    parser.add_argument(
        "--memory",
        type=Path,
        default=_PROJECT_ROOT / "storage" / "chat_workspace" / "MEMORY.md",
    )
    args = parser.parse_args()
    if not args.db.is_file():
        print(f"erro: banco não encontrado em {args.db}", file=sys.stderr)
        return 2

    counts = count_rows(args.db)
    legacy_memory = memory_is_legacy_seed(args.memory)
    for label, n in counts.items():
        print(f"{n:6d}  {label}")
    print(f"{int(legacy_memory):6d}  MEMORY.md do consultor igual a uma semente antiga")

    if any(counts.values()) or legacy_memory:
        print("NÃO remova o legado: ainda há uso (acima).")
        return 1
    print("ok: nada usa o legado; o commit de remoção pode entrar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
