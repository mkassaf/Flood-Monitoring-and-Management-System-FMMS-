# ADR-008 — Deployment: Kubernetes (production) / Docker Compose (PoC)

**Status:** Accepted (Phase 1)
**Related:** ADR-001 (microservices), NFR-01, NFR-02, NFR-06, NFR-07, NFR-08

## Context

Deployment must support:

- Independent scaling per service (NFR-01) with autoscaling driven by service-specific signals (Kafka consumer lag, MQTT message rate, WebSocket connection count).
- Rolling updates per service with zero downtime on the alert path (QAS-07).
- Multi-AZ redundancy for the production environment (NFR-02).
- Idle-aware scale-down for energy efficiency (NFR-07).
- A PoC that runs on a single developer laptop without cloud dependency.

## Decision

**Production:** Kubernetes (managed: EKS / GKE / AKS — provider TBD in BoM, see NFR-08).
- All stateless services as `Deployment` with `HorizontalPodAutoscaler`.
- HPA targets:
  - `ingestion-gateway`: custom metric = MQTT messages/sec per pod.
  - `telemetry-service`, `rule-engine`: custom metric = Kafka consumer lag (target P95 <500 ms).
  - `dashboard-bff`: custom metric = active WebSocket connections per pod.
  - Other services: CPU + RPS.
- Stateful components (Kafka, Mosquitto, TimescaleDB, PostgreSQL, Redis) as **managed cloud services** in production. (Operating Kafka and TimescaleDB ourselves at this scale is out of the project's labor budget.)
- Multi-AZ: single region, ≥3 AZs. Kafka brokers, DB primaries/replicas, and stateless pods spread across AZs by topology spread constraints.
- Helm charts per service, one umbrella chart for the platform.
- GitOps via Argo CD or Flux for production deployment (out of PoC scope but documented in Phase 5).

**PoC:** Docker Compose, single host.
- Every container from the C4 view runs as one Compose service.
- Replicas = 1 across the board (the goal is functional + small-scale load test, not HA).
- Single `docker-compose.yml` with profiles for `core`, `observability`, `load-test`.
- Includes a sensor-simulator container that generates 1,000 simulated sensors at the locked frequencies.

## Considered Alternatives

### A1. Production on Docker Swarm
- **Pros:** Simpler than K8s.
- **Cons:** Smaller ecosystem; weaker autoscaling story; declining adoption — staffing and tooling risk.
- **Verdict:** rejected.

### A2. Production on Nomad
- **Pros:** Lightweight; multi-workload (containers, VMs, batch).
- **Cons:** Smaller ecosystem; less common in EU consulting market (cost / staffing risk for Phase 5 BoM).
- **Verdict:** rejected.

### A3. Self-managed Kafka and DBs in K8s (using operators: Strimzi, CloudNativePG, etc.)
- **Pros:** No cloud vendor lock-in; lower vendor cost.
- **Cons:** Operational labor cost is significant. For a project this size with student labor or a small team, managed services are net cheaper across the project lifecycle.
- **Verdict:** documented as a cost alternative in the Phase 5 BoM; default is managed services for the production estimate.

### A4. PoC on Minikube / Kind
- **Pros:** Same orchestrator as production; reduces dev/prod drift.
- **Cons:** Heavyweight on a laptop; slower iteration; more operational concepts than the PoC needs.
- **Verdict:** rejected — Compose is dramatically faster for inner-loop development; production drift is mitigated by container parity (same images, same env vars).

## Consequences

**Positive**
- HPA driven by domain-specific signals (consumer lag, WS connections) is a strong NFR-07 lever — it scales precisely with demand.
- Managed stateful services move ops burden off the team and into the cloud bill — an explicit cost-vs-labor trade documented in NFR-08.
- Helm + GitOps gives QAS-07 (zero-downtime per-service rollout) for free.
- PoC on Compose keeps the inner-loop fast and removes K8s as a learning prerequisite for contributors.

**Negative**
- Two deployment substrates (Compose vs. K8s) means some duplication in declarative config. Mitigated by keeping the *images* identical and parameterizing only orchestration concerns.
- Managed-service costs dominate the BoM at small scale where self-hosting would be cheaper. The cost model in Phase 5 will show both options.

**Risks**
- HPA on custom metrics requires Prometheus Adapter or equivalent. Add to Phase 2 stack lock.
- Idle-aware scale-down can cause cold-start latency on traffic spikes if `minReplicas` is set too low. Tune in Phase 5.
