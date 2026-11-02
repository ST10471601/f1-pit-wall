select
    session_key,
    driver_number,
    lap_number,
    date_start as lap_started_at,
    lap_duration as lap_seconds,
    duration_sector_1 as sector_1_seconds,
    duration_sector_2 as sector_2_seconds,
    duration_sector_3 as sector_3_seconds,
    i1_speed as intermediate_1_kph,
    i2_speed as intermediate_2_kph,
    st_speed as speed_trap_kph,
    is_pit_out_lap,
    run_id
from {{ source('silver', 'laps') }}
