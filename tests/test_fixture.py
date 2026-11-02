import hashlib
from pathlib import Path

import pyarrow.parquet as pq

from pitwall.ingestion.bronze import BronzeMetadata
from pitwall.validation.silver import DATASETS, build_silver
from tests.conftest import FIXTURE_RUN_ID, FIXTURE_SESSION_KEY, unpack_fixture


def test_fixture_payloads_match_their_recorded_hashes(tmp_path: Path) -> None:
    unpack_fixture(tmp_path)

    payloads = sorted(tmp_path.rglob("payload.json"))
    assert len(payloads) == len(DATASETS)
    for payload in payloads:
        metadata = BronzeMetadata.model_validate_json(
            payload.with_name("metadata.json").read_text()
        )
        assert hashlib.sha256(payload.read_bytes()).hexdigest() == metadata.payload_sha256


def test_fixture_race_passes_the_silver_contracts(tmp_path: Path) -> None:
    unpack_fixture(tmp_path / "bronze")

    rows = {
        dataset: pq.read_metadata(
            build_silver(
                dataset,
                FIXTURE_SESSION_KEY,
                FIXTURE_RUN_ID,
                bronze_dir=tmp_path / "bronze",
                silver_dir=tmp_path / "silver",
            )
        ).num_rows
        for dataset in DATASETS
    }

    assert rows == {"sessions": 1, "drivers": 20, "laps": 1286}
