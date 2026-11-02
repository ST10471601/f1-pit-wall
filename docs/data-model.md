# Data model

What each layer stores, at what grain. Timestamps are UTC; columns ending in `_at` are
timezone-aware. How the layers are produced is in [architecture.md](architecture.md).

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
