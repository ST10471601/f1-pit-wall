# Data model

What each layer stores, at what grain. Timestamps are timezone-aware and in UTC. How the layers are produced is in [architecture.md](architecture.md).

## Bronze

Raw OpenF1 responses, one directory per fetch:

```text
data/bronze/{endpoint}/session_key={session_key}/run_id={run_id}/
  payload.json    # response body exactly as received
  metadata.json   # what was fetched, when and how
```

- **Endpoints so far:** `sessions`, `drivers`, `laps`, each filtered by `session_key`.
- **Grain:** one payload per (endpoint, session_key, run_id). Reruns add a directory; nothing
  is overwritten.
- **Empty results:** OpenF1 answers "no results" with HTTP 404 and
  `{"detail": "No results found."}`. That body is stored as received and the metadata marks
  it `empty`, so readers must check `status` before parsing the payload as a list.

### metadata.json

| Field | Type | Meaning |
|---|---|---|
| `run_id` | string | Run that fetched it, e.g. `20261102T080000Z-3f9a1c` |
| `endpoint` | string | OpenF1 endpoint |
| `session_key` | int | OpenF1 session |
| `params` | object | Query parameters sent |
| `url` | string | Full request URL |
| `http_status` | int | 200, or 404 for an empty result |
| `status` | `ok` or `empty` | `empty` when the response held no records |
| `record_count` | int | Records in the payload |
| `payload_sha256` | string | SHA-256 of `payload.json`; equal hashes mean unchanged data |
| `payload_bytes` | int | Size of `payload.json` |
| `attempts` | int | HTTP attempts, including retries |
| `ingested_at` | timestamp | When the response was received |

## Silver

Validated, typed records, one Parquet file (zstd) per dataset and session:

```text
data/silver/{dataset}/session_key={session_key}/data.parquet
```

- **Grain:** one row per OpenF1 record, as received. Deduplication on a declared key comes in
  Phase 3.
- **Contract:** the Pydantic models in `validation/schemas.py`; the Parquet schema is derived
  from them, so the two cannot drift apart. Types are strict and timestamps are UTC.
- **Lineage:** every row also has `run_id` (VARCHAR) and `ingested_at` (TIMESTAMPTZ) of the
  bronze payload it came from.
- **Empty results** give a zero-row file with the full schema, so readers never see a stale
  partition or a missing column.

Columns are listed in file order. "Null" means the field may be null or missing in OpenF1.

### sessions

| Column | Type | Null |
|---|---|---|
| `session_key`, `meeting_key` | BIGINT | no |
| `session_name` (`Race`, `Sprint`, ...), `session_type` | VARCHAR | no |
| `year` | BIGINT | no |
| `date_start`, `date_end` | TIMESTAMPTZ | no |
| `gmt_offset` (local offset as `HH:MM:SS`, `-` when negative) | VARCHAR | no |
| `is_cancelled` | BOOLEAN | no |
| `circuit_key` | BIGINT | no |
| `circuit_short_name` | VARCHAR | no |
| `country_key` | BIGINT | no |
| `country_code`, `country_name`, `location` | VARCHAR | no |

### drivers

| Column | Type | Null |
|---|---|---|
| `session_key`, `meeting_key`, `driver_number` | BIGINT | no |
| `name_acronym` (e.g. `VER`) | VARCHAR | no |
| `broadcast_name`, `full_name`, `first_name`, `last_name` | VARCHAR | yes |
| `team_name` | VARCHAR | yes |
| `team_colour` (`RRGGBB`, no `#`) | VARCHAR | yes |
| `headshot_url` | VARCHAR | yes |

`country_code` is not kept: OpenF1 deprecated it and removes it after the 2026 season.

### laps

| Column | Type | Null |
|---|---|---|
| `session_key`, `meeting_key`, `driver_number`, `lap_number` | BIGINT | no |
| `date_start` (approximate) | TIMESTAMPTZ | yes |
| `lap_duration`, `duration_sector_1`, `duration_sector_2`, `duration_sector_3` (seconds) | DOUBLE | yes |
| `i1_speed`, `i2_speed`, `st_speed` (km/h) | BIGINT | yes |
| `is_pit_out_lap` | BOOLEAN | no |
| `segments_sector_1`, `segments_sector_2`, `segments_sector_3` | BIGINT[] | yes |

OpenF1's docs say mini-sector segments are not available during races, but real race data
has them on almost every lap (checked on five 2023 to 2026 races). The warehouse leaves them
out because no v1 metric uses them.

## Warehouse (warehouse.duckdb)

Built by dbt from silver. Staging views rename columns to warehouse conventions (`_at` for
UTC timestamps, units in names); everything below is a table. Gold and mart tables are
rebuilt one session at a time (delete+insert on `session_key`).

| Model | Grain | Purpose |
|---|---|---|
| `dim_session` | One row per race session | Circuit, country, start and end, `utc_offset`, `is_cancelled` |
| `dim_driver_session` | One row per (session, driver) | Acronym, names, team name and colour as they were for that race; no separate team dimension |
| `fact_lap` | One row per (session, driver, lap) | Lap and sector times, speeds, pit-out flag, `is_clean_lap`, `exclusion_reason` |
| `mart_driver_race_pace` | One row per (session, driver) | Laps, clean laps, race pace and fastest lap for the dashboard |

Gold rows keep the `run_id` of the bronze payload they came from.

### Clean laps

`fact_lap` applies these rules in order; the first match sets `exclusion_reason`:

| Rule | `exclusion_reason` | Excludes the lap when |
|---|---|---|
| 1 | `first_lap` | `lap_number = 1` |
| 2 | `no_lap_time` | `lap_seconds` is null |
| 3 | `pit_out_lap` | OpenF1 flags the lap as a pit-out lap |
| 6 | `outlier` | Slower than `outlier_pct` (1.07) times the driver's median of the laps that passed rules 1 to 3. A heuristic borrowed from the 107% qualifying rule |

Rules 4 (in-laps, from `pit`) and 5 (laps under a safety car, virtual safety car or red
flag, from `race_control`) come in Phase 4 with those endpoints. Until then, rule 6 catches
most neutralised laps, but a lap at safety-car pace just under the 107% limit still counts as
clean.

### mart_driver_race_pace

Each metric states its `definition_source`: **official** (OpenF1 values as given) or
**derived** (computed here).

| Column | Meaning | Source |
|---|---|---|
| `laps` | Laps the driver started | official |
| `clean_laps` | Laps that passed every clean-lap rule | derived |
| `clean_lap_share` | `clean_laps / laps` | derived |
| `race_pace_seconds` | Median lap time over clean laps | derived |
| `race_pace_gap_seconds` | Race pace minus the best race pace in the session | derived |
| `fastest_lap_seconds` | Minimum lap time over all laps, clean or not | official |

The mart also carries `name_acronym`, `full_name`, `team_name` and `team_colour` from
`dim_driver_session`.

### Tests

- **Unit tests** (dbt): the rule order and the per-driver median in `fact_lap`.
- **Data tests**, severity error, which fail the run: unique keys at each model's grain,
  not-null keys, `session_key` relationships to `dim_session`, every lap's driver listed in
  `dim_driver_session`, `session_name = 'Race'`, and the accepted `exclusion_reason` values.
- **Severity warn:** `team_name` not null. OpenF1 leaves it empty for some drivers.

## ops.duckdb

Operational tables, written only by the pipeline.

### ingestion_log

Every fetch outcome, including failures. **Grain:** one row per
(`run_id`, `endpoint`, `session_key`), enforced by the primary key.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `run_id` | VARCHAR | no | Run that made the fetch |
| `endpoint` | VARCHAR | no | OpenF1 endpoint |
| `session_key` | INTEGER | no | OpenF1 session |
| `params` | JSON | no | Query parameters sent |
| `status` | VARCHAR | no | `ok`, `empty` or `failed` |
| `http_status` | INTEGER | yes | Final HTTP status; null when no response arrived |
| `record_count` | INTEGER | yes | Records received; null on failure |
| `payload_sha256` | VARCHAR | yes | As in `metadata.json`; null on failure |
| `payload_bytes` | BIGINT | yes | As in `metadata.json`; null on failure |
| `attempts` | INTEGER | no | HTTP attempts, including retries |
| `bronze_path` | VARCHAR | yes | Directory relative to `data/bronze`; null on failure |
| `error` | VARCHAR | yes | Failure message; null otherwise |
| `ingested_at` | TIMESTAMPTZ | no | When the response arrived or the fetch gave up |

Example: what did the last run fetch?

```sql
SELECT endpoint, session_key, status, record_count, attempts
FROM ingestion_log
WHERE run_id = (SELECT max(run_id) FROM ingestion_log);
```

`run_id` sorts by start time, so `max(run_id)` is the latest run.
