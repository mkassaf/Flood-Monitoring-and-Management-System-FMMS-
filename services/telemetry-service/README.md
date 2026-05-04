# telemetry-service

Persists sensor telemetry to TimescaleDB and maintains the per-sensor hot state
in Redis. The single writer of the telemetry hypertable.

## Bounded context

Owns the **`tsdb.telemetry`** hypertable and the **`sensor:{id}:latest`** Redis
keys. No other service writes to either.

## Behavior

1. Consumes from Kafka topics `telemetry.0..telemetry.15` (consumer group
   `telemetry-writer`).
2. Buffers incoming events in 1-second windows or 10,000-row batches
   (whichever comes first).
3. Inserts the batch via `COPY` to `tsdb.telemetry` (much cheaper than per-row
   INSERT — see CLAUDE.md energy reminders).
4. For each event, updates `sensor:{sensor_id}:latest` in Redis with the
   freshest reading + status.
5. On batch failure: retries with backoff; on persistent failure, rewinds the
   Kafka consumer offset (no data loss — the broker is the source of truth).

## Inputs

- Kafka topics: `telemetry.0..15`. Schema:
  `contracts/telemetry-envelope.schema.json`.

## Outputs

- TimescaleDB writes: `tsdb.telemetry`. (Continuous aggregates refresh
  themselves via Timescale policies.)
- Redis keys:
  - `sensor:{sensor_id}:latest` — JSON of the freshest reading.
  - `sensor:{sensor_id}:status` — `0` or `1`.
  - `area:{area_id}:sensors` — set of sensor IDs in the area (for fast lookup).
- Prometheus metrics on `:8000/metrics`:
  - `telemetry_consumed_total`
  - `telemetry_persisted_total`
  - `telemetry_batch_size` (histogram)
  - `telemetry_batch_seconds` (histogram)
  - `telemetry_consumer_lag_seconds`

## Configuration

| Var | Default | Notes |
|---|---|---|
| `KAFKA_BOOTSTRAP` | `redpanda:9092` | |
| `POSTGRES_DSN` | required | |
| `REDIS_URL` | required | |
| `TELEMETRY_TOPIC_SHARDS` | `16` | |
| `BATCH_WINDOW_MS` | `1000` | |
| `BATCH_MAX_ROWS` | `10000` | |
| `CONSUMER_GROUP` | `telemetry-writer` | |

## Run locally

```bash
cd services/telemetry-service
uv sync
uv run python -m telemetry_service
```

## Tests

- Unit: batch accumulation, COPY statement formation, Redis update payload.
- Integration: full Kafka → batch → TimescaleDB → Redis flow against
  testcontainers; assert hypertable insertion and Redis state.

## Critical paths

- COPY is the only acceptable insertion mode at the load envelope. Per-row
  INSERT is a regression — it will not meet QAS-03 throughput.
- Batches must be **idempotent**: telemetry has a primary key on
  `(sensor_id, ts)` (or equivalent partition + sensor + ts dedup). A retried
  batch must not double-write.
- The Redis update is **best-effort**. If Redis is down the persistence path
  must continue (TimescaleDB is the source of truth). Stale `sensor:latest`
  is a UI freshness problem, not a data integrity problem.
