# Architecture

How PitWall is put together today, and the rules that keep it correct as it grows. The data
itself is described in [data-model.md](data-model.md).

## Pipeline

```text
OpenF1 API -> ingestion -> bronze (raw JSON) -> silver (Parquet) -> dbt on DuckDB -> serving -> Streamlit
                  \-> ops.duckdb (ingestion_log)
```

Built so far: ingestion into bronze and `ops.ingestion_log`, validation into silver, and the
dbt models in `warehouse.duckdb`. Serving and the dashboard follow in Phase 1.

## Components

| Module | Responsibility |
|---|---|
| `cli.py` | Entry point. Loads settings, reads the wall clock, creates the `run_id`, runs a command. |
| `config.py` | Settings from `config/settings.yaml`, overridden by `PITWALL_*` variables. |
| `log.py` | JSON log lines on stderr, each carrying the `run_id`. |
| `ingestion/openf1.py` | OpenF1 client: timeouts, retries with backoff, 3/s and 30/min rate limits. |
| `ingestion/bronze.py` | Writes one response as `payload.json` plus `metadata.json`. |
| `ingestion/race.py` | Ingests one race: checks the session record, then fetches drivers and laps. |
| `ops.py` | Opens `ops.duckdb` and writes `ingestion_log`. |
| `validation/schemas.py` | Record contracts (Pydantic) and the Arrow schemas derived from them. |
| `validation/silver.py` | Validates a run's bronze payload and replaces the silver partition. |
| `transform/warehouse.py` | Runs `dbt build` for one session in a separate process. |
| `orchestration/run.py` | Runs one session: ingestion, silver, then dbt. |
| `dbt/` | Staging views over silver, gold dimensions and facts, marts, and their tests. |

## Run flow

`pitwall run --session KEY [--as-of TIMESTAMP]`:

1. The CLI loads settings, reads the clock once and derives the `run_id` from it.
2. `sessions?session_key=KEY` is fetched, stored in bronze and logged.
3. The session must exist, be a `Race` (not a Sprint), not be cancelled, and have ended at
   least `settle_delay_hours` before `as_of`. Otherwise the run stops here.
4. `drivers` and `laps` are fetched, stored and logged in turn.
5. Each dataset is validated from this run's bronze payload and written to its silver
   partition.
6. `dbt build --vars '{session_key: KEY}'` rebuilds that session's rows in every gold model
   and mart, then runs the unit and data tests.
7. Exit code 0 on success. An API failure, an ineligible session, a contract break, or a dbt
   model or `error` test failure exits 1 with the reason logged. A failed fetch is also a row
   in `ingestion_log`; dbt's own output is in `data/dbt/logs/dbt.log`.

`pitwall run` without `--session` exits 1 until run selection exists (Phase 2).

## Rules

- **One clock.** Only `cli.py` reads the wall clock. `--as-of` is the logical run time used
  for decisions such as the settle delay, so a rerun with the same value decides the same way.
  Audit timestamps (`ingested_at`) record when a payload actually arrived, so the CLI passes a
  clock function down instead of a fixed time; tests pass a fixed one.
- **Bronze is immutable.** Each run writes a new `run_id=` directory and never touches an
  older one. Files are written to `.tmp` and renamed into place, and `metadata.json` is
  written last, so a directory without it is an interrupted write.
- **An empty result is an outcome.** It is stored and logged with status `empty` and a
  warning, never treated as silent success. The quality gate decides whether it blocks.
- **Failures are recorded.** A fetch that fails after retries gets an `ingestion_log` row with
  status `failed` and the error before the run stops.
- **Only registered endpoints.** OpenF1 answers an unknown endpoint with the same 404 as "no
  results", so a typo would look like an empty result. Endpoints are fixed in code
  (`ingestion/race.py`) until the Phase 2 registry in config.
- **Strict contracts.** Silver accepts a record only if every field has the documented type:
  numbers sent as strings and timestamps without an offset are rejected, not coerced.
  Timestamps are converted to UTC. Fields OpenF1 adds are dropped until Phase 3 logs them as
  schema drift. In Phase 1 one bad record fails its dataset and the run; Phase 3 routes bad
  records to quarantine instead.
- **Silver is overwritten per partition.** A run replaces the whole
  `{dataset}/session_key=X/data.parquet` file, so rerunning a session gives the same result.
  The file is written to `.tmp` and renamed into place, so readers see the old file or the new
  one, and a failed validation leaves the old one untouched. Readers match `data.parquet` only.
- **Gold is rebuilt per session.** Gold models and marts are incremental with delete+insert
  on `session_key`: a run deletes its session's rows and inserts them again, so a rerun gives
  the same tables. A build without `session_key` rebuilds every session in silver.
- **dbt gets its settings from the pipeline.** `pitwall run` passes paths and DuckDB limits
  from `config/settings.yaml` as `DBT_PITWALL_*` environment variables, and `profiles.yml`
  has no fallbacks, so there is one source of configuration. Model parameters such as
  `outlier_pct` live in `dbt_project.yml` beside the logic they define.
- **Single writer per DuckDB file.** Only pipeline Python writes `ops.duckdb`, and only dbt
  writes `warehouse.duckdb`. Windows file locks make two writers fail. dbt runs in its own
  process, so the warehouse file is closed when it exits.

## Storage layout

```text
data/                                   # PITWALL_DATA_DIR, gitignored
  bronze/{endpoint}/session_key=X/run_id=Y/{payload.json, metadata.json}
  silver/{dataset}/session_key=X/data.parquet
  ops.duckdb                            # ingestion_log
  warehouse.duckdb                      # dbt models
  dbt/{target, logs}/                   # dbt artefacts and dbt.log
  serving/                              # planned
```
