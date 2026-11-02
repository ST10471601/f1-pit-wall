import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pitwall.ingestion.bronze import BronzeMetadata, write_bronze
from pitwall.ingestion.openf1 import ApiResponse

INGESTED_AT = datetime(2026, 11, 2, 8, 0, 1, tzinfo=UTC)


def _response(body: bytes, status_code: int = 200) -> ApiResponse:
    records = json.loads(body) if status_code == 200 else []
    return ApiResponse(
        endpoint="laps",
        params={"session_key": 9158},
        url="https://api.openf1.org/v1/laps?session_key=9158",
        status_code=status_code,
        body=body,
        records=records,
        attempts=2,
    )


def test_payload_is_stored_byte_for_byte_with_its_metadata(tmp_path: Path) -> None:
    body = b'[{"lap_number": 1,  "lap_duration": null}]'

    run_dir, metadata = write_bronze(
        tmp_path, _response(body), session_key=9158, run_id="R1", ingested_at=INGESTED_AT
    )

    assert run_dir == tmp_path / "laps" / "session_key=9158" / "run_id=R1"
    assert (run_dir / "payload.json").read_bytes() == body
    assert sorted(p.name for p in run_dir.iterdir()) == ["metadata.json", "payload.json"]
    stored = BronzeMetadata.model_validate_json((run_dir / "metadata.json").read_text())
    assert stored == metadata
    assert stored.status == "ok"
    assert stored.record_count == 1
    assert stored.payload_sha256 == hashlib.sha256(body).hexdigest()
    assert stored.payload_bytes == len(body)
    assert stored.attempts == 2
    assert stored.params == {"session_key": 9158}
    assert stored.ingested_at == INGESTED_AT


def test_no_results_is_stored_as_received_and_marked_empty(tmp_path: Path) -> None:
    body = b'{"detail": "No results found."}'

    run_dir, metadata = write_bronze(
        tmp_path, _response(body, 404), session_key=9158, run_id="R1", ingested_at=INGESTED_AT
    )

    assert (run_dir / "payload.json").read_bytes() == body
    assert metadata.status == "empty"
    assert metadata.record_count == 0
    assert metadata.http_status == 404


def test_each_run_gets_its_own_directory(tmp_path: Path) -> None:
    for run_id in ("R1", "R2"):
        write_bronze(
            tmp_path, _response(b"[]"), session_key=9158, run_id=run_id, ingested_at=INGESTED_AT
        )

    runs = sorted(p.name for p in (tmp_path / "laps" / "session_key=9158").iterdir())
    assert runs == ["run_id=R1", "run_id=R2"]
