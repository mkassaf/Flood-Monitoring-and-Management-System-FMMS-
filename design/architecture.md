# FMMS — Phase 1: Software Architecture Document

**Project:** Flood Monitoring and Management System (FMMS)
**Course:** Software Architectures 2024–2025 — Prof. Henry Muccini, UnivAQ
**Document purpose:** Lock the architecture: style, decomposition, deployment, NFR realization. Read alongside `workspace.dsl` (renderable C4 views) and `docs/adr/` (ADRs).

---

## 1. Architectural Drivers (recap)

This phase resolves the architecture against the requirements locked in Phase 0. Drivers, in order of architectural impact:

1. **Throughput at scale (NFR-01, NFR-03)** — sustained 150K msg/min, burst envelope ~645K msg/min (D-01).
2. **Reliability under partial failure (NFR-02)** — no message loss on the alert path; ≥99.9% availability.
3. **Energy efficiency (NFR-07)** — measurable J/msg with adaptive sampling and idle-aware autoscaling. (Highest-leverage driver for the thesis-relevant evaluation.)
4. **Security at scale (NFR-04)** — sensor identity for 150K endpoints, RBAC for users.
5. **Modifiability + Maintainability (NFR-06, NFR-09)** — independently deployable services, plug-in extensibility for alert channels.

---

## 2. Architectural Style

**Decision:** event-driven microservices with a Kafka backbone for the core data plane, synchronous REST for control-plane operations, WebSockets for UI push. Full reasoning in **ADR-001**.

**Why event-driven, not request-response monolith / classical layered:**
- Decouples ingestion rate from processing rate — bursts buffer in the broker rather than overwhelming downstream services. Direct enabler for QAS-04.
- Multiple independent consumers can subscribe to the same telemetry stream (telemetry persistence, rule evaluation, future ML inference) without coordination. Direct enabler for NFR-09.
- Per-area partitioning gives natural horizontal scaling. Direct enabler for NFR-01.

**Why microservices, not modular monolith:**
- Different services have different scaling profiles (ingestion is throughput-bound, dashboard-bff is connection-bound, geo-service is mostly idle). Independent autoscaling saves both cost and energy (NFR-07, NFR-08).
- Independent deployability satisfies QAS-07 (per-service rolling update).

**Trade-offs accepted:** higher operational complexity and observability burden — addressed by NFR-10 and ADR-008.

---

## 3. C4 — Views

The full structure is in `workspace.dsl`. Render with `structurizr-cli` or upload to https://structurizr.com/dsl. Summary below.

### 3.1 System Context
FMMS receives telemetry from the **Sensor Fleet** (external) and serves **Area / City / Regional Managers** plus a **System Operator**. A **Notification Channels** external system is shown but out of PoC scope (extensibility surface for Phase 7+).

### 3.2 Container view — responsibilities

| Container | Responsibility | Stateless? | Scaling axis |
|---|---|---|---|
| **MQTT Broker** (Mosquitto) | Terminate sensor connections; per-sensor topics; QoS 1 | No (session state) | Connections; cluster horizontally |
| **Ingestion Gateway** | MQTT→Kafka bridge; identity check; schema validation; partition by `area_id` | Yes | Replicas behind broker subscribers |
| **Event Backbone** (Kafka) | Durable, partitioned event log | No (replicated) | Partitions per topic |
| **Telemetry Service** | Consume telemetry; batched writes to TimescaleDB; update Redis hot state | Yes | Consumer group size = partition count |
| **Rule Engine** | Stream-process telemetry; evaluate thresholds; track area-level redundancy; emit alerts | Mostly (state in Redis) | Consumer group size |
| **Alert Service** | Dedup, prioritize, persist, route to UI; plugin port for out-of-band channels | Yes | Replicas |
| **Geo Service** | Areas, sensors, sensor↔area, area↔manager, threshold config | Yes | Replicas (rarely needed) |
| **Auth Service** | JWT issuance, scope assertion, token validation | Yes | Replicas |
| **Dashboard BFF** | Aggregate live + historical for UI; enforce RBAC; WebSocket fan-out | Mostly (WS connections) | Replicas; WS connections per pod |
| **Frontend SPA** | React + Leaflet; role-conditional landing; map + alert list + sensor drill-down | n/a (browser) | CDN-fronted static |
| **Telemetry Store** (TimescaleDB) | Time-series measurements; 90d hot; continuous aggregates | No | Vertical + read replicas |
| **Operational Store** (PostgreSQL) | Areas, sensors, managers, alerts (audit), thresholds, users | No | Vertical + read replicas |
| **Hot State Cache** (Redis) | Last-known sensor state; alert summaries; redundancy state | No | Cluster; sharded by `area_id` |
| **Metrics** (Prometheus + Grafana) | Throughput, lag, latency, J/msg dashboards | No | Federated for HA |
| **Logs + Traces** | Structured logs + OpenTelemetry traces | No | Cluster |

---

## 4. Component-level decomposition (key containers)

Component-level diagrams change frequently and are not worth maintaining as Structurizr models in Phase 1. They are described textually here; reify them as Structurizr `component` views in Phase 4 once the implementation stabilizes.

### 4.1 Ingestion Gateway

- `mqtt_subscriber` — async MQTT 5 client; one connection per broker node it consumes from.
- `identity_resolver` — caches sensor→area binding from geo-service (TTL 5 min); rejects unknown sensor IDs.
- `schema_validator` — Pydantic models for the canonical telemetry envelope; drops + audits malformed.
- `kafka_producer` — async aiokafka producer; partition key = `area_id`; batched sends (10 ms / 64 KB).
- `metrics_emitter` — Prometheus client; counters for accepted/rejected, histogram for end-to-end gateway latency.

### 4.2 Rule Engine

- `telemetry_consumer` — Faust agent; one stream per topic.
- `threshold_evaluator` — pure function; consults per-area thresholds from a 1-minute-cached snapshot of geo-service.
- `redundancy_tracker` — area-keyed state in Redis: count of operational sensors per parameter per area. Updated on each `sensor_status` event. Source of truth for FR-08 escalation.
- `alert_emitter` — produces to `alerts.threshold` / `alerts.malfunction` / `alerts.priority` based on classification.
- `replay_harness` — supports replay from broker offset for testing FR-08 escalation paths.

### 4.3 Dashboard BFF

- `auth_middleware` — validates JWT on every request; extracts scope.
- `scope_filter` — translates user scope (zone / city / region) to the set of `area_id`s the user may read; enforced on all reads.
- `live_view` — WebSocket endpoint; subscribes per-connection to the relevant Redis Pub/Sub channels for the user's areas; pushes deltas only.
- `query_view` — REST endpoints for historical telemetry + alerts; pushes scope filter into SQL `WHERE` clauses.
- `aggregator` — pre-computes city/region rollups; cached in Redis with short TTL.

---

## 5. Use case flows

### 5.1 Case 1 — River sensor exceeds threshold

```
Sensor S (area A) → MQTT Broker → Ingestion Gateway
                                     ↓ partition=A
                                   Kafka: telemetry.A
                                     ↙        ↘
                          Telemetry Service   Rule Engine
                                ↓                ↓
                          TimescaleDB      classify → alerts.threshold
                          + Redis state           ↓
                                              Alert Service
                                                  ↓ (Redis Pub/Sub)
                                             Dashboard BFF
                                                  ↓
                                            WebSocket → Area Manager UI
                                                       → City Manager UI
```

End-to-end SLA: ≤2s P95 (QAS-04).

### 5.2 Case 2 — Storm across regions (burst)

Same path as Case 1 but at higher cardinality. Adaptive frequency (FR-10) at sensor pushes traffic into critical mode. Kafka partition headroom and stateless service autoscaling absorb the burst (D-01 envelope). Regional Manager UI subscribes to per-region rollups (`aggregator` component) rather than per-sensor streams to keep WebSocket fan-out tractable.

### 5.3 Case 3 — Malfunction + redundancy

```
Sensor S1 (area A) stops transmitting OR sends status=0
   → Ingestion Gateway emits sensor_status event
       → Rule Engine.redundancy_tracker decrements operational count for area A
           if count > 0 → alerts.malfunction (low priority)
           if count == 0 → alerts.malfunction (high priority) + alerts.priority (escalation)
```

The redundancy state is held in Redis, keyed by `(area_id, parameter)`. Recovery (sensor reports status=1 again) increments the count and clears the escalation.

---

## 6. Deployment topology

### 6.1 Production
- Single cloud region, multi-AZ for reliability (NFR-02).
- Kafka cluster: 3 brokers across AZs, replication factor 3, min ISR 2.
- Mosquitto: 2-node active/active cluster (shared session state via persistence).
- Stateless services on Kubernetes with HPA driven by Kafka consumer lag (custom metric).
- Stateful stores as managed services (managed PostgreSQL with Timescale extension, managed Redis).
- Frontend SPA on CDN; static assets versioned per release.
- Per-NFR autoscaling targets:
  - Ingestion gateway: scale on MQTT message rate (target: 80% of per-pod capacity).
  - Telemetry service: scale on Kafka consumer lag (target: <500ms P95).
  - Rule engine: scale on Kafka consumer lag.
  - Dashboard BFF: scale on active WebSocket connections (target: 80% of per-pod connection budget).

### 6.2 PoC
- Single host, Docker Compose.
- Single-node Mosquitto, single-broker Kafka (or Redpanda for lower memory footprint).
- All services as containers; one replica each.
- TimescaleDB, PostgreSQL (could be a single Postgres+Timescale instance with logical schemas), Redis: one instance each.
- Sensor simulator generates ~1,000 simulated sensors at the locked frequencies (60s nominal / 5s critical).
- Prometheus + Grafana included; CodeCarbon attached to each Python service for energy measurement.

---

## 7. Cross-cutting concerns

### 7.1 Schema & contract management
- Telemetry envelope: JSON Schema v2020-12, versioned. Schema registry (Apicurio or Confluent OSS) holds the canonical definition; Kafka producers/consumers reference by schema ID.
- REST APIs: OpenAPI 3.1, generated from FastAPI. Frontend SDK generated from OpenAPI at build time.
- Versioning: additive changes are backward-compatible; breaking changes require new topic + dual-write window.

### 7.2 Identity & authorization
- Sensors: per-area X.509 cert + per-sensor token (ADR-006).
- Users: JWT with scope claim encoding `(role, jurisdiction_ids)` (ADR-007).
- Authorization is enforced at the dashboard-bff (the only user-facing data plane). Internal service-to-service calls use mTLS with service identities (issued by a small in-cluster CA).

### 7.3 Time
- Sensors NTP-sync; ingestion gateway also stamps `ingested_at` (server time). Both timestamps are persisted. Threshold evaluation uses `ingested_at` to avoid replay/clock-skew attacks.

### 7.4 Backpressure
- MQTT broker → ingestion: TCP backpressure via consumer slowdown.
- Ingestion → Kafka: bounded producer buffer; on overflow, drop the *oldest* nominal-mode reading from the same sensor (preserve criticals). Logged + metric.
- Kafka → consumers: consumer-side rate limiting via prefetch; lag is the autoscale signal.

### 7.5 Energy instrumentation (NFR-07)
- CodeCarbon attached to each Python service: emissions exported as Prometheus metric `co2_g_total` and converted to `joules_per_message` via throughput counters.
- Sensor sim reports its own duty-cycle metric (sleep_pct) to model field deployment.
- Grafana panel: J/msg per service over time, segmented by load mode (nominal / critical).

---

## 8. NFR → Tactics mapping (Bass / Clements / Kazman)

This is the contract between requirements (Phase 0) and the architecture (this document). Each tactic ties to a concrete realization.

### Scalability (NFR-01)
| Tactic category | Tactic | FMMS realization |
|---|---|---|
| Resource demand mgmt | Manage event rate | Adaptive sensor frequency (FR-10); edge filtering for redundant readings |
| Resource demand mgmt | Reduce computational overhead | Batched DB inserts (telemetry-service); Faust agent fusion (rule-engine) |
| Resource arbitration | Increase resources | Kafka partitioning by `area_id`; HPA on stateless services |
| Resource arbitration | Bound queue sizes | Kafka topic retention bounded; consumer-lag alarm at SLO threshold |

### Availability / Reliability (NFR-02)
| Tactic category | Tactic | FMMS realization |
|---|---|---|
| Fault detection | Heartbeat | K8s liveness/readiness probes; sensor heartbeat (status flag) |
| Fault detection | Monitor | Prometheus alerting on lag, error rate, partition under-replication |
| Recovery preparation | Active redundancy | Kafka RF=3, min ISR=2; multi-replica stateless services |
| Recovery preparation | Passive redundancy / spare | TimescaleDB primary+replica; Mosquitto active/active |
| Recovery reintroduction | Rollback | K8s rolling update with auto-rollback on probe failure |
| Recovery reintroduction | Replay | Kafka offset replay for rule engine and alert reconstruction |
| Fault prevention | Removal from service | Circuit breaker (resilience4py / aiobreaker) on inter-service calls |

### Performance (NFR-03)
| Tactic category | Tactic | FMMS realization |
|---|---|---|
| Resource demand mgmt | Reduce computation | Pre-aggregated rollups in Redis for region/city dashboards |
| Resource demand mgmt | Prioritize events | Separate Kafka topics for `alerts.priority` (priority-1 consumer group) |
| Resource arbitration | Concurrency | One Kafka partition per consumer thread; partition count = peak parallelism |
| Resource arbitration | Maintain multiple copies of data | Hot state in Redis, durable in TimescaleDB |

### Security (NFR-04)
| Tactic category | Tactic | FMMS realization |
|---|---|---|
| Resist attacks | Authenticate actors | Sensor mTLS + token (ADR-006); user JWT (ADR-007) |
| Resist attacks | Authorize actors | RBAC scope at dashboard-bff; SQL `WHERE area_id IN scope` |
| Resist attacks | Encrypt data | TLS 1.3 in transit; PostgreSQL at-rest encryption; Kafka in-transit TLS |
| Resist attacks | Limit exposure | No direct sensor → backbone path; ingestion gateway is the only crossing point |
| Detect attacks | Audit trail | All denied access + all writes appended to audit log in opdb |
| React to attacks | Revoke access | Token denylist in Redis; sensor cert revocation via short-lived certs |

### Usability (NFR-05)
| Tactic category | Tactic | FMMS realization |
|---|---|---|
| Support user initiative | Aggregate | Pre-computed city/region rollups; alert grouping by area |
| Support user initiative | Cancel / acknowledge | Alert ack with reason persisted to audit log |
| Support system initiative | User model | Role-driven landing view; map auto-focuses on user jurisdiction |

### Maintainability (NFR-06) + Modifiability (NFR-09)
| Tactic category | Tactic | FMMS realization |
|---|---|---|
| Modules | Increase cohesion | One bounded context per service |
| Modules | Reduce coupling | Async event-driven communication; schema registry; OpenAPI contracts |
| Defer binding | Plugin pattern | Alert service has notification-channel plugin port (modifiability for Phase 7+) |
| Tools | Configuration mgmt | Helm charts + env-driven config; no per-env code paths |

### Energy Efficiency (NFR-07)
| Tactic category | Tactic | FMMS realization |
|---|---|---|
| Resource mgmt | Manage event rate | Adaptive frequency at sensor (FR-10); edge filtering |
| Resource mgmt | Reduce computational overhead | Idle-aware autoscale-down; warm-pod preference in load balancer |
| Allocation | Workload consolidation | Co-locate low-traffic services (geo, auth) on shared nodes |
| Measurement | Energy accounting | CodeCarbon per service → Prometheus `joules_per_message` |
| Measurement | Energy budget | Documented J/msg budget per service; alerts on budget breach |

### Cost (NFR-08)
| Tactic | FMMS realization |
|---|---|
| Right-sizing | Per-service resource limits derived from load test (Phase 5) |
| Spot/reserved mix | Spot for stateless pool; reserved for stateful stores; on-demand for ingestion (latency-sensitive) |
| Storage tiering | TimescaleDB continuous aggregates + 90d hot; warm/cold tiering documented for Phase 7+ |

### Observability (NFR-10)
| Tactic | FMMS realization |
|---|---|
| Metrics | Prometheus on every service; one Grafana panel per NFR with documented threshold |
| Tracing | OpenTelemetry from gateway through alert delivery |
| Logging | Structured (JSON) logs; correlation ID propagated via Kafka headers |

---

## 9. Risk register

| ID | Risk | Mitigation | Severity if unmitigated |
|---|---|---|---|
| R-01 | Burst envelope (D-01) underestimates real storm load | Load test up to 4× burst envelope; document headroom in SAD | High |
| R-02 | Per-sensor X.509 ops cost prohibitive at 150K | ADR-006 uses per-area cert + per-sensor token; revisit at Phase 7+ | Medium |
| R-03 | Faust unmaintained; rule engine becomes maintenance burden | ADR-005 documents Flink as evacuation path; keep rule logic in pure functions | Medium |
| R-04 | TimescaleDB write throughput bottleneck at full scale | Continuous aggregates + write-side batching; ADR-004 documents ClickHouse as fallback | Medium |
| R-05 | WebSocket fan-out at 50 concurrent regional managers × ~50K sensors | Pre-aggregate at BFF; deltas only; per-area Redis Pub/Sub channels | Medium |
| R-06 | Kafka cluster ops complexity in PoC environment | PoC uses Redpanda (Kafka-compatible, single binary) | Low |
| R-07 | Energy measurements via CodeCarbon are estimates, not measurements | Document methodology limitations in Phase 5 report; cross-check with Scaphandre on Linux hosts | Low |
| R-08 | RBAC bypass through direct service access | Service-to-service mTLS; only dashboard-bff is user-reachable | High (if not enforced) |

---

## 10. ADR index

Architectural Decision Records are in `docs/adr/`. All in MADR format (Status / Context / Decision / Considered Alternatives / Consequences).

| ID | Title | Status |
|---|---|---|
| ADR-001 | Architectural style: event-driven microservices | Accepted |
| ADR-002 | Edge protocol: MQTT 5 over TLS | Accepted |
| ADR-003 | Streaming backbone: Apache Kafka (Redpanda for PoC) | Accepted |
| ADR-004 | Telemetry store: TimescaleDB | Accepted |
| ADR-005 | Stream processing: Faust (PoC), Flink (production option) | Accepted |
| ADR-006 | Sensor identity: per-area X.509 + per-sensor token | Accepted |
| ADR-007 | User authentication: JWT with scope claims | Accepted |
| ADR-008 | Deployment: Kubernetes (production) / Docker Compose (PoC) | Accepted |
| ADR-009 | Real-time UI push: WebSocket via dashboard-bff | Accepted |
| ADR-010 | Topic partitioning: by `area_id` | Accepted |

---

## 11. Exit criteria for Phase 1

- [x] Architectural style decided and justified against Phase 0 drivers.
- [x] C4 Context, Container, and Deployment views defined as code (`workspace.dsl`).
- [x] Container responsibilities, scaling axes, and statefulness documented.
- [x] Component-level decomposition for the three highest-risk containers.
- [x] All three Phase 0 use cases traced through the architecture.
- [x] Every NFR mapped to at least one tactic with a concrete realization.
- [x] Every consequential decision has an ADR.
- [x] Risk register with mitigations.

Next: **Phase 2 — Technology stack lock and project skeleton** (lock specific versions, generate the monorepo scaffold, write `CLAUDE.md` and per-service `README.md` so the implementation phases are Claude-Code-ready).
