# rule-engine

Stream processor that evaluates flood-risk rules against the telemetry stream
and emits classified alerts. The most architecturally critical service: it
holds the FR-08 redundancy state machine and is the first place a regression
shows up.

## Bounded context

Owns the **alert classification logic** and the **per-area redundancy state**
in Redis. Stateless across restarts (state is recoverable from Kafka offset
replay + Redis snapshot).

## Behavior

Three Faust agents, one per rule family:

### Agent 1 — Threshold evaluator (FR-06)

Pure function per event:

```
evaluate_thresholds(event, thresholds_for_area(event.area_id)) -> [Alert]
```

Compares each measurement against the configured `warning_*` / `critical_*`
thresholds. Emits `alerts.threshold` for warning crossings and
`alerts.priority` for critical crossings (with severity = `high`).

Thresholds are read from `opdb.threshold` via the geo-service REST API and
cached for 60 seconds. Cache invalidation on threshold update is
**eventually consistent** — managers may see ~60 s of stale rules after a
configuration change. Acceptable; documented.

### Agent 2 — Redundancy tracker (FR-07, FR-08)

Subscribes to `sensor-status`. Maintains state in Redis:

```
area:{area_id}:operational_count:{parameter}  →  integer
```

On `status=0` or sensor-silence-timeout: decrement.
On `status=1` after recovery: increment.

When the count drops to 0 for any parameter, emit a high-severity
`alerts.malfunction` plus a corresponding `alerts.priority` (escalation per
Phase 0 Case 3). When the count is > 0, emit a low-severity
`alerts.malfunction` (the "backup is still covering" case).

Sensor silence is detected by a watchdog that scans `sensor:{id}:latest`
timestamps every 30 s.

### Agent 3 — Trend annotator

Computes a short-window trend (rising / falling / stable) for each parameter
per sensor. Annotates outgoing alerts with the trend so the UI can show it.
Window = 5 min; data read from Redis.

## Inputs

- Kafka: `telemetry.0..15`, `sensor-status`.
- REST: `geo-service` for thresholds (cached 60 s).
- Redis: redundancy state, sensor latest snapshots.

## Outputs

- Kafka topics: `alerts.threshold`, `alerts.malfunction`, `alerts.priority`.
  Schema: `contracts/alert.schema.json`.
- Redis writes: `area:{area_id}:operational_count:{parameter}`.
- Prometheus metrics:
  - `rule_events_evaluated_total`
  - `rule_alerts_emitted_total{kind, severity}`
  - `rule_threshold_cache_hits_total`, `..._misses_total`
  - `rule_redundancy_escalations_total`
  - `rule_consumer_lag_seconds`

## Configuration

| Var | Default | Notes |
|---|---|---|
| `KAFKA_BOOTSTRAP` | `redpanda:9092` | |
| `REDIS_URL` | required | |
| `GEO_SERVICE_URL` | `http://geo-service:8000` | |
| `THRESHOLD_CACHE_TTL_S` | `60` | |
| `SENSOR_SILENCE_TIMEOUT_S` | `180` | 3× nominal interval. |
| `WATCHDOG_INTERVAL_S` | `30` | |
| `CONSUMER_GROUP` | `rule-engine` | |

## Run locally

```bash
cd services/rule-engine
uv sync
uv run faust -A rule_engine worker -l info
```

## Tests

The redundancy state machine is the most fragile part of the system. Tests
must cover:

- Single sensor in area, fails → high-priority malfunction.
- Two sensors in area, one fails → low-priority malfunction.
- Two sensors in area, both fail → escalation to high-priority + priority alert.
- Recovery: sensor restored → count increments, no spurious alerts.
- Replay: rebuild state from `sensor-status` topic from offset 0; assert final
  state matches direct event-by-event accumulation.

Integration tests use a testcontainers Redpanda + Redis stack.

## Critical paths

- **Pure functions** for `evaluate_thresholds` and `update_redundancy`. These
  are the portability surface to Flink (ADR-005). Do not let them grow I/O.
- Out-of-order events within an area would corrupt the redundancy state.
  Partition-by-area in Kafka (ADR-010) prevents this.
- The 60 s threshold cache TTL means rule changes lag. If a use case ever
  requires immediate effect, switch to push-based invalidation via a Redis
  Pub/Sub channel from geo-service.

## Replay procedure

```bash
make consume TOPIC=sensor-status   # observe the stream
# or, to rebuild redundancy state from scratch:
docker compose exec redis redis-cli KEYS 'area:*:operational_count:*' | \
  xargs docker compose exec redis redis-cli DEL
# then restart rule-engine; it will re-consume from the configured offset.
```
