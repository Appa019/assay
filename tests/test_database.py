from sqlalchemy import create_engine

from app.core.database import _ensure_sqlite_columns


def test_added_columns_are_patched_in(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'mig.db'}")
    with engine.begin() as conn:
        # Pre-split schema: contribution without the columns added later.
        conn.exec_driver_sql("CREATE TABLE contribution (id TEXT PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE asset (id TEXT PRIMARY KEY)")
    _ensure_sqlite_columns(engine)
    with engine.begin() as conn:
        contribution_cols = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(contribution)")
        }
        asset_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(asset)")}
    assert {"claude_session_id", "run_attempts"} <= contribution_cols
    assert {"thesis", "target_price", "stop_price"} <= asset_cols
    # Idempotent: a second run must not raise on existing columns.
    _ensure_sqlite_columns(engine)
    engine.dispose()
