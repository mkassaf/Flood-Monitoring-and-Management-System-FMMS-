# ADR-001 — Architectural style: event-driven microservices

**Status:** Accepted (Phase 1)
**Deciders:** Architecture team
**Related:** ADR-003 (broker), ADR-005 (stream processor), ADR-008 (deployment), ADR-010 (partitioning)

## Context

FMMS must absorb 150K msg/min sustained and ~645K msg/min during burst (D-01), serve up to 50 concurrent managers with role-tailored views, and remain modifiable as new alert types and notification channels are added (NFR-09). Different parts of the workload have very different shapes:

- **Ingestion** — throughput-bound, latency-sensitive, write-mostly.
- **Rule evaluation** — stateful, partitionable by area, consumes the same stream as persistence.
- **User-facing dashboard** — connection-bound (WebSocket), read-mostly with bursty refresh patterns.
- **Configuration / RBAC** — low-traffic, transactional.

A single deployment unit forces the slowest-changing, lowest-traffic component to share infrastructure profile with the highest-traffic one — which is wasteful (NFR-08) and rigid (NFR-06).

The data plane is fundamentally a stream: sensors emit events; multiple downstream consumers (persistence, rule evaluation, future ML) need the same events without coordinating with each other (NFR-09). Bursts must buffer somewhere outside the consumers' memory (NFR-02).

## Decision

Adopt **event-driven microservices** with three communication modes:

1. **Asynchronous events on a durable broker (Kafka)** for the data plane: sensor telemetry and alerts.
2. **Synchronous REST (HTTPS, OpenAPI 3.1)** for the control plane: configuration, user/sensor admin, query APIs.
3. **WebSocket push** for the user-facing real-time channel (dashboard-bff → frontend).

Service decomposition follows **bounded contexts**, not technical layers. The boundaries identified in Phase 0 stand: ingestion, telemetry persistence, rule engine, alert service, geo, auth, dashboard-bff, frontend.

## Considered Alternatives

### A1. Modular monolith
- **Pros:** simpler deployment, single transactional boundary, lower operational overhead.
- **Cons:** scaling unit is the whole app — wasteful and energy-inefficient (NFR-07, NFR-08); rolling updates affect all functionality (QAS-07 fails); language/runtime locked for all components.
- **Verdict:** rejected — does not meet QAS-07 and inflates NFR-08.

### A2. Service-oriented architecture with synchronous calls only (no broker)
- **Pros:** simpler to reason about; no broker ops.
- **Cons:** tight runtime coupling — ingestion failure cascades to rule engine and alert service. Burst absorption requires per-service queues, reinventing the broker piecemeal. Replay impossible.
- **Verdict:** rejected — fails QAS-04 (burst) and QAS-02 (recovery via replay).

### A3. Serverless / FaaS data plane
- **Pros:** elastic, pay-per-use.
- **Cons:** cold start latency unacceptable for the alert path (QAS-04: ≤2s P95); per-invocation cost at 645K msg/min becomes prohibitive (NFR-08); energy accounting is opaque (NFR-07 — cannot measure J/msg accurately).
- **Verdict:** rejected — fails NFR-07 measurability and NFR-08 at burst.

### A4. Lambda architecture (batch + speed layers)
- **Pros:** classical pattern for this kind of workload.
- **Cons:** double the implementation cost (two pipelines, two codebases) for marginal benefit at PoC scale; long-term value comes mostly from historical reprocessing which Kafka offset replay already covers.
- **Verdict:** rejected — over-engineered for the stated requirements.

## Consequences

**Positive**
- Independent scaling per service satisfies NFR-01 and reduces idle compute (NFR-07, NFR-08).
- Independent deployability satisfies QAS-07.
- Broker absorbs bursts; consumers are decoupled from producer rate (QAS-04, QAS-02).
- New consumers (analytics, future ML inference, additional notification channels) attach without touching producers (NFR-09).
- Each service can choose its own runtime profile — Python/asyncio for I/O-bound, JVM Faust/Flink for state-heavy stream processing.

**Negative**
- Operational complexity (more deployable units, more network hops). Mitigated by ADR-008 (Kubernetes + Helm) and ADR-001's commitment to observability (NFR-10).
- Distributed transactions are off the table — the design must assume eventual consistency between telemetry-service writes and rule-engine state. Acceptable because the rule engine never relies on `tsdb` for its state; it uses Redis + Kafka offsets.
- Higher learning curve for new contributors. Mitigated by per-service `README.md` and `CLAUDE.md` (Phase 2 deliverable).

**Risks**
- Service decomposition that's too fine becomes a "distributed monolith." Mitigated by keeping the service count to the ten identified in Phase 0 and by using event contracts (not RPC) between services.
