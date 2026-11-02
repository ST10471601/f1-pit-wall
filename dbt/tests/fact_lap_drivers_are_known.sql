-- Every lap belongs to a driver listed for its session.
select laps.session_key, laps.driver_number
from {{ ref('fact_lap') }} as laps
anti join {{ ref('dim_driver_session') }} as drivers
    using (session_key, driver_number)
