# ingestion-gateway

Bridges MQTT to Kafka. The single ingress point for the data plane.

## Bounded context

Owns the **trust boundary** between the sensor fleet and the internal event
backbone. Verifies sensor identity, validates payload schema, and writes to Kafka.
Nothing else is allowed to publish to the `telemetry.*` topics.

## Behavior

1. Subscribes to `fmms/area/+/sensor/+/telemetry` on Mosquitto via MQTT 5.
2. For each incoming message:
   1. Parse + validate against `contracts/telemetry-envelope.schema.json`. Drop
      and audit malformed.
   2. Look up the sensor in the identity cache (TTL 5 min, populated from
      `opdb.sensor`). Verify the per-sensor token from MQTT 5 auth properties
      (ADR-006 layer 2). Reject + audit unknown / mismatched sensors.
   3. Verify the sensor's claimed `area_id` matches its registered area.
   4. Stamp `ingested_at = now()` (server time). Both timestamps are persisted.
   5. Compute target topic shard: `telemetry.{hash(area_id) mod 16}` (ADR-010).
   6. Produce to Kafka with partition key = `area_id`, batched send (10 ms / 64 KB).

## Inputs

- MQTT topics: `fmms/area/+/sensor/+/telemetry`, `fmms/area/+/sensor/+/status`.
- REST: `geo-service` for sensor identity lookup (cached).

## Outputs

- Kafka topics:
  - `telemetry.0`..`telemetry.15` — partitioned by `area_id`.
  - `sensor-status` — status events (FR-07).
- Prometheus metrics on `:8000/metrics`:
  - `ingestion_messages_total{outcome}` (`accepted`, `malformed`, `unauthenticated`, `area_mismatch`)
  - `ingestion_kafka_publish_seconds` (histogram)
  - `ingestion_identity_cache_hits_total`, `..._misses_total`
  - `ingestion_messages_dropped_backpressure_total`
- Audit log: every rejection writes to `opdb.audit_log`.

## Backpressure

When the Kafka producer buffer is full, the gateway drops the **oldest**
nominal-mode reading from the same sensor (preserves criticals). This is logged
and counted. See architecture.md §7.4.

## Configuration

| Var | Default | Notes |
|---|---|---|
| `MQTT_HOST` | `mosquitto` | |
| `MQTT_PORT` | `1883` | |
| `KAFKA_BOOTSTRAP` | `redpanda:9092` | |
| `POSTGRES_DSN` | required | For identity lookup. |
| `IDENTITY_CACHE_TTL_S` | `300` | |
| `KAFKA_BATCH_LINGER_MS` | `10` | |
| `KAFKA_BATCH_SIZE_BYTES` | `65536` | |
| `TELEMETRY_TOPIC_SHARDS` | `16` | Must match Kafka topic count. |

## Run locally

```bash
cd services/ingestion-gateway
uv sync
uv run python -m ingestion_gateway
```

In Compose: starts automatically with `make up-all`.

## Tests

- Unit: schema validation, identity cache, partition key calculation,
  backpressure drop policy.
- Integration: real Mosquitto + Redpanda + Postgres via testcontainers; assert
  end-to-end that a published MQTT message lands on the right Kafka topic with
  the right partition key.

## Critical paths (do not regress)

- The validate → identity → produce path must remain async and bounded. No
  synchronous DB hits per message — only the cache miss path may hit Postgres,
  and that path is rate-limited.
- Token verification compares against an **argon2id** hash. Plaintext token
  comparison is a security regression.
