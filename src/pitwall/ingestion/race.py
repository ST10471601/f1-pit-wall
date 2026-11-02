import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
from pydantic import AwareDatetime, BaseModel, ValidationError

from pitwall.ingestion.bronze import write_bronze
from pitwall.ingestion.openf1 import ApiResponse, OpenF1Client, OpenF1Error, OpenF1HTTPError
from pitwall.ops import IngestionLogEntry, record_ingestion

log = logging.getLogger(__name__)

# Fetched after the session record has shown the session is a finished race.
RACE_ENDPOINTS = ("drivers", "laps")


class SessionNotEligibleError(Exception):
    """The session is missing, malformed, not a race, cancelled or not settled yet."""


class _SessionRecord(BaseModel):
    # Only the fields that decide eligibility; silver validates the whole record.
    session_key: int
    session_name: str
    date_end: AwareDatetime
    is_cancelled: bool


@dataclass(frozen=True)
class IngestionRun:
    """What every fetch in one pipeline run shares."""

    run_id: str
    client: OpenF1Client
    ops: duckdb.DuckDBPyConnection
    bronze_dir: Path
    now: Callable[[], datetime]


def ingest_race(
    run: IngestionRun, session_key: int, *, as_of: datetime, settle_delay: timedelta
) -> None:
    """Ingest a finished race session: its session record, drivers and laps."""
    sessions = ingest_endpoint(run, "sessions", session_key)
    _check_eligible(sessions.records, session_key, as_of, settle_delay)
    for endpoint in RACE_ENDPOINTS:
        ingest_endpoint(run, endpoint, session_key)


def ingest_endpoint(run: IngestionRun, endpoint: str, session_key: int) -> ApiResponse:
    """Fetch one endpoint for a session into bronze and log the outcome, failures included."""
    params: dict[str, str | int] = {"session_key": session_key}
    try:
        response = run.client.get(endpoint, params)
    except OpenF1Error as exc:
        record_ingestion(
            run.ops,
            IngestionLogEntry(
                run_id=run.run_id,
                endpoint=endpoint,
                session_key=session_key,
                params=params,
                status="failed",
                http_status=exc.status_code if isinstance(exc, OpenF1HTTPError) else None,
                record_count=None,
                payload_sha256=None,
                payload_bytes=None,
                attempts=exc.attempts,
                bronze_path=None,
                error=str(exc),
                ingested_at=run.now(),
            ),
        )
        raise

    run_dir, metadata = write_bronze(
        run.bronze_dir,
        response,
        session_key=session_key,
        run_id=run.run_id,
        ingested_at=run.now(),
    )
    record_ingestion(
        run.ops,
        IngestionLogEntry(
            run_id=run.run_id,
            endpoint=endpoint,
            session_key=session_key,
            params=params,
            status=metadata.status,
            http_status=metadata.http_status,
            record_count=metadata.record_count,
            payload_sha256=metadata.payload_sha256,
            payload_bytes=metadata.payload_bytes,
            attempts=metadata.attempts,
            bronze_path=run_dir.relative_to(run.bronze_dir).as_posix(),
            error=None,
            ingested_at=metadata.ingested_at,
        ),
    )
    log.log(
        logging.WARNING if metadata.status == "empty" else logging.INFO,
        "ingested",
        extra={
            "endpoint": endpoint,
            "session_key": session_key,
            "status": metadata.status,
            "records": metadata.record_count,
        },
    )
    return response


def _check_eligible(
    records: list[dict[str, Any]], session_key: int, as_of: datetime, settle_delay: timedelta
) -> None:
    if not records:
        raise SessionNotEligibleError(f"session {session_key} not found")
    if len(records) > 1:
        raise SessionNotEligibleError(
            f"session {session_key} returned {len(records)} session records, expected 1"
        )
    try:
        session = _SessionRecord.model_validate(records[0])
    except ValidationError as exc:
        raise SessionNotEligibleError(f"session {session_key} record is invalid: {exc}") from exc

    # Sprints are typed as Race sessions too; only the name tells a Grand Prix race apart.
    if session.session_name != "Race":
        raise SessionNotEligibleError(
            f"session {session_key} is a {session.session_name!r} session, not a 'Race'"
        )
    if session.is_cancelled:
        raise SessionNotEligibleError(f"session {session_key} was cancelled")
    if session.date_end > as_of - settle_delay:
        raise SessionNotEligibleError(
            f"session {session_key} ended at {session.date_end.isoformat()}, "
            f"less than {settle_delay} before {as_of.isoformat()}"
        )
