from collections.abc import Iterator
from pathlib import Path

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


# Columns added after the initial schema shipped. SQLite has no migration tool
# here and create_all() won't add columns to an existing table, so patch them in.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "contribution": {"claude_session_id": "TEXT"},
}


def _ensure_sqlite_columns() -> None:
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
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
