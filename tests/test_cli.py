import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import duckdb
import pytest
import responses

from pitwall.cli import EXIT_FAILED, EXIT_OK, main
from tests.conftest import OPENF1_URL, REPO_CONFIG
from tests.records import DRIVER, LAP, SESSION


def _log_lines(stderr: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stderr.splitlines() if line.startswith("{")]


def test_help_lists_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "run" in out
    assert "release" in out


@pytest.mark.integration
def test_module_entry_point_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pitwall", "run", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--session" in result.stdout
    assert "--as-of" in result.stdout


def test_run_session_ingests_the_race_into_bronze_ops_and_silver(
    api: responses.RequestsMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api.get(f"{OPENF1_URL}/sessions", json=[SESSION])
    api.get(f"{OPENF1_URL}/drivers", json=[DRIVER])
    api.get(f"{OPENF1_URL}/laps", json=[LAP, LAP | {"lap_number": 9}])
    args = ["run", "--session", "9158", "--as-of", "2026-11-02T10:00+02:00"]

    code = main(["--config", str(REPO_CONFIG), *args])

    assert code == EXIT_OK
    lines = _log_lines(capsys.readouterr().err)
    started = next(line for line in lines if line["message"] == "run started")
    assert started["session_key"] == 9158
    assert started["as_of"] == "2026-11-02T08:00:00+00:00"
    assert lines[-1]["message"] == "run finished"
    run_ids = {line["run_id"] for line in lines}
    assert len(run_ids) == 1
    run_id = run_ids.pop()
    data = tmp_path / "data"
    for endpoint in ("sessions", "drivers", "laps"):
        assert (data / "bronze" / endpoint / "session_key=9158" / f"run_id={run_id}").is_dir()
    with duckdb.connect(str(data / "ops.duckdb"), read_only=True) as ops:
        rows = ops.execute("SELECT DISTINCT run_id, status FROM ingestion_log").fetchall()
    assert rows == [(run_id, "ok")]
    with duckdb.connect() as con:
        silver = con.execute(
            "SELECT count(*), any_value(run_id)"
            f" FROM read_parquet('{(data / 'silver').as_posix()}/laps/*/data.parquet')"
        ).fetchone()
    assert silver == (2, run_id)


def test_run_fails_when_a_payload_breaks_its_contract(
    api: responses.RequestsMock, capsys: pytest.CaptureFixture[str]
) -> None:
    api.get(f"{OPENF1_URL}/sessions", json=[SESSION])
    api.get(f"{OPENF1_URL}/drivers", json=[DRIVER])
    api.get(f"{OPENF1_URL}/laps", json=[LAP | {"lap_number": "8"}])

    code = main(["--config", str(REPO_CONFIG), "run", "--session", "9158"])

    assert code == EXIT_FAILED
    failed = _log_lines(capsys.readouterr().err)[-1]
    assert failed["message"] == "run failed"
    assert failed["error"].startswith("laps for session 9158: 1 problem(s)")


def test_run_fails_when_the_session_is_not_a_race(
    api: responses.RequestsMock, capsys: pytest.CaptureFixture[str]
) -> None:
    api.get(f"{OPENF1_URL}/sessions", json=[SESSION | {"session_name": "Sprint"}])

    code = main(["--config", str(REPO_CONFIG), "run", "--session", "9158"])

    assert code == EXIT_FAILED
    failed = _log_lines(capsys.readouterr().err)[-1]
    assert failed["message"] == "run failed"
    assert "'Sprint' session, not a 'Race'" in failed["error"]


def test_run_without_session_fails_until_run_selection_exists(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--config", str(REPO_CONFIG), "run"]) == EXIT_FAILED
    assert "pass --session KEY" in capsys.readouterr().err


def test_release_stub_fails_loudly() -> None:
    assert main(["--config", str(REPO_CONFIG), "release"]) == EXIT_FAILED


@pytest.mark.parametrize("value", ["2026-11-02T08:00:00", "yesterday"])
def test_as_of_rejects_naive_or_invalid_timestamps(value: str) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--config", str(REPO_CONFIG), "run", "--as-of", value])

    assert exc.value.code == 2


def test_missing_config_exits_with_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--config", "nope.yaml", "run"])

    assert exc.value.code == 2
    assert "config file not found" in capsys.readouterr().err
