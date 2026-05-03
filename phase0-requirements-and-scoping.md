# FMMS — Phase 0: Requirements Lock & PoC Scoping

**Project:** Flood Monitoring and Management System (FMMS)
**Course:** Software Architectures 2024–2025 — Prof. Henry Muccini, UnivAQ
**Document purpose:** Lock the requirement set, define quality attribute scenarios in measurable form, and fix the PoC envelope before architectural design (Phase 1) begins.

---

## 1. Functional Requirements

| ID | Requirement | Source (brief) | Priority |
|---|---|---|---|
| FR-01 | The system shall ingest periodic measurements from each sensor for: water level, river flow velocity, cumulative rainfall, soil saturation, wind speed, wind direction. | System Overview | MUST |
| FR-02 | Each sensor shall transmit an operational status flag (0/1) alongside measurements. | System Overview | MUST |
| FR-03 | Each sensor shall be uniquely identified and bound to one geographic area associated with a hydrogeological risk profile. | Objective | MUST |
| FR-04 | The system shall display a real-time visualization of environmental parameters per sensor and per area. | Key Features | MUST |
| FR-05 | The system shall support map-based selection of areas and drill-down to associated sensors. | Key Features | MUST |
| FR-06 | The system shall raise a *threshold alert* when any monitored parameter exceeds its configured safety threshold, with a clear visual indicator. | Key Features | MUST |
| FR-07 | The system shall raise a *malfunction alert* when a sensor reports `status=0` or stops transmitting beyond a timeout. | Key Features + Case 3 | MUST |
| FR-08 | Malfunction alert priority shall be computed from the residual sensor coverage in the affected area: low when ≥1 redundant sensor remains operational, escalated when all sensors covering a parameter fail. | Case 3 | MUST |
| FR-09 | The system shall raise a *priority alarm* (highest severity) for imminent danger conditions (e.g., water-level threshold breach indicating potential flood). | Key Features + Case 1 | MUST |
| FR-10 | Each sensor shall increase its transmission frequency when locally measured values cross critical thresholds, returning to nominal frequency when conditions normalize. | Tech Characteristics | MUST |
| FR-11 | The system shall route alerts to managers based on their geographic scope (Area Manager → own zone; City/Regional Manager → all zones in jurisdiction). | User Access | MUST |
| FR-12 | The system shall enforce role-based access: Area Manager (single zone), City Manager (multi-zone city view), Regional Manager (multi-city region view). | User Access | MUST |
| FR-13 | The system shall support concurrent sessions for at least 50 managers, each with a role-tailored UI. | Tech Characteristics | MUST |
| FR-14 | The system shall authenticate all users and authorize all sensor-data access against the user's geographic scope. | NFR Security | MUST |
| FR-15 | The system shall expose an aggregated regional view summarizing alert counts and severity distribution across all subordinate areas. | User Access + Case 2 | MUST |
| FR-16 | The system shall persist all sensor measurements and alerts for historical query and audit. | Implied (audit + Case replay) | SHOULD |
| FR-17 | The system shall expose a configuration interface for thresholds per parameter per area. | Implied (thresholds are not hardcoded) | SHOULD |
| FR-18 | The system shall expose a sensor-management interface (register, decommission, reassign to area). | Implied (lifecycle for 150K sensors) | SHOULD |

---

## 2. Non-Functional Requirements

| ID | Quality Attribute | Requirement | Priority |
|---|---|---|---|
| NFR-01 | Scalability | Support up to 150,000 sensors and scale horizontally + vertically without architectural change. | MUST |
| NFR-02 | Reliability | Provide redundant components and continuous operation under peak load and partial failure. | MUST |
| NFR-03 | Performance | Sustain ingestion + storage of ≥150,000 messages/minute with minimal end-to-end latency. | MUST |
| NFR-04 | Security | Encrypt sensor-to-platform transmission and enforce strong authn/authz for users. | MUST |
| NFR-05 | Usability | Provide an intuitive, role-tailored UI with clear visual feedback and easy navigation. | MUST |
| NFR-06 | Maintainability | Allow updates and scaling with minimal downtime. | MUST |
| NFR-07 | Energy Efficiency | Minimize energy at sensor (low-power modes, efficient protocols), prioritize critical-data processing, and balance load to reduce data-center energy. | MUST |
| NFR-08 | Cost (derived from "Cost Optimization") | Minimize hardware + dev cost; produce a cost estimate with explicit BoM. | MUST |
| NFR-09 | Modifiability (derived from Maintainability) | Adding new sensor types or new alert rules shall not require redeploying unrelated services. | SHOULD |
| NFR-10 | Observability (derived; required to *prove* NFR-01/02/03/07) | The system shall expose metrics, logs, and traces sufficient to validate every other NFR. | MUST |

---

## 3. Quality Attribute Scenarios

Each scenario follows the Bass/Clements/Kazman six-part form: **Source, Stimulus, Environment, Artifact, Response, Response Measure**. These are the testable contracts for Phase 5 validation.

### QAS-01 — Scalability (NFR-01)
- **Source:** Operations team (capacity planning) / sensor deployment program.
- **Stimulus:** Sensor population grows from baseline N to 150,000 over the system's lifetime; concurrent manager population grows up to 50.
- **Environment:** Production, normal operating load.
- **Artifact:** Ingestion pipeline, stream processor, telemetry store, dashboard backend.
- **Response:** New sensors and new managers are absorbed by adding broker partitions and service replicas; no schema change, no downtime, no architectural rewrite.
- **Response Measure:** End-to-end P95 latency degrades by ≤10% as load scales from 1× to 10× PoC baseline; throughput scales ≥0.85× linearly with added replicas up to 150K msg/min sustained.

### QAS-02 — Reliability (NFR-02)
- **Source:** Single component fault (broker node crash, ingestion replica OOM, DB primary failover).
- **Stimulus:** One instance of a stateless service or one node of a clustered stateful component becomes unreachable.
- **Environment:** Production, normal or peak load.
- **Artifact:** Affected service, broker cluster, downstream consumers.
- **Response:** Traffic reroutes to a healthy replica; in-flight messages with broker QoS ≥ 1 are not lost; user sessions reconnect transparently.
- **Response Measure:** Recovery time ≤30 s; committed-message loss = 0; monthly availability ≥99.9% on the critical alert path.

### QAS-03 — Performance, sustained (NFR-03)
- **Source:** Full sensor population at nominal frequency.
- **Stimulus:** 150,000 sensors transmit at 60 s nominal interval = 150,000 msg/min sustained.
- **Environment:** Production, steady state.
- **Artifact:** Ingestion gateway → broker → telemetry service → store; alert rule engine.
- **Response:** All messages are ingested, persisted, and evaluated against thresholds without queue growth.
- **Response Measure:** Throughput ≥150,000 msg/min sustained ≥1 hour; broker consumer lag <500 ms P95; ingestion-to-store latency <1 s P95.

### QAS-04 — Performance, burst (NFR-03 + FR-10)
- **Source:** Storm event triggers adaptive frequency increase across a sub-population of sensors.
- **Stimulus:** ~30% of sensors (45,000) enter critical mode at 5 s frequency; remaining 70% (105,000) stay at 60 s nominal.
  - Burst load = 45,000 × 12 + 105,000 × 1 = **645,000 msg/min**.
- **Environment:** Production, regional emergency.
- **Artifact:** Full ingestion-to-alert path + autoscaler.
- **Response:** Autoscaler adds ingestion + processing replicas; alert path remains responsive; no message loss.
- **Response Measure:** Threshold-breach → manager notification ≤2 s P95, ≤5 s P99; autoscaling stabilizes within 60 s; zero dropped messages on critical topic.

### QAS-05 — Security (NFR-04)
- **Source:** External attacker / compromised sensor / unauthorized manager.
- **Stimulus:** (a) Inject forged sensor reading; (b) intercept sensor-to-broker traffic; (c) request data outside user's geographic scope.
- **Environment:** Production.
- **Artifact:** Transport (mTLS), sensor identity (cert/token), API gateway, RBAC enforcement layer.
- **Response:** (a) rejected on identity check + logged; (b) traffic is unintelligible to interceptor; (c) request denied with 403 + audit log.
- **Response Measure:** 100% of sensor traffic mTLS-encrypted; 0 successful unauthorized data accesses in pen-test of the RBAC layer; 100% of denied access attempts logged with user, scope, target, timestamp.

### QAS-06 — Usability (NFR-05)
- **Source:** Manager (any of the three roles).
- **Stimulus:** Logs in during an active emergency.
- **Environment:** Production, ongoing alert condition in the manager's scope.
- **Artifact:** Dashboard frontend, alert summary widget.
- **Response:** Role-appropriate landing view loads, with active alerts ranked by severity, and the relevant geographic area pre-focused on the map.
- **Response Measure:** Time-to-critical-info (login submit → highest-severity alert visible) ≤3 s; new-manager training to 80% task completion ≤30 min in a usability session of n≥5.

### QAS-07 — Maintainability (NFR-06)
- **Source:** Developer.
- **Stimulus:** Deploys a new version of one microservice (e.g., rule-engine).
- **Environment:** Production.
- **Artifact:** Target service + its consumers/producers.
- **Response:** Rolling update with zero connection drops on the alert path; other services keep running.
- **Response Measure:** Per-service deployment downtime ≤10 s; rollback time ≤2 min; no other service requires redeployment.

### QAS-08 — Energy Efficiency (NFR-07)
- **Source:** Operations / sustainability stakeholder.
- **Stimulus:** System operates over a 24 h period spanning nominal load + at least one simulated burst.
- **Environment:** Production-equivalent, instrumented with energy meters at sensor sim, ingestion tier, and processing tier.
- **Artifact:** Sensor firmware (sim), MQTT bridge, stream processor, autoscaler.
- **Response:** Sensors stay in low-power transmit mode at nominal; adaptive frequency activates only on local threshold breach; compute autoscales down under low load; load balancer prefers warm nodes to avoid cold-start energy waste.
- **Response Measure:**
  - Energy per ingested message at nominal load: J/msg reported and below the no-optimization baseline by ≥20%.
  - Compute idle CPU at low load reduced ≥50% via downscaling vs. fixed-replica baseline.
  - Sensor average duty cycle at nominal: ≤5% (sleep ≥95% of the time).

> **Note (PhD-relevant framing):** QAS-08 is the strongest tie to the energy-budgeting research direction. It deliberately requires *measured* J/msg rather than only proxy metrics — the same posture the thesis takes toward agentic frameworks lacking energy budgeting (Gap 4). Treat the FMMS energy-measurement harness in Phase 5 as a transferable artifact.

### QAS-09 — Cost (NFR-08)
- **Source:** Project sponsor / course grading rubric.
- **Stimulus:** Request for production cost estimate at full scale (150K sensors, 50 managers, 24/7 operation).
- **Environment:** Design-time deliverable.
- **Artifact:** Bill of Materials (BoM) spreadsheet covering compute, storage, network egress, broker cluster, observability, IAM.
- **Response:** Itemized BoM in EUR/month for one cloud provider (AWS or GCP), with justification per line and a clearly stated load assumption (nominal vs. burst-included).
- **Response Measure:** BoM line items ≥90% of total cost are sourced from current provider price sheets; sensitivity analysis included for ±50% sensor count and ±50% burst frequency.

### QAS-10 — Observability (NFR-10)
- **Source:** Validation engineer / on-call operator.
- **Stimulus:** Need to verify that NFR-01/02/03/07 are actually being met in any given hour.
- **Environment:** Production or load test.
- **Artifact:** Metrics endpoint (Prometheus), structured logs, distributed traces.
- **Response:** Dashboards exist for throughput, lag, error rate, P95/P99 latency, energy/msg, autoscaling events.
- **Response Measure:** Every other NFR has at least one corresponding dashboard panel with a documented threshold and alarm.

---

## 4. Key Architectural Decisions Locked in Phase 0

These are not full ADRs (those come in Phase 1) but pre-design decisions needed to scope the PoC.

### D-01 — Sensor transmission frequency

**Math.** The brief constrains the system to "at least 150,000 messages/minute." With 150,000 sensors:

- 60 s nominal interval → 150,000 msg/min → exactly hits the floor at full population.
- 30 s nominal → 300,000 msg/min → already 2× the floor *before* any critical-mode burst.

**Decision.**
- **Nominal frequency: 60 s** per sensor.
- **Critical frequency: 5 s** per sensor (12× nominal), activated by local threshold breach (FR-10).
- **Burst budget assumed:** up to 30% of sensors concurrently in critical mode → **~645,000 msg/min peak**.
- The "150,000 msg/min" figure in the brief is interpreted as a **floor for steady-state** capacity. Architecture must scale beyond it for burst, via broker partitioning and stateless-consumer autoscaling.

**Mitigations.**
- Edge filtering at the sensor sim: suppress retransmission of identical readings within a small delta (configurable). Reduces nominal traffic without losing semantic information.
- Broker partitioning by `area_id` so burst load in one region does not starve consumers serving other regions.

### D-02 — PoC scale-down

**Decision.** PoC will simulate **1,000 sensors** (≈0.67% of full scale), running on a single dev machine via Docker Compose. Manager population in PoC: **5 simulated users covering all 3 roles**.

**Validation strategy.**
- All NFR scenarios are exercised at PoC scale.
- Performance and scalability scenarios additionally include a **load-test extrapolation argument**: measured throughput at PoC scale + measured per-replica capacity → projected resource count for 150K sensors, with explicit linearity and headroom assumptions stated. This goes into the Phase 5 SAD.

### D-03 — PoC scope (in / out)

**IN scope for the PoC:**
- All 18 FRs implemented end-to-end against simulated sensors.
- All 3 brief use cases (Case 1 threshold breach, Case 2 multi-region storm, Case 3 redundant-sensor failure) demonstrable.
- Real-time dashboard with role-conditional views.
- RBAC across the three manager roles.
- Adaptive transmission frequency (FR-10) implemented in the sensor sim.
- Energy measurement harness producing J/msg numbers.
- Load test exercising QAS-03 and QAS-04 at scaled load.
- Chaos test exercising QAS-02 (kill one replica, verify no message loss).
- Cost BoM for the *production* deployment.

**OUT of PoC scope (documented but not built):**
- Real sensor hardware, LoRa/cellular uplinks — replaced by MQTT-over-TCP simulation.
- Geographically distributed multi-DC deployment — single-region cloud assumed in cost model.
- Mobile push notifications — replaced by in-dashboard WebSocket alerts.
- Production-grade IAM (Keycloak, federated SSO) — replaced by JWT + local user store with RBAC scopes.
- Long-term archival tiering (S3 cold storage) — only hot/warm storage in PoC.
- Full disaster-recovery drill across regions — single-AZ failure injection only.

### D-04 — Critical thresholds (placeholder values for PoC)

These are *not* hydrogeologically calibrated; they are placeholders sufficient to drive the alert pipeline. Real values would come from a domain expert.

| Parameter | Nominal range | Warning | Critical |
|---|---|---|---|
| Water level (m above reference) | 0–2.0 | 2.0–3.0 | >3.0 |
| River flow velocity (m/s) | 0–2.5 | 2.5–4.0 | >4.0 |
| Cumulative rainfall (mm/h) | 0–10 | 10–30 | >30 |
| Soil saturation (%) | 0–70 | 70–90 | >90 |
| Wind speed (m/s) | 0–15 | 15–25 | >25 |

Stored per-area in the configuration store (FR-17), so they can be overridden per geography without code change.

---

## 5. Traceability Matrix

| Use Case | Primary FRs | Primary NFRs |
|---|---|---|
| Case 1 — River sensor exceeds threshold; area + city alerted | FR-01, FR-04, FR-06, FR-09, FR-10, FR-11 | NFR-03 (alert latency), NFR-05 |
| Case 2 — Storm across regions; regional emergency view | FR-04, FR-05, FR-09, FR-11, FR-15 | NFR-01, NFR-03 (burst), NFR-05 |
| Case 3 — Sensor malfunction with backup; escalation if both fail | FR-02, FR-07, FR-08, FR-11 | NFR-02, NFR-10 |

| FR | Implementing service (anticipated) |
|---|---|
| FR-01, FR-02, FR-03 | sensor-simulator → ingestion-gateway → telemetry-service |
| FR-04, FR-05, FR-15 | dashboard-bff → frontend |
| FR-06, FR-07, FR-08, FR-09, FR-10 | rule-engine → alert-service |
| FR-11, FR-12, FR-13, FR-14 | auth-service + RBAC enforcement at dashboard-bff |
| FR-16 | telemetry-service (TimescaleDB) + alert-service (PostgreSQL) |
| FR-17, FR-18 | geo-service (admin endpoints) |

---

## 6. Stakeholder Concerns Map

| Stakeholder | Primary concerns | Driving requirements |
|---|---|---|
| Area Manager | Fast situational awareness for own zone; low false-positive rate on alerts | FR-04, FR-06, FR-09, NFR-05 |
| City / Regional Manager | Cross-zone aggregation; ability to triage during storm | FR-15, NFR-01, NFR-03 |
| System Operator | Uptime, recovery, observability | NFR-02, NFR-06, NFR-10 |
| Sponsor / Procurement | Cost predictability and scaling cost curve | NFR-08 |
| Sustainability stakeholder | Energy footprint of compute + sensor fleet | NFR-07 |
| Security officer | Sensor identity, transport, RBAC, audit | NFR-04, FR-14 |
| Software developer | Ability to evolve service-by-service | NFR-06, NFR-09 |

---

## 7. Open Questions and Assumptions to Validate

These are deferred to Phase 1 ADRs, but flagged here so they don't get silently resolved.

1. **Brief vs. burst capacity.** The "150K msg/min" figure is treated as a floor for steady state. Confirm with the course brief that designing for ~600K msg/min peak is the intended interpretation. (Decision D-01.)
2. **Sensor identity model.** Per-sensor X.509 cert is the secure baseline but ops-heavy at 150K. Alternative: per-area cert + per-sensor token. To be decided in an ADR with explicit threat model.
3. **Manager population growth.** Brief caps concurrent managers at 50; total manager accounts could be larger. Authn store sizing assumes ≤500 total accounts. Confirm.
4. **Alert delivery channels beyond UI.** Out of PoC scope but commonly expected by stakeholders (SMS, email). Document as a Phase 7+ extension; ensure the alert-service has an outbound port that can plug in additional channels (modifiability — NFR-09).
5. **Sensor data retention period.** Not specified in brief. Working assumption: 90 days hot in TimescaleDB, summarized retention beyond that. Confirm and adjust BoM accordingly.
6. **Geographic hierarchy depth.** Brief mentions Area, City, Region. Assumed strict 3-level hierarchy. Confirm there is no "sub-area" or "district" intermediate level that would change the RBAC model.
7. **Data sovereignty.** EU deployment is assumed (course context — UnivAQ). All PII (manager accounts) stays in EU regions. Sensor data is not personal but is treated as critical-infrastructure data — same constraint.
8. **Time synchronization.** Sensors must NTP-sync for ordering; severity of clock skew on alert correctness to be quantified.

---

## 8. Exit Criteria for Phase 0

Phase 0 is complete when:
- [x] Every line of the brief maps to at least one FR or NFR ID.
- [x] Every NFR has a six-part QAS with a numeric response measure.
- [x] Transmission frequency and burst envelope are decided with explicit math (D-01).
- [x] PoC scale and scope boundary are fixed (D-02, D-03).
- [x] All three use cases trace to FRs and NFRs.
- [x] Open questions are enumerated rather than silently assumed.

Next: **Phase 1 — Architectural design (C4 + ADRs + tactic mapping).**
