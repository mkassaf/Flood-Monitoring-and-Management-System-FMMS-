# ADR-004 — Telemetry store: TimescaleDB

**Status:** Accepted (Phase 1)
**Related:** ADR-003 (writers consume from Kafka), ADR-001

## Context

Telemetry is time-series, append-mostly:

- **Write rate:** 150K msg/min nominal, ~645K msg/min burst.
- **Read patterns:**
  - Latest reading per sensor (served from Redis hot cache, not the store).
  - Range queries per sensor or per area for historical dashboards (recent-hours window).
  - Aggregated rollups per area / city / region (downsampled).
- **Retention:** 90 days hot per Phase 0 working assumption; older data summarized.
- **Schema evolution:** new sensor types may add new columns/parameters (NFR-09).

The operational store (`opdb`) is a separate concern (areas, sensors, alerts, users) — relational, transactional, low-volume. This ADR covers the *telemetry* store only.

## Decision

Adopt **TimescaleDB** (PostgreSQL extension) as the telemetry store.

- Hypertable `telemetry` partitioned on `(time, area_id)` with 1-day chunks.
- **Continuous aggregates** at 1-minute and 1-hour granularity for dashboard queries.
- **Compression policy:** compress chunks older than 7 days (10–20× ratio is typical).
- **Retention policy:** drop raw chunks older than 90 days; keep continuous aggregates indefinitely.
- Write path: telemetry-service does **batched COPY** (1-second windows, ~10K rows/batch) — much cheaper than per-row INSERT at this rate.

## Considered Alternatives

### A1. InfluxDB (OSS or Cloud)
- **Pros:** Purpose-built TSDB; tag-based query model is ergonomic for sensor data.
- **Cons:** OSS InfluxDB has had unstable major version transitions (1.x → 2.x → 3.x); query language churn (InfluxQL → Flux → SQL); operational ergonomics (cardinality limits) require careful schema design at 150K sensors. The cardinality of `(area_id, sensor_id, parameter)` is in the millions — historically a danger zone.
- **Verdict:** rejected — TimescaleDB's reliance on PostgreSQL gives a stable, well-understood substrate.

### A2. ClickHouse
- **Pros:** Outstanding compression and read performance for analytical queries; designed for very high write rates.
- **Cons:** Operational expertise less common; UPDATE/DELETE semantics non-trivial (mutations are async); team productivity hit while learning. Excellent fit if/when read load becomes the bottleneck — kept as fallback.
- **Verdict:** rejected for now; documented as the migration target if write throughput or query latency becomes a bottleneck (R-04 in risk register).

### A3. Plain PostgreSQL (no Timescale)
- **Pros:** Simplest possible stack.
- **Cons:** Manual partitioning of time-series tables is painful; query optimizer doesn't know about time semantics; no continuous aggregates (must be hand-rolled with materialized views and refresh logic).
- **Verdict:** rejected — Timescale is a thin extension over PostgreSQL that solves exactly these problems.

### A4. Kafka topic as the store (no DB)
- **Pros:** Zero additional infrastructure; offset-based replay.
- **Cons:** Random-access reads (range queries by sensor/time) are not what a log is for; compaction at this cardinality would not bound storage; UI dashboards would require a DB anyway.
- **Verdict:** rejected — the log is the source of truth for ingestion ordering, not for query.

## Consequences

**Positive**
- PostgreSQL substrate means familiar tooling (psql, pgAdmin, asyncpg), familiar ops (pg_dump, streaming replication), and the same connection driver used by `opdb` — reducing the dependency surface.
- Continuous aggregates push the dashboard-rollup work down into the DB layer, eliminating the need for a separate OLAP system at this scale.
- Compression on cold chunks is essentially free (read amplification is negligible for cold data).

**Negative**
- Single-node TimescaleDB has a write ceiling. Production needs managed Timescale Cloud or a self-hosted cluster with multi-node Timescale (commercial). This is a known scaling boundary; documented in R-04.
- The 90-day hot retention sized in Phase 0 needs validation against actual storage at full scale — at 150K sensors × 1 msg/min × 90 days = ~19.4 B rows. Compression brings this to a workable footprint, but capacity planning must be redone for the BoM.

**Risks**
- If multi-node Timescale licensing becomes a blocker, evacuation path is ClickHouse for the analytical store, with TimescaleDB retained for short-term hot data only.
