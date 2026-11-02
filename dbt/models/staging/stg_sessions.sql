select
    session_key,
    meeting_key,
    year,
    session_name,
    circuit_short_name,
    country_name,
    location,
    date_start as started_at,
    date_end as ended_at,
    gmt_offset as utc_offset,
    is_cancelled,
    run_id
from {{ source('silver', 'sessions') }}
