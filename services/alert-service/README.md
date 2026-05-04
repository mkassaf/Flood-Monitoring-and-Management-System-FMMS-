# alert-service

Consumes alerts from Kafka, deduplicates them, persists them, and pushes them
to the BFF for fan-out to the UI. The audit-of-record for every alert.

## Bounded context

Owns **`opdb.alert`** and **`opdb.audit_log`** writes that originate from
alerts. The BFF reads from `opdb.alert` for historical queries; nothing else
writes there.

## Behavior

1. Consumes from `alerts.threshold`, `alerts.malfunction`, `alerts.priority`
   (separate consumer groups so the priority path can never be starved by the
   bulk topics — architecture.md §8 Performance/prioritize-events).
2. Dedup: an alert with an `alert_id` already seen in the last 24 h is dropped
   and counted (the rule engine should not produce duplicates, but defense in
   depth).
3. Inserts into `opdb.alert`.
4. Publishes to Redis Pub/Sub channel `area:{area_id}:updates` for the BFF's
   WebSocket fan-out.
5. Updates the per-area alert summary cache in Redis
   (`area:{area_id}:alert_summary`) for fast dashboard rollups.
6. Provides a REST endpoint for **acknowledge** — managers acknowledge alerts
   via the BFF, which proxies to this service.

## Plugin port (NFR-09)

A pluggable notification channel interface lets future Phase 7+ work add SMS
/ email / push without changing the alert-service core. The interface is in
`src/alert_service/channels/base.py` and any concrete channel registers
itself via entry-points or env-var-driven loader. The PoC ships with one
channel: `WebSocketChannel` (push to BFF via Redis Pub/Sub).

## Inputs

- Kafka topics: `alerts.threshold`, `alerts.malfunction`, `alerts.priority`.
- REST: `POST /alerts/{alert_id}/acknowledge` from BFF.

## Outputs

- `opdb.alert` writes.
- Redis Pub/Sub: `area:{id}:updates` channel.
- Redis keys: `area:{id}:alert_summary` (counts by severity, last 24h).
- Prometheus metrics:
  - `alerts_consumed_total{kind}`
  - `alerts_persisted_total`
  - `alerts_dedup_dropped_total`
  - `alert_publish_to_pubsub_seconds` (histogram)
  - `alert_acks_total`

## Configuration

| Var | Default | Notes |
|---|---|---|
| `KAFKA_BOOTSTRAP` | `redpanda:9092` | |
| `POSTGRES_DSN` | required | |
| `REDIS_URL` | required | |
| `DEDUP_WINDOW_S` | `86400` | 24h. |
| `PRIORITY_CONSUMER_GROUP` | `alert-priority` | Isolated lag SLO. |
| `STANDARD_CONSUMER_GROUP` | `alert-standard` | |

## Run locally

```bash
cd services/alert-service
uv sync
uv run python -m alert_service
```

## Tests

- Unit: dedup logic, severity routing, plugin loader.
- Integration: end-to-end alert flow — produce to Kafka, assert `opdb.alert`
  row + Redis Pub/Sub message.

## Critical paths

- The priority topic is consumed by a **separate consumer group** so a backlog
  on the bulk topics cannot delay priority-1 alerts. Don't merge them.
- Acknowledge writes the user ID + reason to `opdb.alert.acknowledged_*` and
  appends to `opdb.audit_log`. Both must succeed in a single transaction.
