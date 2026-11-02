# ADR-001: Why DuckDB

- **Status:** Accepted
- **Date:** 2026-11-02

## Decision

Use DuckDB as the analytical database for the warehouse (dbt-duckdb), the pipeline's
operational tables and the dashboard's serving snapshots.

## Context

- **Machine:** Windows laptop, 8 GB RAM, no Docker. The pipeline must not need a background
  database service.
- **Workload:** weekly batch, analytical queries (medians, window functions, joins across laps,
  stints and pit stops). No transactional workload and no concurrent writers.
- **Volume (estimate):** about 22-24 races a season from 2023, so about 90 races by the end of
  2026. Laps are the largest v1 dataset at about 20 drivers x 60 laps = 1,200 rows a race, or
  about 110k rows in total. All v1 datasets together come to well under 1M rows and well under
  1 GB. The v1.1 `car_data` scope adds about 7k rows a race.
- **Serving:** the public demo runs on Streamlit Community Cloud, which has no database of its own.
- **Budget:** zero running cost.

## Options

| Option | Strongest case | Why not here |
|---|---|---|
| **DuckDB** (chosen) | In-process and file-based, so there is nothing to install or run. Columnar, vectorised engine built for analytical SQL. Reads Parquet directly. Mature dbt adapter. | See trade-offs |
| PostgreSQL (native Windows install) | Real server with concurrent writers, roles and backups; the most widely used open-source database in industry; mature dbt adapter. | Runs as an always-on service competing for 8 GB RAM, adds setup and maintenance, and the public demo would need a hosted instance (cost) instead of a file. Row storage is fine at this size, so its strengths don't apply to a single-writer batch job. |
| SQLite | Zero-ops single file, available everywhere. | Row-oriented, weak types (no native timestamp type), no direct Parquet reads, and the dbt adapter is community-maintained with gaps. |
| Cloud warehouse (BigQuery sandbox, MotherDuck free tier) | Closest to industry warehouses; shareable; no local resource limits. | Needs an account, credentials and a network connection on every run; free-tier limits and lock-in for data that fits on a laptop. MotherDuck stays an easy upgrade path because it runs DuckDB SQL. |

## Why DuckDB

- **No service:** it runs inside the Python process, which meets the no-Docker constraint and
  leaves RAM free when the pipeline isn't running. `memory_limit` and `threads` cap what a run
  can use on an 8 GB machine.
- **Parquet-native:** silver Parquet files can be queried in place (`read_parquet` with Hive
  partitions), so there is no separate load step between silver and dbt.
- **Serving as a file:** a serving snapshot is a single `.duckdb` file. It can be published as a
  GitHub Release asset and opened read-only by Streamlit Cloud, with no hosted database to pay for.
- **Fits the volume:** the whole v1 dataset is small enough that a single-node engine is fast
  without tuning.

## Trade-offs

- **Easier:** zero running cost and no operations, fast local development, portable snapshots,
  one SQL dialect from silver to serving.
- **Harder:** a database file can be open by one read-write process *or* by several read-only
  processes, never both. Windows file locks make this strict, so the file layout has to give
  each DuckDB file a single writer (ADR-002). There are no users, roles or network access, and
  backup means copying the file. Warehouse-specific skills (IAM, clustering, cost controls) are
  not exercised, though the SQL and dbt work transfers.

## Revisit when

- More than one process needs to write at the same time, for example live-timing ingestion
  alongside the batch run.
- The dashboard needs writes from users, or an always-on shared database.
- Data grows to a size where a run regularly spills to disk under the 1.5 GB memory limit, for
  example full-race `car_data` for every driver. MotherDuck is the smallest move from there.
