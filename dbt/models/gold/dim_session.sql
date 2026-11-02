select
    session_key,
    meeting_key,
    year,
    session_name,
    circuit_short_name,
    country_name,
    location,
    started_at,
    ended_at,
    utc_offset,
    is_cancelled,
    run_id
from {{ ref('stg_sessions') }}
{{ session_filter() }}
