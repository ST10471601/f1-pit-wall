from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest

from pitwall.config import DuckDBSettings
from pitwall.ops import IngestionLogEntry, connect_ops, record_ingestion

SETTINGS = DuckDBSettings(threads=1, memory_limit="256MB")


ENTRY = IngestionLogEntry(
    run_id="20261102T080000Z-abc123",
    endpoint="laps",
    session_key=9158,
    params={"session_key": 9158},
    status="ok",
    http_status=200,
    record_count=1200,
    payload_sha256="ab" * 32,
    payload_bytes=250_000,
    attempts=1,
    bronze_path="laps/session_key=9158/run_id=20261102T080000Z-abc123",
    error=None,
    ingested_at=datetime(2026, 11, 2, 8, 0, 5, tzinfo=UTC),
)


@pytest.fixture
def ops(tmp_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    with connect_ops(tmp_path / "data" / "ops.duckdb", SETTINGS) as conn:
        yield conn


def test_entry_is_stored_with_params_as_json_and_time_in_utc(
    ops: duckdb.DuckDBPyConnection,
) -> None:
    sast = timezone(timedelta(hours=2))
    record_ingestion(ops, replace(ENTRY, ingested_at=datetime(2026, 11, 2, 10, 0, 5, tzinfo=sast)))

    row = ops.execute(
        "SELECT params->>'session_key', status, record_count, ingested_at::VARCHAR"
        " FROM ingestion_log"
    ).fetchone()

    assert row == ("9158", "ok", 1200, "2026-11-02 08:00:05+00")


def test_failure_is_recorded_without_payload_columns(ops: duckdb.DuckDBPyConnection) -> None:
    failed = replace(
        ENTRY,
        status="failed",
        http_status=None,
        record_count=None,
        payload_sha256=None,
        payload_bytes=None,
        bronze_path=None,
        attempts=6,
        error="ReadTimeout (laps {'session_key': 9158}, attempts=6)",
    )

    record_ingestion(ops, failed)

    assert ops.execute("SELECT status, attempts, error FROM ingestion_log").fetchone() == (
        "failed",
        6,
        failed.error,
    )


def test_one_row_per_run_endpoint_and_session(ops: duckdb.DuckDBPyConnection) -> None:
    record_ingestion(ops, ENTRY)

    with pytest.raises(duckdb.ConstraintException):
        record_ingestion(ops, ENTRY)


def test_reopening_keeps_existing_rows(tmp_path: Path) -> None:
    path = tmp_path / "ops.duckdb"
    with connect_ops(path, SETTINGS) as conn:
        record_ingestion(conn, ENTRY)

    with connect_ops(path, SETTINGS) as conn:
        assert conn.execute("SELECT count(*) FROM ingestion_log").fetchone() == (1,)
