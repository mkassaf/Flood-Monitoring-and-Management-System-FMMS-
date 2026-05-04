# ADR-005 — Stream processing: Faust (PoC), Flink (production option)

**Status:** Accepted (Phase 1)
**Related:** ADR-003 (Kafka), ADR-001

## Context

The rule engine consumes telemetry events from Kafka and must:

- Evaluate per-parameter thresholds (FR-06) — pure stateless function per event.
- Maintain area-level redundancy state (FR-08) — keyed by `(area_id, parameter)`, mutated on every status change. State must survive consumer restart.
- Emit alerts to downstream Kafka topics, partitioned by area for downstream ordering.
- Support replay from arbitrary Kafka offset for testing FR-08 escalation paths.

The team has Python expertise and has been building agentic-AI tooling primarily in Python (LangGraph, FastAPI, etc.). The PoC must run on a developer laptop in Docker Compose.

## Decision

For the **PoC**: use **Faust** (Python async stream processing library, Kafka Streams-like). Specifically the maintained community fork `faust-streaming`.

For **production**: keep the rule logic written as pure functions (`evaluate_thresholds(event, thresholds) -> [Alert]`, `update_redundancy(state, event) -> (new_state, [Alert])`) so it can be hosted by either Faust or **Apache Flink** without rewriting the domain logic.

State store:
- PoC: Faust's RocksDB-backed table.
- Production: Redis (already in the stack) for low-volume state; revisit if state grows.

## Considered Alternatives

### A1. Apache Flink (from the start)
- **Pros:** Industry-standard, JVM-based, strong exactly-once guarantees, scales to massive throughput, widely deployed for similar workloads.
- **Cons:** JVM operational footprint heavy in Docker Compose; team productivity hit; the alert latency budget (≤2s P95) is achievable in Faust at PoC scale; introduces a second runtime (JVM alongside Python) for a small piece of the pipeline.
- **Verdict:** rejected for PoC; documented as the production option if Faust becomes a bottleneck.

### A2. Kafka Streams (Java)
- **Pros:** First-class Kafka integration; mature.
- **Cons:** Same JVM-overhead argument; binds the team to writing Java for a single service.
- **Verdict:** rejected.

### A3. Custom Python consumer (no framework)
- **Pros:** Minimal dependencies; full control.
- **Cons:** Reimplements offset management, state store, agent fan-out, rebalancing. Faust solves these. The "framework tax" is small relative to the engineering cost.
- **Verdict:** rejected.

### A4. Materialize / RisingWave (streaming SQL)
- **Pros:** Declarative; SQL is familiar; great for sliding-window aggregates.
- **Cons:** The redundancy logic (FR-08) is not naturally a windowed aggregate — it's a state machine keyed by area; SQL fits awkwardly. Adds another infrastructure component.
- **Verdict:** rejected — wrong tool shape for the dominant rule.

## Consequences

**Positive**
- Single-language stack for the PoC reduces cognitive load.
- Pure-function domain logic is easy to unit-test and is portable to Flink without rewriting.
- Faust agents map naturally to bounded-context boundaries.

**Negative**
- `faust-streaming` is community-maintained; commercial support is unavailable. Mitigated by pure-function domain logic + documented Flink evacuation path.
- Faust performance ceiling is below Flink. Acceptable at PoC scale; revisit if load test in Phase 5 shows headroom is insufficient at the burst envelope.

**Risks**
- If `faust-streaming` becomes unmaintained, migration to Flink is a real project (not trivial despite portable rules — the runtime around the rules differs). Treat this as R-03 in the risk register.
