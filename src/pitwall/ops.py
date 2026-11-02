import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import duckdb

from pitwall.config import DuckDBSettings

IngestionStatus = Literal["ok", "empty", "failed"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingestion_log (
    run_id         VARCHAR     NOT NULL,
    endpoint       VARCHAR     NOT NULL,
    session_key    INTEGER     NOT NULL,
    params         JSON        NOT NULL,
    status         VARCHAR     NOT NULL CHECK (status IN ('ok', 'empty', 'failed')),
    http_status    INTEGER,
    record_count   INTEGER,
    payload_sha256 VARCHAR,
    payload_bytes  BIGINT,
    attempts       INTEGER     NOT NULL,
    bronze_path    VARCHAR,
    error          VARCHAR,
    ingested_at    TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, endpoint, session_key)
);
"""

_INSERT_INGESTION = """
INSERT INTO ingestion_log (
    run_id, endpoint, session_key, params, status, http_status, record_count,
    payload_sha256, payload_bytes, attempts, bronze_path, error, ingested_at
) VALUES (
    $run_id, $endpoint, $session_key, $params, $status, $http_status, $record_count,
    $payload_sha256, $payload_bytes, $attempts, $bronze_path, $error, $ingested_at
)
"""


@dataclass(frozen=True)
class IngestionLogEntry:
    """One fetch outcome; the columns that don't apply to a failure are None."""

    run_id: str
    endpoint: str
    session_key: int
    params: dict[str, str | int]
    status: IngestionStatus
    http_status: int | None
    record_count: int | None
    payload_sha256: str | None
    payload_bytes: int | None
    attempts: int
    bronze_path: str | None
    error: str | None
    ingested_at: datetime


def connect_ops(path: Path, settings: DuckDBSettings) -> duckdb.DuckDBPyConnection:
    """Open ops.duckdb for writing, creating the file and its tables if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(
        str(path),
        config={
            "threads": settings.threads,
            "memory_limit": settings.memory_limit,
            # Show and cast TIMESTAMPTZ in UTC whatever the machine's time zone is.
            "TimeZone": "UTC",
        },
    )
    conn.execute(_SCHEMA)
    return conn


def record_ingestion(conn: duckdb.DuckDBPyConnection, entry: IngestionLogEntry) -> None:
    conn.execute(_INSERT_INGESTION, asdict(entry) | {"params": json.dumps(entry.params)})
