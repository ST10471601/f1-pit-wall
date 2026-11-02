with laps as (
    select session_key, driver_number, lap_seconds, is_clean_lap
    from {{ ref('fact_lap') }}
    {{ session_filter() }}
),

per_driver as (
    select
        session_key,
        driver_number,
        count(*) as laps,
        count(*) filter (where is_clean_lap) as clean_laps,
        median(lap_seconds) filter (where is_clean_lap) as race_pace_seconds,
        min(lap_seconds) as fastest_lap_seconds
    from laps
    group by session_key, driver_number
)

select
    per_driver.session_key,
    per_driver.driver_number,
    drivers.name_acronym,
    drivers.full_name,
    drivers.team_name,
    drivers.team_colour,
    per_driver.laps,
    per_driver.clean_laps,
    per_driver.clean_laps / per_driver.laps as clean_lap_share,
    per_driver.race_pace_seconds,
    per_driver.race_pace_seconds
        - min(per_driver.race_pace_seconds) over (partition by per_driver.session_key)
        as race_pace_gap_seconds,
    per_driver.fastest_lap_seconds
from per_driver
left join {{ ref('dim_driver_session') }} as drivers
    using (session_key, driver_number)
