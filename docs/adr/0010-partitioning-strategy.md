# ADR-010 — Topic partitioning: by `area_id`

**Status:** Accepted (Phase 1)
**Related:** ADR-003 (Kafka), ADR-005 (rule engine), NFR-01

## Context

Kafka topic partition strategy is one of the most consequential decisions in an event-driven system: it fixes the unit of parallelism, the unit of ordering, and the unit of failure isolation. It is hard to change after launch (adding partitions disturbs key-based ordering).

For FMMS, the dominant access patterns are:

- **Per-area ordering required** by the rule engine: redundancy state (FR-08) is keyed by area, and out-of-order events corrupt the state machine.
- **Storm bursts are spatially localized** — when one area is in critical mode, neighbors usually are too. The partitioning should keep regional bursts from starving non-affected areas.
- **Sensor-level ordering not required**: each measurement is a complete snapshot; out-of-order sensor messages within an area are tolerable for telemetry-service (insert is idempotent on `(sensor_id, ts)`).

## Decision

Partition Kafka telemetry topics by **`area_id`** (hash partitioning).

- **Topic shape:** `telemetry.{shard}` where `shard = hash(area_id) mod 16`. Sixteen telemetry topics, each with sixteen partitions → 256-way parallelism upper bound.
- **Partition key for producers:** `area_id` itself (within the chosen shard topic).
- **Consumer parallelism:** consumer groups size up to the partition count per topic; one consumer can hold multiple partitions but never the inverse.
- **Alert topics** partitioned the same way for the same reason (ordering of events about an area must be preserved through to UI delivery).

Why two-level (topic shards + partitions within each)? Pure-partition partitioning at 256 partitions per topic is operationally awkward (rebalancing storms on consumer add/remove). Sharding into 16 topics × 16 partitions gives the same parallelism with smaller rebalance blast radius and the option to migrate individual shards to dedicated clusters later.

## Considered Alternatives

### A1. Partition by `sensor_id`
- **Pros:** Maximum write parallelism; no hot partitions even within an area.
- **Cons:** Rule engine cannot maintain per-area state without aggregating across partitions (which means cross-partition ordering is lost). Defeats FR-08.
- **Verdict:** rejected — breaks the rule engine.

### A2. Partition by `(area_id, parameter)`
- **Pros:** Finer-grained parallelism; rule engine can shard threshold evaluation by parameter.
- **Cons:** Multiplies partition count by 5 (number of parameters); cross-parameter rules (e.g., "high water + high rainfall = priority alert") become harder to express; not currently needed.
- **Verdict:** rejected — premature optimization.

### A3. Partition by `region_id`
- **Pros:** Coarser; fewer partitions; simpler to operate.
- **Cons:** During a regional storm, *all* burst load lands on one partition. Defeats QAS-04 (burst absorption depends on parallelism in the affected dimension).
- **Verdict:** rejected — concentrates rather than distributes burst load.

### A4. Round-robin (no key)
- **Pros:** Even load distribution.
- **Cons:** No ordering guarantees anywhere; rule engine impossible.
- **Verdict:** rejected.

## Consequences

**Positive**
- Per-area ordering enables FR-08 redundancy state machine without coordination.
- A regional storm distributes across the partitions of areas in that region — not concentrated on a single partition.
- 256-way upper bound on parallelism is well above the consumer count needed at 645K msg/min burst.

**Negative**
- Areas with very many sensors (the 200-sensor maximum from Phase 0) generate more traffic per partition than 10-sensor areas — partition load is uneven. Mitigated by the area-size cap from the Phase 0 sizing assumption; if real deployments exceed 200, revisit by sub-keying with `area_id + zone`.
- Adding a 17th telemetry shard topic later requires a careful migration (drain old, dual-write transition). The 16-shard sizing should be confirmed against projected sensor counts in the Phase 5 BoM.

**Risks**
- A "celebrity" area (e.g., a particular high-risk river basin under intense monitoring) could dominate one partition. Mitigated by monitoring per-partition throughput and, if needed, manually moving its area to a less-loaded shard at provisioning time.
