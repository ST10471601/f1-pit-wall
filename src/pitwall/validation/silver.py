import json
import logging
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import ValidationError

from pitwall.ingestion.bronze import METADATA_FILE, PAYLOAD_FILE, BronzeMetadata, bronze_run_dir
from pitwall.validation.schemas import (
    DriverRecord,
    LapRecord,
    SessionRecord,
    SilverRecord,
    arrow_schema,
)

log = logging.getLogger(__name__)

SILVER_FILE = "data.parquet"
DATASETS: dict[str, type[SilverRecord]] = {
    "sessions": SessionRecord,
    "drivers": DriverRecord,
    "laps": LapRecord,
}
# Added to every row so each silver row traces back to the bronze payload it came from.
_LINEAGE = [
    pa.field("run_id", pa.string(), nullable=False),
    pa.field("ingested_at", pa.timestamp("us", tz="UTC"), nullable=False),
]
_SCHEMAS = {name: pa.schema([*arrow_schema(model), *_LINEAGE]) for name, model in DATASETS.items()}
_PROBLEMS_SHOWN = 5


class SilverValidationError(Exception):
    """A bronze payload broke its dataset's contract; the silver partition was left as it was."""

    def __init__(self, dataset: str, session_key: int, problems: list[str]) -> None:
        shown = "; ".join(problems[:_PROBLEMS_SHOWN])
        hidden = len(problems) - _PROBLEMS_SHOWN
        more = f" (+{hidden} more)" if hidden > 0 else ""
        super().__init__(
            f"{dataset} for session {session_key}: {len(problems)} problem(s): {shown}{more}"
        )
        self.dataset = dataset
        self.session_key = session_key
        self.problems = problems


def silver_path(silver_dir: Path, dataset: str, session_key: int) -> Path:
    return silver_dir / dataset / f"session_key={session_key}" / SILVER_FILE


def build_silver(
    dataset: str, session_key: int, run_id: str, *, bronze_dir: Path, silver_dir: Path
) -> Path:
    """Validate this run's bronze payload and replace the dataset's silver partition with it."""
    source = bronze_run_dir(bronze_dir, dataset, session_key, run_id)
    metadata = BronzeMetadata.model_validate_json((source / METADATA_FILE).read_bytes())
    # An empty payload is OpenF1's "no results" body, not a list of records.
    records = (
        _validate(dataset, session_key, (source / PAYLOAD_FILE).read_bytes())
        if metadata.status == "ok"
        else []
    )
    lineage = {"run_id": run_id, "ingested_at": metadata.ingested_at}
    table = pa.Table.from_pylist(
        [record.model_dump() | lineage for record in records], schema=_SCHEMAS[dataset]
    )
    target = silver_path(silver_dir, dataset, session_key)
    _write_atomic(table, target)
    log.info(
        "silver written",
        extra={"dataset": dataset, "session_key": session_key, "rows": table.num_rows},
    )
    return target


def _validate(dataset: str, session_key: int, payload: bytes) -> list[SilverRecord]:
    rows = json.loads(payload)
    if not isinstance(rows, list):
        raise SilverValidationError(dataset, session_key, ["payload is not a JSON list"])

    model = DATASETS[dataset]
    records: list[SilverRecord] = []
    problems: list[str] = []
    for index, row in enumerate(rows):
        try:
            record = model.model_validate(row)
        except ValidationError as exc:
            problems += [
                f"record {index} {'.'.join(map(str, error['loc']))}: {error['msg']}"
                for error in exc.errors()
            ]
            continue
        # The partition is per session, so a stray row would silently join the wrong race.
        if record.session_key != session_key:
            problems.append(f"record {index} session_key: {record.session_key}")
        records.append(record)

    if problems:
        raise SilverValidationError(dataset, session_key, problems)
    return records


def _write_atomic(table: pa.Table, path: Path) -> None:
    # Readers only ever see the old file or the new one. A .tmp left by a killed run is
    # overwritten the next time this partition is written, and readers never match it.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, path)
