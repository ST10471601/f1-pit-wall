-- Clean-lap rules 1-3 and 6; rules 4 (in-laps) and 5 (neutralisations) need pit and race
-- control data and come in Phase 4. The first rule that matches sets exclusion_reason.
with laps as (
    select
        session_key,
        driver_number,
        lap_number,
        lap_started_at,
        lap_seconds,
        sector_1_seconds,
        sector_2_seconds,
        sector_3_seconds,
        intermediate_1_kph,
        intermediate_2_kph,
        speed_trap_kph,
        is_pit_out_lap,
        run_id,
        case
            when lap_number = 1 then 'first_lap'
            when lap_seconds is null then 'no_lap_time'
            when is_pit_out_lap then 'pit_out_lap'
        end as rule_reason
    from {{ ref('stg_laps') }}
    {{ session_filter() }}
),

driver_medians as (
    select
        session_key,
        driver_number,
        median(lap_seconds) as median_lap_seconds
    from laps
    where rule_reason is null
    group by session_key, driver_number
),

classified as (
    select
        laps.*,
        coalesce(
            laps.rule_reason,
            case
                when laps.lap_seconds > {{ var('outlier_pct') }} * driver_medians.median_lap_seconds
                    then 'outlier'
            end
        ) as exclusion_reason
    from laps
    left join driver_medians using (session_key, driver_number)
)

select
    session_key,
    driver_number,
    lap_number,
    lap_started_at,
    lap_seconds,
    sector_1_seconds,
    sector_2_seconds,
    sector_3_seconds,
    intermediate_1_kph,
    intermediate_2_kph,
    speed_trap_kph,
    is_pit_out_lap,
    exclusion_reason is null as is_clean_lap,
    exclusion_reason,
    run_id
from classified
