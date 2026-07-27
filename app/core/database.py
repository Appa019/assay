from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

# Resolve relative paths against the project root (parent of /app), not the
# current working directory — uvicorn may be launched from anywhere.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_raw_path = Path(settings.sqlite_path).expanduser()
if not _raw_path.is_absolute():
    _raw_path = _PROJECT_ROOT / _raw_path
_db_path = _raw_path.resolve()
_db_path.parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{_db_path}"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    """Per-connection PRAGMAs.

    The API, the Telegram bot and three cron scripts all write to this one
    file: WAL allows concurrent readers during a write, busy_timeout makes
    writers wait instead of failing with "database is locked", and NORMAL
    sync is the recommended (safe) pairing with WAL.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# Columns added after the initial schema shipped. SQLite has no migration tool
# here and create_all() won't add columns to an existing table, so patch them in.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "contribution": {
        "claude_session_id": "TEXT",
        "run_attempts": "INTEGER NOT NULL DEFAULT 0",
    },
    "contribution_prompt": {
        "cost_usd": "REAL",
        "duration_s": "REAL",
        "num_turns": "INTEGER",
    },
    "asset": {
        "thesis": "TEXT",
        "target_price": "NUMERIC",
        "stop_price": "NUMERIC",
    },
}


def _ensure_sqlite_columns(target_engine: Any = None) -> None:
    target_engine = target_engine if target_engine is not None else engine
    with target_engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if not existing:  # table not created yet — create_all will handle it
                continue
            for name, ddl in columns.items():
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def init_db() -> None:
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _ensure_sqlite_columns()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
