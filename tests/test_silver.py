import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pitwall.ingestion.bronze import write_bronze
from pitwall.ingestion.openf1 import ApiResponse
from pitwall.ingestion.race import RACE_ENDPOINTS
from pitwall.validation.silver import DATASETS, SilverValidationError, build_silver
from tests.records import DRIVER, LAP, SESSION

INGESTED_AT = datetime(2026, 11, 2, 8, 0, 5, tzinfo=UTC)


def _bronze(
    root: Path, endpoint: str, run_id: str, records: list[Any], body: bytes | None = None
) -> None:
    body = json.dumps(records).encode() if body is None else body
    response = ApiResponse(
        endpoint=endpoint,
        params={"session_key": 9158},
        url=f"https://api.openf1.org/v1/{endpoint}?session_key=9158",
        status_code=200 if records else 404,
        body=body,
        records=records,
        attempts=1,
    )
    write_bronze(
        root / "bronze", response, session_key=9158, run_id=run_id, ingested_at=INGESTED_AT
    )


def _build(root: Path, dataset: str, run_id: str) -> Path:
    return build_silver(
        dataset, 9158, run_id, bronze_dir=root / "bronze", silver_dir=root / "silver"
    )


@pytest.mark.parametrize(
    ("dataset", "record"), [("sessions", SESSION), ("drivers", DRIVER), ("laps", LAP)]
)
def test_valid_payload_becomes_a_typed_silver_partition(
    tmp_path: Path, dataset: str, record: dict[str, Any]
) -> None:
    _bronze(tmp_path, dataset, "R1", [record])

    path = _build(tmp_path, dataset, "R1")

    assert path == tmp_path / "silver" / dataset / "session_key=9158" / "data.parquet"
    assert sorted(p.name for p in path.parent.iterdir()) == ["data.parquet"]
    table = pq.read_table(path)
    assert table.schema.names == [*DATASETS[dataset].model_fields, "run_id", "ingested_at"]
    (row,) = table.to_pylist()
    assert row["session_key"] == 9158
    assert row["run_id"] == "R1"
    assert row["ingested_at"] == INGESTED_AT


def test_laps_keep_their_types_and_utc_timestamps(tmp_path: Path) -> None:
    _bronze(tmp_path, "laps", "R1", [LAP | {"date_start": "2023-09-16T21:59:07.606+08:00"}])

    table = pq.read_table(_build(tmp_path, "laps", "R1"))

    assert table.schema.field("date_start").type == pa.timestamp("us", tz="UTC")
    assert table.schema.field("lap_number").type == pa.int64()
    assert not table.schema.field("lap_number").nullable
    (row,) = table.to_pylist()
    assert row["date_start"] == datetime(2023, 9, 16, 13, 59, 7, 606000, tzinfo=UTC)
    assert row["segments_sector_2"] == [2049, None]


def test_empty_result_gives_an_empty_partition_with_the_full_schema(tmp_path: Path) -> None:
    _bronze(tmp_path, "laps", "R1", [], body=b'{"detail": "No results found."}')

    table = pq.read_table(_build(tmp_path, "laps", "R1"))

    assert table.num_rows == 0
    assert table.schema.names[-2:] == ["run_id", "ingested_at"]


def test_a_later_run_replaces_the_partition(tmp_path: Path) -> None:
    _bronze(tmp_path, "laps", "R1", [LAP, LAP | {"lap_number": 9}])
    _bronze(tmp_path, "laps", "R2", [LAP])
    _build(tmp_path, "laps", "R1")

    rows = pq.read_table(_build(tmp_path, "laps", "R2")).to_pylist()

    assert [(row["lap_number"], row["run_id"]) for row in rows] == [(8, "R2")]


def test_invalid_records_fail_and_leave_the_partition_as_it_was(tmp_path: Path) -> None:
    _bronze(tmp_path, "laps", "R1", [LAP])
    _bronze(tmp_path, "laps", "R2", [LAP, LAP | {"lap_number": "9"}])
    path = _build(tmp_path, "laps", "R1")

    with pytest.raises(SilverValidationError) as exc:
        _build(tmp_path, "laps", "R2")

    assert exc.value.problems == ["record 1 lap_number: Input should be a valid integer"]
    assert pq.read_table(path).column("run_id").to_pylist() == ["R1"]
    assert sorted(p.name for p in path.parent.iterdir()) == ["data.parquet"]


def test_record_from_another_session_is_rejected(tmp_path: Path) -> None:
    _bronze(tmp_path, "drivers", "R1", [DRIVER, DRIVER | {"session_key": 9165}])

    with pytest.raises(SilverValidationError, match="record 1 session_key: 9165"):
        _build(tmp_path, "drivers", "R1")


def test_payload_that_is_not_a_list_is_rejected(tmp_path: Path) -> None:
    _bronze(tmp_path, "laps", "R1", [LAP], body=b'{"lap_number": 8}')

    with pytest.raises(SilverValidationError, match="payload is not a JSON list"):
        _build(tmp_path, "laps", "R1")


def test_error_message_shows_the_first_problems_and_counts_the_rest(tmp_path: Path) -> None:
    _bronze(tmp_path, "laps", "R1", [LAP | {"lap_number": None}] * 7)

    with pytest.raises(SilverValidationError) as exc:
        _build(tmp_path, "laps", "R1")

    message = str(exc.value)
    assert message.startswith("laps for session 9158: 7 problem(s): record 0 lap_number")
    assert message.endswith("(+2 more)")


def test_every_ingested_endpoint_has_a_silver_contract() -> None:
    assert set(DATASETS) == {"sessions", *RACE_ENDPOINTS}
