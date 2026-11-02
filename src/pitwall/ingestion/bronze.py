import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from pitwall.ingestion.openf1 import ApiResponse

PAYLOAD_FILE = "payload.json"
METADATA_FILE = "metadata.json"


class BronzeMetadata(BaseModel):
    """What was fetched, when and how, written beside each payload as metadata.json."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    endpoint: str
    session_key: int
    params: dict[str, str | int]
    url: str
    http_status: int
    status: Literal["ok", "empty"]
    record_count: int
    payload_sha256: str
    payload_bytes: int
    attempts: int
    ingested_at: AwareDatetime


def bronze_run_dir(bronze_dir: Path, endpoint: str, session_key: int, run_id: str) -> Path:
    return bronze_dir / endpoint / f"session_key={session_key}" / f"run_id={run_id}"


def write_bronze(
    bronze_dir: Path,
    response: ApiResponse,
    *,
    session_key: int,
    run_id: str,
    ingested_at: datetime,
) -> tuple[Path, BronzeMetadata]:
    """Store the response body unchanged as payload.json, then its metadata.json."""
    run_dir = bronze_run_dir(bronze_dir, response.endpoint, session_key, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    metadata = BronzeMetadata(
        run_id=run_id,
        endpoint=response.endpoint,
        session_key=session_key,
        params=response.params,
        url=response.url,
        http_status=response.status_code,
        status="ok" if response.records else "empty",
        record_count=len(response.records),
        payload_sha256=hashlib.sha256(response.body).hexdigest(),
        payload_bytes=len(response.body),
        attempts=response.attempts,
        ingested_at=ingested_at,
    )
    _write_atomic(run_dir / PAYLOAD_FILE, response.body)
    # Written last: a run directory without metadata.json is an interrupted write.
    _write_atomic(run_dir / METADATA_FILE, metadata.model_dump_json(indent=2).encode())
    return run_dir, metadata


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
