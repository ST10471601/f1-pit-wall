import json
import logging
import re
import sys
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from pitwall.log import JsonFormatter, run_context
from pitwall.run_id import new_run_id


def _format(**kwargs: object) -> dict[str, Any]:
    record = logging.makeLogRecord({"name": "pitwall.test", "levelname": "INFO", **kwargs})
    entry: dict[str, Any] = json.loads(JsonFormatter().format(record))
    return entry


def test_line_carries_run_id_and_extra_fields() -> None:
    with run_context("20261102T080000Z-abc123"):
        entry = _format(msg="ingested %s rows", args=(42,), endpoint="laps")

    assert entry["run_id"] == "20261102T080000Z-abc123"
    assert entry["message"] == "ingested 42 rows"
    assert entry["endpoint"] == "laps"
    assert entry["level"] == "INFO"
    assert entry["ts"].endswith("+00:00")


def test_run_id_is_null_outside_a_run() -> None:
    assert _format(msg="startup")["run_id"] is None


def test_exception_is_included() -> None:
    try:
        raise ValueError("bad payload")
    except ValueError:
        entry = _format(msg="failed", exc_info=sys.exc_info())

    assert "ValueError: bad payload" in entry["exc_info"]


def test_run_id_format_is_filename_safe_and_utc() -> None:
    sast = timezone(timedelta(hours=2))
    run_id = new_run_id(datetime(2026, 11, 2, 10, 0, 0, tzinfo=sast))

    assert re.fullmatch(r"20261102T080000Z-[0-9a-f]{6}", run_id)


def test_run_ids_sort_by_start_time() -> None:
    start = datetime(2026, 11, 2, 8, 0, 0, tzinfo=UTC)
    ids = [new_run_id(start + timedelta(seconds=s)) for s in (59, 0, 3600)]

    assert sorted(ids) == [ids[1], ids[0], ids[2]]
