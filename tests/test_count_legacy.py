"""scripts/count_legacy.py: the migration gate for removing the legacy enum members."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import count_legacy  # noqa: E402

from app.services import chat_service  # noqa: E402


def _db(path: Path, rows: dict[str, list[str]]) -> Path:
    conn = sqlite3.connect(path)
    for table, column, *_ in count_legacy.CHECKS:
        conn.execute(f"CREATE TABLE {table} ({column} TEXT)")
        conn.executemany(f"INSERT INTO {table} VALUES (?)", [(v,) for v in rows.get(table, [])])
    conn.commit()
    conn.close()
    return path


def _run(monkeypatch: pytest.MonkeyPatch, db: Path, memory: Path) -> int:
    monkeypatch.setattr(sys, "argv", ["count_legacy.py", "--db", str(db), "--memory", str(memory)])
    return count_legacy.main()


def test_clean_database_allows_the_removal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(
        tmp_path / "p.db",
        {
            "chat_message": ["WEB"],
            "cashflow_entry": ["CHAT", "API"],
            "contribution_prompt": ["MACRO"],
        },
    )
    memory = tmp_path / "MEMORY.md"
    memory.write_text("# memória escrita pelo consultor\n")
    assert _run(monkeypatch, db, memory) == 0


@pytest.mark.parametrize(
    ("table", "value"),
    [
        ("chat_message", "TELEGRAM"),
        ("cashflow_entry", "BOT"),
        ("contribution_prompt", "RESEARCH"),
        ("cashflow_entry", "bot"),  # value instead of name: still counted
    ],
)
def test_any_legacy_row_blocks_the_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, table: str, value: str
) -> None:
    db = _db(tmp_path / "p.db", {table: [value]})
    assert sum(count_legacy.count_rows(db).values()) == 1
    assert _run(monkeypatch, db, tmp_path / "absent.md") == 1


def test_untouched_old_memory_seed_blocks_the_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory = tmp_path / "MEMORY.md"
    memory.write_text(chat_service._LEGACY_CHAT_MEMORY_SEEDS[0], encoding="utf-8")
    assert _run(monkeypatch, _db(tmp_path / "p.db", {}), memory) == 1


def test_never_writes_to_the_database(tmp_path: Path) -> None:
    db = _db(tmp_path / "p.db", {"chat_message": ["TELEGRAM"]})
    before = db.read_bytes()
    count_legacy.count_rows(db)
    assert db.read_bytes() == before
    assert not (tmp_path / "p.db-wal").exists()


def test_missing_database_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run(monkeypatch, tmp_path / "nope.db", tmp_path / "m.md") == 2
