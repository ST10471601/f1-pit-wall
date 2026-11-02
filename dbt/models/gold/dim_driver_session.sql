select
    session_key,
    driver_number,
    name_acronym,
    full_name,
    broadcast_name,
    team_name,
    team_colour,
    headshot_url,
    run_id
from {{ ref('stg_drivers') }}
{{ session_filter() }}
