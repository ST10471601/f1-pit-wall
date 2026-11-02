import types
from datetime import UTC, datetime
from typing import Annotated, Any, Union, get_args, get_origin

import pyarrow as pa
from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


# OpenF1 sends ISO 8601 strings, which strict mode only accepts in JSON input, not in parsed dicts.
UtcDatetime = Annotated[AwareDatetime, Field(strict=False), AfterValidator(_to_utc)]
HexColour = Annotated[str, Field(pattern=r"^[0-9A-Fa-f]{6}$")]
UtcOffset = Annotated[str, Field(pattern=r"^-?\d{2}:\d{2}:\d{2}$")]


class SilverRecord(BaseModel):
    """Contract for one OpenF1 record; nullable fields may also be missing."""

    # Strict: a number sent as a string is a contract break, not something to coerce.
    # Unknown fields are dropped for now; Phase 3 logs them as schema drift.
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    session_key: int
    meeting_key: int


class SessionRecord(SilverRecord):
    session_name: str
    session_type: str
    year: int
    date_start: UtcDatetime
    date_end: UtcDatetime
    gmt_offset: UtcOffset
    is_cancelled: bool
    circuit_key: int
    circuit_short_name: str
    country_key: int
    country_code: str
    country_name: str
    location: str


class DriverRecord(SilverRecord):
    # country_code is left out: OpenF1 deprecated it and drops it after the 2026 season.
    driver_number: int
    name_acronym: str
    broadcast_name: str | None = None
    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    team_name: str | None = None
    team_colour: HexColour | None = None
    headshot_url: str | None = None


class LapRecord(SilverRecord):
    driver_number: int
    lap_number: int
    date_start: UtcDatetime | None = None
    lap_duration: float | None = None
    duration_sector_1: float | None = None
    duration_sector_2: float | None = None
    duration_sector_3: float | None = None
    i1_speed: int | None = None
    i2_speed: int | None = None
    st_speed: int | None = None
    is_pit_out_lap: bool
    segments_sector_1: list[int | None] | None = None
    segments_sector_2: list[int | None] | None = None
    segments_sector_3: list[int | None] | None = None


_ARROW_TYPES: dict[Any, pa.DataType] = {
    int: pa.int64(),
    float: pa.float64(),
    str: pa.string(),
    bool: pa.bool_(),
    AwareDatetime: pa.timestamp("us", tz="UTC"),
    list[int | None]: pa.list_(pa.int64()),
}


def arrow_schema(model: type[BaseModel]) -> pa.Schema:
    """Arrow schema for a record model, so Parquet columns follow the contract exactly."""
    fields = []
    for name, info in model.model_fields.items():
        annotation, nullable = _without_none(info.annotation)
        if get_origin(annotation) is Annotated:
            annotation = get_args(annotation)[0]
        if annotation not in _ARROW_TYPES:
            raise TypeError(f"no Arrow type for {model.__name__}.{name}: {annotation!r}")
        fields.append(pa.field(name, _ARROW_TYPES[annotation], nullable=nullable))
    return pa.schema(fields)


def _without_none(annotation: Any) -> tuple[Any, bool]:
    args = get_args(annotation)
    if get_origin(annotation) in (Union, types.UnionType) and type(None) in args:
        rest = [arg for arg in args if arg is not type(None)]
        # A union of several types stays as it is and has no Arrow type.
        return (rest[0] if len(rest) == 1 else annotation), True
    return annotation, False
