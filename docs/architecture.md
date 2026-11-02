# Architecture

How PitWall is put together today, and the rules that keep it correct as it grows. The data
itself is described in [data-model.md](data-model.md).

## Pipeline

```text
OpenF1 API -> ingestion -> bronze (raw JSON) -> silver (Parquet) -> dbt on DuckDB -> serving -> Streamlit
                  \-> ops.duckdb (ingestion_log)
```

Built so far: ingestion into bronze and `ops.ingestion_log`. Silver, dbt, serving and the
dashboard follow in Phase 1.

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

## Run flow

`pitwall run --session KEY [--as-of TIMESTAMP]`:

1. The CLI loads settings, reads the clock once and derives the `run_id` from it.
2. `sessions?session_key=KEY` is fetched, stored in bronze and logged.
3. The session must exist, be a `Race` (not a Sprint), not be cancelled, and have ended at
   least `settle_delay_hours` before `as_of`. Otherwise the run stops here.
4. `drivers` and `laps` are fetched, stored and logged in turn.
5. Exit code 0 on success. An API failure or an ineligible session exits 1 with the reason
   logged; the failed fetch is also a row in `ingestion_log`.

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
- **Single writer per DuckDB file.** Only pipeline Python writes `ops.duckdb`. Windows file
  locks make two writers fail, so each later database file also has exactly one writer.

## Storage layout

```text
data/                                   # PITWALL_DATA_DIR, gitignored
  bronze/{endpoint}/session_key=X/run_id=Y/{payload.json, metadata.json}
  ops.duckdb                            # ingestion_log
  silver/, warehouse.duckdb, serving/   # planned
```
