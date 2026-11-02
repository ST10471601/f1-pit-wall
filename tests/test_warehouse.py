import sys
from pathlib import Path

import duckdb
import pytest

from pitwall.config import Settings, load_settings
from pitwall.transform.warehouse import WarehouseBuildError, build_warehouse
from pitwall.validation.silver import DATASETS, build_silver
from tests.conftest import FIXTURE_RUN_ID, FIXTURE_SESSION_KEY, REPO_CONFIG, unpack_fixture


@pytest.fixture
def settings(repo_dbt_project: None) -> Settings:
    return load_settings(REPO_CONFIG)


def _fixture_silver(settings: Settings) -> None:
    unpack_fixture(settings.bronze_dir)
    for dataset in DATASETS:
        build_silver(
            dataset,
            FIXTURE_SESSION_KEY,
            FIXTURE_RUN_ID,
            bronze_dir=settings.bronze_dir,
            silver_dir=settings.silver_dir,
        )


def _counts(settings: Settings) -> dict[str, int]:
    tables = ["dim_session", "dim_driver_session", "fact_lap", "mart_driver_race_pace"]
    with duckdb.connect(str(settings.warehouse_db), read_only=True) as warehouse:
        return {
            table: warehouse.execute(f"SELECT count(*) FROM {table}").fetchall()[0][0]
            for table in tables
        }


@pytest.mark.integration
def test_fixture_race_builds_and_a_rerun_gives_the_same_tables(settings: Settings) -> None:
    _fixture_silver(settings)

    build_warehouse(settings, "R1", FIXTURE_SESSION_KEY)
    first = _counts(settings)
    build_warehouse(settings, "R2", FIXTURE_SESSION_KEY)

    assert first == {
        "dim_session": 1,
        "dim_driver_session": 20,
        "fact_lap": 1286,
        "mart_driver_race_pace": 20,
    }
    assert _counts(settings) == first
    with duckdb.connect(str(settings.warehouse_db), read_only=True) as warehouse:
        best = warehouse.execute(
            "SELECT name_acronym, race_pace_gap_seconds FROM mart_driver_race_pace"
            " ORDER BY race_pace_seconds LIMIT 1"
        ).fetchone()
        fastest = warehouse.execute(
            "SELECT name_acronym, fastest_lap_seconds FROM mart_driver_race_pace"
            " ORDER BY fastest_lap_seconds LIMIT 1"
        ).fetchone()
    # Verstappen won Mexico City 2023 on pace; Hamilton set the fastest lap, 1:21.334.
    assert best == ("VER", 0.0)
    assert fastest == ("HAM", 81.334)


@pytest.mark.integration
def test_failed_build_raises_with_the_log_location(settings: Settings) -> None:
    # No silver files, so the staging views cannot read their sources.
    with pytest.raises(WarehouseBuildError, match=r"session 9181 exited with \d.*dbt\.log"):
        build_warehouse(settings, "R1", FIXTURE_SESSION_KEY)


def test_missing_dbt_is_reported(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))

    with pytest.raises(WarehouseBuildError, match="dbt is not installed"):
        build_warehouse(settings, "R1", FIXTURE_SESSION_KEY)
