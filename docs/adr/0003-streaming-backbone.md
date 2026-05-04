# ADR-003 — Streaming backbone: Apache Kafka (Redpanda for PoC)

**Status:** Accepted (Phase 1)
**Related:** ADR-001 (event-driven), ADR-005 (stream processing), ADR-010 (partitioning)

## Context

The data plane is a multi-consumer event log: the same telemetry stream feeds at minimum the persistence consumer (telemetry-service) and the rule engine, with future consumers anticipated (NFR-09). Requirements:

- Sustained throughput ≥150K msg/min, burst ≥645K msg/min (D-01).
- **Replay** capability for stream reprocessing (e.g., when a rule changes) and for chaos-test recovery (QAS-02).
- **Durable buffering** so that processing slowdown does not cause data loss.
- **Per-partition ordering** within an area, since the rule engine relies on event order to maintain redundancy state per area.
- **Operational maturity** — this is critical infrastructure; failure modes must be well understood.

## Decision

Use **Apache Kafka** as the production backbone. For the PoC, use **Redpanda** — a Kafka-API-compatible single-binary broker with much lower memory and ops footprint, suitable for Docker Compose.

- **Topics:**
  - `telemetry.{area_id_shard}` — sharded by hash of `area_id` into N topics (initially N=16). Each topic has 16 partitions. Partition key = `area_id`. This guarantees per-area ordering and bounds partition count to a manageable number.
  - `alerts.threshold`, `alerts.malfunction`, `alerts.priority` — separate topics so the priority-1 alert path can have its own consumer group with isolated lag SLO.
  - `sensor-status` — broker LWT events; consumed by rule engine for FR-08 redundancy tracking.
- **Replication factor:** 3, min ISR 2 (production); 1 (PoC).
- **Retention:** 7 days hot on telemetry topics, 30 days on alert topics.
- **Compression:** zstd (better ratio than snappy at modest CPU cost; energy positive when network egress is the bottleneck — NFR-07).

## Considered Alternatives

### A1. RabbitMQ
- **Pros:** Mature; rich routing; lower operational complexity than Kafka.
- **Cons:** Designed as a message broker, not a log — replay requires explicit re-publication; consumer-side state for ordering is awkward; throughput at 645K msg/min requires careful tuning of Streams plugin which is essentially Kafka's model bolted on.
- **Verdict:** rejected — replay and partitioned ordering are first-class needs.

### A2. Apache Pulsar
- **Pros:** Tiered storage built in; geo-replication; segment-based architecture scales storage independently of compute.
- **Cons:** Smaller community than Kafka; Faust/Flink Kafka connectors are battle-tested, Pulsar connectors less so; operational expertise scarcer in the Italian/EU consulting market (relevant for the cost-estimation deliverable, NFR-08).
- **Verdict:** rejected — Pulsar's strengths (tiered storage, geo-replication) are not in the Phase 0 / 1 scope.

### A3. Redpanda for production too
- **Pros:** Same Kafka API, simpler ops (single binary, no ZooKeeper), better tail latency.
- **Cons:** Smaller ecosystem; commercial support model less mature in EU; harder to staff.
- **Verdict:** kept as PoC choice; production stays on Kafka. The Kafka API contract means the migration path is one-way reversible.

### A4. Cloud-native managed (AWS MSK / Confluent Cloud / GCP Pub/Sub)
- **Pros:** No ops burden; SLA-backed.
- **Cons:** Cost (NFR-08); vendor lock-in (the cost model in Phase 5 will compare them); GCP Pub/Sub doesn't preserve partition ordering the way Kafka does.
- **Verdict:** documented as production deployment alternative in the cost BoM (Phase 5); architecture is portable because we use only the open Kafka API.

## Consequences

**Positive**
- Replay enables Phase 5 chaos-test recovery (QAS-02), Phase 5 burst load tests (QAS-04), and rule changes without data loss.
- Partition-by-area gives natural horizontal scaling unit (NFR-01) and isolates one storm-affected region from others.
- Multi-consumer model lets future consumers attach without changes to producers (NFR-09).

**Negative**
- Kafka in production is operationally non-trivial — needs broker monitoring, partition rebalancing, ZooKeeper or KRaft mode management. Mitigated by managed-service option in BoM.
- Topic + partition count is a long-lived schema decision (you can add partitions but it disturbs key ordering). The 16-shard / 16-partition initial number is sized for ~256-way parallelism, well above expected need.

**Risks**
- Choosing Redpanda for PoC and Kafka for production introduces a small drift risk (some admin APIs differ). Mitigated by using only Kafka client API surface and avoiding broker-specific admin tooling in code.
