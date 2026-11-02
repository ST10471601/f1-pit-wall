import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import requests
import responses
from responses import matchers

from pitwall.config import DuckDBSettings
from pitwall.ingestion.openf1 import OpenF1Client, OpenF1HTTPError, OpenF1UnavailableError
from pitwall.ingestion.race import IngestionRun, SessionNotEligibleError, ingest_race
from pitwall.ops import connect_ops
from tests.conftest import API_SETTINGS, OPENF1_URL, FakeClock

RUN_ID = "20261102T080000Z-abc123"
AS_OF = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)
SETTLE_DELAY = timedelta(hours=6)
SESSION: dict[str, Any] = {
    "session_key": 9158,
    "session_name": "Race",
    "session_type": "Race",
    "date_start": "2023-09-17T12:00:00+00:00",
    "date_end": "2023-09-17T14:00:00+00:00",
    "is_cancelled": False,
}
DRIVERS = [{"session_key": 9158, "driver_number": 55}, {"session_key": 9158, "driver_number": 4}]
LAPS = [{"session_key": 9158, "driver_number": 55, "lap_number": 1, "lap_duration": None}]


@pytest.fixture
def run(tmp_path: Path, clock: FakeClock) -> Iterator[IngestionRun]:
    with (
        OpenF1Client(API_SETTINGS, clock=clock, sleep=clock.sleep) as client,
        connect_ops(
            tmp_path / "ops.duckdb", DuckDBSettings(threads=1, memory_limit="256MB")
        ) as ops,
    ):
        yield IngestionRun(
            run_id=RUN_ID,
            client=client,
            ops=ops,
            bronze_dir=tmp_path / "bronze",
            now=lambda: datetime(2026, 11, 2, 8, 0, 5, tzinfo=UTC),
        )


def _register(api: responses.RequestsMock, endpoint: str, **kwargs: Any) -> None:
    api.get(
        f"{OPENF1_URL}/{endpoint}",
        match=[matchers.query_param_matcher({"session_key": "9158"})],
        **kwargs,
    )


def _ingest(run: IngestionRun) -> None:
    ingest_race(run, 9158, as_of=AS_OF, settle_delay=SETTLE_DELAY)


def _log(run: IngestionRun) -> dict[str, tuple[Any, ...]]:
    rows = run.ops.execute(
        "SELECT endpoint, status, record_count, http_status, attempts, bronze_path"
        " FROM ingestion_log WHERE run_id = ?",
        [RUN_ID],
    ).fetchall()
    return {row[0]: row[1:] for row in rows}


def test_race_is_ingested_into_bronze_and_logged(
    api: responses.RequestsMock, run: IngestionRun
) -> None:
    _register(api, "sessions", json=[SESSION])
    _register(api, "drivers", json=DRIVERS)
    _register(api, "laps", json=LAPS)

    _ingest(run)

    assert _log(run) == {
        endpoint: ("ok", count, 200, 1, f"{endpoint}/session_key=9158/run_id={RUN_ID}")
        for endpoint, count in [("sessions", 1), ("drivers", 2), ("laps", 1)]
    }
    laps_dir = run.bronze_dir / "laps" / "session_key=9158" / f"run_id={RUN_ID}"
    assert json.loads((laps_dir / "payload.json").read_bytes()) == LAPS


def test_session_that_ended_exactly_the_settle_delay_ago_is_eligible(
    api: responses.RequestsMock, run: IngestionRun
) -> None:
    _register(api, "sessions", json=[SESSION | {"date_end": "2026-11-02T02:00:00+00:00"}])
    _register(api, "drivers", json=DRIVERS)
    _register(api, "laps", json=LAPS)

    _ingest(run)

    assert set(_log(run)) == {"sessions", "drivers", "laps"}


def test_unknown_session_is_logged_as_empty_and_stops_the_race(
    api: responses.RequestsMock, run: IngestionRun
) -> None:
    _register(api, "sessions", json={"detail": "No results found."}, status=404)

    with pytest.raises(SessionNotEligibleError, match="session 9158 not found"):
        _ingest(run)

    assert _log(run) == {
        "sessions": ("empty", 0, 404, 1, f"sessions/session_key=9158/run_id={RUN_ID}")
    }


@pytest.mark.parametrize(
    ("records", "reason"),
    [
        ([SESSION | {"session_name": "Sprint"}], "'Sprint' session, not a 'Race'"),
        ([SESSION | {"is_cancelled": True}], "was cancelled"),
        (
            [SESSION | {"date_end": "2026-11-02T02:00:01+00:00"}],
            "less than 6:00:00 before 2026-11-02T08:00:00",
        ),
        ([SESSION, SESSION], "returned 2 session records"),
        ([{k: v for k, v in SESSION.items() if k != "date_end"}], "record is invalid"),
    ],
    ids=["sprint", "cancelled", "not-settled", "duplicate", "invalid"],
)
def test_ineligible_session_stops_before_drivers_and_laps(
    api: responses.RequestsMock, run: IngestionRun, records: list[dict[str, Any]], reason: str
) -> None:
    _register(api, "sessions", json=records)

    with pytest.raises(SessionNotEligibleError, match=reason):
        _ingest(run)

    assert list(_log(run)) == ["sessions"]


def test_http_failure_is_logged_with_its_status_and_raised(
    api: responses.RequestsMock, run: IngestionRun
) -> None:
    _register(api, "sessions", json=[SESSION])
    _register(api, "drivers", json=DRIVERS)
    _register(api, "laps", status=500)

    with pytest.raises(OpenF1HTTPError):
        _ingest(run)

    assert _log(run)["laps"] == ("failed", None, 500, 4, None)
    assert not (run.bronze_dir / "laps").exists()
    error = run.ops.execute("SELECT error FROM ingestion_log WHERE endpoint = 'laps'").fetchone()
    assert error == ("HTTP 500 (laps {'session_key': 9158}, attempts=4)",)


def test_unreachable_api_is_logged_and_stops_the_race(
    api: responses.RequestsMock, run: IngestionRun
) -> None:
    _register(api, "sessions", json=[SESSION])
    _register(api, "drivers", body=requests.ConnectionError())

    with pytest.raises(OpenF1UnavailableError):
        _ingest(run)

    assert _log(run)["drivers"] == ("failed", None, None, 4, None)
    assert "laps" not in _log(run)


def test_empty_laps_are_recorded_and_warned_about(
    api: responses.RequestsMock, run: IngestionRun, caplog: pytest.LogCaptureFixture
) -> None:
    _register(api, "sessions", json=[SESSION])
    _register(api, "drivers", json=DRIVERS)
    _register(api, "laps", json=[])

    with caplog.at_level(logging.INFO, logger="pitwall.ingestion.race"):
        _ingest(run)

    assert _log(run)["laps"][:2] == ("empty", 0)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert [r.__dict__["endpoint"] for r in warnings] == ["laps"]
