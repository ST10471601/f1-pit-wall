"""OpenF1 records shaped as the API documents them, shared by tests."""

from typing import Any

SESSION: dict[str, Any] = {
    "circuit_key": 61,
    "circuit_short_name": "Singapore",
    "country_code": "SGP",
    "country_key": 157,
    "country_name": "Singapore",
    "date_end": "2023-09-17T14:00:00+00:00",
    "date_start": "2023-09-17T12:00:00+00:00",
    "gmt_offset": "08:00:00",
    "is_cancelled": False,
    "location": "Marina Bay",
    "meeting_key": 1219,
    "session_key": 9158,
    "session_name": "Race",
    "session_type": "Race",
    "year": 2023,
}
DRIVER: dict[str, Any] = {
    "broadcast_name": "M VERSTAPPEN",
    "driver_number": 1,
    "first_name": "Max",
    "full_name": "Max VERSTAPPEN",
    "headshot_url": "https://www.formula1.com/maxver01.png",
    "last_name": "Verstappen",
    "meeting_key": 1219,
    "name_acronym": "VER",
    "session_key": 9158,
    "team_colour": "3671C6",
    "team_name": "Red Bull Racing",
}
LAP: dict[str, Any] = {
    "date_start": "2023-09-16T13:59:07.606000+00:00",
    "driver_number": 63,
    "duration_sector_1": 26.966,
    "duration_sector_2": 38.657,
    "duration_sector_3": 26.12,
    "i1_speed": 307,
    "i2_speed": 277,
    "is_pit_out_lap": False,
    "lap_duration": 91.743,
    "lap_number": 8,
    "meeting_key": 1219,
    "segments_sector_1": [2049, 2049, 2051],
    "segments_sector_2": [2049, None],
    "segments_sector_3": [2048, 2064],
    "session_key": 9158,
    "st_speed": 298,
}
