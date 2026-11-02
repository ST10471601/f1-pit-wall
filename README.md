# PitWall

A batch data pipeline and dashboard for Formula 1 race data. PitWall ingests race sessions
from the [OpenF1 API](https://openf1.org), validates and models them with DuckDB and dbt, and
serves race pace, tyre stint, pit stop and teammate analysis in Streamlit.

> **Status:** foundations. The `run` and `release` commands are stubs that exit with an error.

## Architecture

```text
OpenF1 API -> bronze (raw JSON, immutable) -> silver (validated Parquet) -> dbt + DuckDB (gold) -> serving snapshot -> Streamlit
                                                   \-> quarantine (rejected rows with a reason)
```

- **Scope (v1):** Grand Prix race sessions from 2023 (where OpenF1 history starts) to the
  current season. Sprints are excluded.
- **Runs:** weekly batch, local-first, on Windows without Docker.

## Setup (Windows)

Requires [uv](https://docs.astral.sh/uv/), which installs Python 3.12 if it is missing.

```powershell
git clone https://github.com/ST10471601/f1-pit-wall.git
cd f1-pit-wall
uv sync
uv run pre-commit install
uv run pitwall --help
```

## Usage

```powershell
uv run pitwall run                                # process race sessions that are due
uv run pitwall run --session 9158                 # process one session
uv run pitwall run --as-of 2026-11-02T08:00:00Z   # fix the logical run time for reruns
uv run pitwall release                            # publish the serving snapshot
```

## Configuration

Settings live in [`config/settings.yaml`](config/settings.yaml). Environment variables override
them as `PITWALL_<FIELD>`, with `__` separating nested fields.

| Variable | Purpose |
|---|---|
| `PITWALL_CONFIG_FILE` | Use a different YAML file |
| `PITWALL_DATA_DIR` | Where data and DuckDB files are written (default `data/`) |
| `PITWALL_API__TIMEOUT_SECONDS` | Example of a nested override |
| `PITWALL_DISCORD_WEBHOOK_URL` | Failure alerts. Secret: set it in the environment only |

Local secrets go in `.env` (gitignored); [`.env.example`](.env.example) lists the options.

Logs are JSON lines on stderr, and every line carries the `run_id` of the run that wrote it.

## Development

```powershell
uv run poe check       # lint, strict type check, tests with coverage gate (what CI runs)
uv run poe format      # auto-format and apply safe fixes
uv run poe test-unit   # quick unit tests
```

## Project layout

```text
config/          settings.yaml
src/pitwall/     cli, config, logging; ingestion, validation, transform, orchestration
dbt/             dbt project
tests/
docs/adr/        architecture decision records
data/            pipeline output (gitignored)
```

## Decisions

- [ADR-001: Why DuckDB](docs/adr/001-why-duckdb.md)

## Disclaimer

Unofficial project; not affiliated with Formula 1. Data: [OpenF1](https://openf1.org).
