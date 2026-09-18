import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError

from app.core.database import _ensure_sqlite_columns


def test_added_columns_are_patched_in(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'mig.db'}")
    with engine.begin() as conn:
        # Pre-split schema: contribution without the columns added later.
        conn.exec_driver_sql("CREATE TABLE contribution (id TEXT PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE asset (id TEXT PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE cashflow_entry (id TEXT PRIMARY KEY)")
    _ensure_sqlite_columns(engine)
    with engine.begin() as conn:
        contribution_cols = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(contribution)")
        }
        asset_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(asset)")}
        cashflow_cols = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(cashflow_entry)")
        }
    assert {"claude_session_id", "run_attempts"} <= contribution_cols
    assert {"thesis", "target_price", "stop_price"} <= asset_cols
    assert "wallet" in cashflow_cols
    # Idempotent: a second run must not raise on existing columns.
    _ensure_sqlite_columns(engine)
    engine.dispose()


def test_card_columns_are_patched_in_with_fk_on(tmp_path) -> None:
    """The four card/installment columns land on an old ledger table, and the
    REFERENCES clause on card_id is enforced once foreign keys are on."""
    engine = create_engine(f"sqlite:///{tmp_path / 'mig.db'}")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _record):  # noqa: ANN001
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as conn:
        # create_all() runs before the column patch, so the parent exists.
        conn.exec_driver_sql("CREATE TABLE credit_card (id CHAR(32) PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE cashflow_entry (id TEXT PRIMARY KEY)")
    _ensure_sqlite_columns(engine)
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(cashflow_entry)")}
        assert {"card_id", "installment_no", "installment_count", "installment_group"} <= cols
        conn.exec_driver_sql("INSERT INTO credit_card (id) VALUES ('c1')")
        conn.exec_driver_sql("INSERT INTO cashflow_entry (id, card_id) VALUES ('e1', 'c1')")
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO cashflow_entry (id, card_id) VALUES ('e2', 'zz')")
    engine.dispose()


def test_step_telemetry_columns_land_on_an_old_prompt_table(tmp_path) -> None:
    """`context_tokens` joins the per-step telemetry: cost alone never said
    whether a step got expensive from thinking harder or from carrying more."""
    engine = create_engine(f"sqlite:///{tmp_path / 'mig.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE contribution_prompt (id TEXT PRIMARY KEY)")
    _ensure_sqlite_columns(engine)
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(contribution_prompt)")}
    assert {"cost_usd", "duration_s", "num_turns", "context_tokens"} <= cols
    engine.dispose()
