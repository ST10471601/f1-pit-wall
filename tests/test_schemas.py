from datetime import UTC, datetime
from typing import Any

import pyarrow as pa
import pytest
from pydantic import BaseModel, ValidationError

from pitwall.validation.schemas import DriverRecord, LapRecord, SessionRecord, arrow_schema
from tests.records import DRIVER, LAP, SESSION


@pytest.mark.parametrize(
    ("model", "record"), [(SessionRecord, SESSION), (DriverRecord, DRIVER), (LapRecord, LAP)]
)
def test_documented_records_are_valid(model: type[BaseModel], record: dict[str, Any]) -> None:
    model.model_validate(record)


def test_timestamps_are_converted_to_utc() -> None:
    session = SessionRecord.model_validate(SESSION | {"date_end": "2023-09-17T22:00:00+08:00"})

    assert session.date_end == datetime(2023, 9, 17, 14, 0, tzinfo=UTC)
    assert session.date_end.tzinfo is UTC


def test_nullable_fields_may_be_null_or_missing() -> None:
    lap = LapRecord.model_validate(
        {key: LAP[key] for key in ("session_key", "meeting_key", "driver_number", "lap_number")}
        | {"is_pit_out_lap": True, "lap_duration": None}
    )

    assert lap.lap_duration is None
    assert lap.segments_sector_1 is None


def test_unknown_fields_are_dropped() -> None:
    driver = DriverRecord.model_validate(DRIVER | {"country_code": "NED"})

    assert "country_code" not in driver.model_dump()


@pytest.mark.parametrize(
    ("model", "record", "field"),
    [
        (LapRecord, LAP | {"lap_number": "8"}, "lap_number"),
        (LapRecord, LAP | {"i1_speed": 307.0}, "i1_speed"),
        (LapRecord, LAP | {"is_pit_out_lap": 0}, "is_pit_out_lap"),
        (LapRecord, LAP | {"date_start": "2023-09-16T13:59:07"}, "date_start"),
        (LapRecord, {k: v for k, v in LAP.items() if k != "lap_number"}, "lap_number"),
        (DriverRecord, DRIVER | {"team_colour": "#3671C6"}, "team_colour"),
        (DriverRecord, DRIVER | {"name_acronym": None}, "name_acronym"),
        (SessionRecord, SESSION | {"gmt_offset": "+08:00"}, "gmt_offset"),
    ],
    ids=[
        "number-as-string",
        "float-for-int",
        "int-for-bool",
        "naive-timestamp",
        "missing-key",
        "colour-with-hash",
        "null-required",
        "offset-format",
    ],
)
def test_contract_breaks_are_rejected(
    model: type[BaseModel], record: dict[str, Any], field: str
) -> None:
    with pytest.raises(ValidationError) as exc:
        model.model_validate(record)

    assert [error["loc"][0] for error in exc.value.errors()] == [field]


def test_arrow_schema_follows_the_model() -> None:
    schema = arrow_schema(LapRecord)

    assert schema.names == list(LapRecord.model_fields)
    assert schema.field("lap_number").type == pa.int64()
    assert not schema.field("lap_number").nullable
    assert schema.field("lap_duration").type == pa.float64()
    assert schema.field("lap_duration").nullable
    assert schema.field("date_start").type == pa.timestamp("us", tz="UTC")
    assert schema.field("is_pit_out_lap").type == pa.bool_()
    assert schema.field("segments_sector_1").type == pa.list_(pa.int64())
    assert arrow_schema(SessionRecord).field("date_end").type == pa.timestamp("us", tz="UTC")
    assert arrow_schema(DriverRecord).field("team_colour").type == pa.string()


@pytest.mark.parametrize("annotation", [bytes, int | str | None])
def test_arrow_schema_rejects_types_it_cannot_map(annotation: Any) -> None:
    class Unmapped(BaseModel):
        value: annotation

    with pytest.raises(TypeError, match=r"Unmapped\.value"):
        arrow_schema(Unmapped)


def test_whole_number_is_accepted_for_a_float() -> None:
    assert LapRecord.model_validate(LAP | {"lap_duration": 92}).lap_duration == 92.0
