# FMMS — Flood Monitoring and Management System

PoC implementation for the *Software Architectures 2024–2025* project (UnivAQ,
Prof. Henry Muccini).

Event-driven microservices that ingest telemetry from up to 150,000 environmental
sensors, evaluate flood-risk thresholds, and deliver real-time alerts to area, city,
and regional managers.

---

## Quickstart

Prerequisites: Docker 27+, Docker Compose v2.30+, GNU Make, Python 3.12 (only if you
want to run services outside containers).

```bash
git clone <this-repo>
cd fmms
cp .env.example .env             # fill in secrets / passwords for local dev
make up                          # bring up infra (broker, DBs, Prometheus, Grafana)
make up-all                      # bring up infra + application services
python scripts/seed.py           # seed regions, areas, sensors, and demo users
```

Once everything is healthy:

| URL | What |
|---|---|
| http://localhost:3000 | Frontend (React SPA) |
| http://localhost:8080 | Dashboard BFF (REST + WebSocket) |
| http://localhost:8006 | Auth service |
| http://localhost:9090 | Prometheus |
| http://localhost:3001 | Grafana (`admin` / `admin`) |
| http://localhost:1883 | Mosquitto MQTT (TCP) |
| http://localhost:9092 | Redpanda (Kafka API) |
| http://localhost:5432 | Postgres + TimescaleDB |
| http://localhost:6379 | Redis |

### Demo credentials

| Email | Password | Role |
|---|---|---|
| `area_manager@fmms.local` | `Test1234!` | Area Manager |
| `city_manager@fmms.local` | `Test1234!` | City Manager |
| `regional_manager@fmms.local` | `Test1234!` | Regional Manager |

### Demo scenarios

Run these to trigger alerts end-to-end through the full pipeline:

```bash
# Case 1 — water level rises past flood threshold (3 m)
docker exec fmms-sensor-simulator-1 python -m sensor_simulator.demos case_1

# Case 2 — storm: rainfall bursts across multiple areas simultaneously
docker exec fmms-sensor-simulator-1 python -m sensor_simulator.demos case_2

# Case 3 — redundancy loss: both sensors in an area go offline
docker exec fmms-sensor-simulator-1 python -m sensor_simulator.demos case_3
```

To run the load test that validates QAS-03 / QAS-04:

```bash
make load-test
```

---

## Repository map

| Path | What lives here |
|---|---|
| `architecture.md` | Phase 1 SAD. Read this first. |
| `STACK.md` | Pinned versions and rationale. |
| `CLAUDE.md` | Standing brief for Claude Code sessions. |
| `workspace.dsl` | C4 architecture-as-code (Structurizr). |
| `docs/adr/` | Architectural Decision Records. |
| `contracts/` | Cross-service wire contracts (JSON Schema, OpenAPI). |
| `services/` | One folder per microservice. |
| `infra/` | Config for infrastructure components. |
| `scripts/` | Seed data and operational scripts. |
| `secrets/` | JWT key pair (gitignored; generate with `openssl`). |
| `docker-compose.yml` | PoC orchestration. |
| `Makefile` | Common commands. |

---

## Architecture overview

FMMS is structured as a pipeline of independent services communicating over three channels:

```
Sensors (MQTT)
    │
    ▼
ingestion-gateway ──► Kafka (telemetry topic)
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
    telemetry-service    rule-engine      (future ML)
    (TimescaleDB +       (thresholds +
     Redis hot state)     redundancy)
                              │
                              ▼
                        alert-service ──► Redis Pub/Sub
                        (Postgres)              │
                                               ▼
                                        dashboard-bff
                                        (REST + WS)
                                               │
                                               ▼
                                          frontend (SPA)
```

**Services:**

| Service | Port | Responsibility |
|---|---|---|
| `sensor-simulator` | 8001 | Generates synthetic MQTT traffic; includes 3 demo scenarios |
| `ingestion-gateway` | 8002 | MQTT → Kafka bridge; validates sensor identity |
| `telemetry-service` | 8000 | Kafka → TimescaleDB writer; updates Redis hot state |
| `rule-engine` | 8003 | Threshold evaluation + redundancy state machine; emits alerts |
| `alert-service` | 8004 | Alert dedup, persistence, Redis Pub/Sub fan-out |
| `geo-service` | 8005 | Geographic hierarchy (regions/cities/areas) + threshold config |
| `auth-service` | 8006 | JWT issuance (RS256), user management, RBAC |
| `dashboard-bff` | 8080 | REST + WebSocket backend-for-frontend |
| `frontend` | 3000 | React SPA with live alert feed and map view |

---

## Technology decisions

All decisions are recorded as ADRs in [`docs/adr/`](docs/adr/). Summary:

### ADR-001 — Event-driven microservices
Chosen because the workload has three fundamentally different shapes (ingestion throughput, stateful stream processing, connection-bound UI) that can't be efficiently co-located. The data plane is a stream that multiple consumers must read independently without coordinating.

### ADR-002 — MQTT 5 over TLS for sensor communication
MQTT's publish/subscribe model suits 150K long-lived connections with minimal per-message overhead. Last Will and Testament provides automatic offline detection. Chosen over HTTP (too chatty for sensors) and CoAP (weaker ecosystem).

### ADR-003 — Apache Kafka (Redpanda for PoC)
The telemetry stream needs durable buffering, replay capability, and multi-consumer fan-out without coupling producers to consumers. Redpanda is Kafka-API compatible but runs as a single binary — suitable for Docker Compose without a Zookeeper dependency.

### ADR-004 — TimescaleDB for telemetry storage
Time-series data with a 90-day hot window. TimescaleDB's hypertable partitioning, continuous aggregates, and native compression outperform plain Postgres for range queries. Writes are batched (1-second windows, bulk `UNNEST` inserts) to hit the NFR-07 energy target.

### ADR-005 — Plain aiokafka consumer for rule-engine (PoC)
The original plan was Faust (Python stream processing). For the PoC, a plain `aiokafka` consumer loop avoids Faust's RocksDB state backend and external coordinator dependency, while still correctly implementing threshold evaluation and the FR-08 redundancy state machine.

### ADR-006 — Two-layer sensor identity (per-area X.509 + per-sensor token)
One X.509 cert per area (150 CAs instead of 150K), plus a lightweight per-sensor MQTT username/token. Balances strong authentication against the operational cost of certificate lifecycle at scale.

### ADR-007 — JWT with RS256 and scope claims
JWTs carry `role` and `jurisdiction` so the dashboard-bff can enforce authorization on every request without an extra DB hit. RS256 allows any service to verify tokens offline using only the public key. Refresh tokens are stored server-side for revocation.

### ADR-008 — Docker Compose (PoC) / Kubernetes (production)
PoC runs on a developer laptop with a single `docker compose up`. Production targets Kubernetes with HPA per service, driven by Kafka consumer-lag and WebSocket connection count, enabling idle-aware scale-down (NFR-07).

### ADR-009 — WebSocket for real-time UI push
Alert path latency target is ≤2 s P95. Redis Pub/Sub fans alerts to `dashboard-bff`, which maintains one WebSocket per active manager session. Per-user channel subscriptions filter by jurisdiction scope, avoiding cross-tenant leakage.

### ADR-010 — Partition Kafka topics by `area_id`
The rule engine's redundancy state machine (FR-08) requires per-area ordering. Partitioning by `area_id` hash guarantees all events for one area go to the same partition and consumer instance. 16 partitions × 16 shards → 256-way parallelism upper bound.

---

## Framework and library choices

### Backend (Python 3.12, async-first)

| Library | Version | Why |
|---|---|---|
| FastAPI | `~0.115` | Async-native, Pydantic v2 integration, automatic OpenAPI |
| Pydantic v2 | `~2.9` | Schema validation, settings management; v2 is 5–50× faster than v1 |
| pydantic-settings | `~2.6` | Env-var config with type checking and fail-fast on missing vars |
| aiokafka | `~0.12` | Pure-asyncio Kafka producer/consumer; no threading overhead |
| asyncpg | `~0.30` | Fastest async Postgres driver; binary protocol |
| redis-py (async) | `~5.2` | Async Redis client; Pub/Sub for alert fan-out |
| paho-mqtt | `~2.1` | MQTT 5 support; handles reconnect and QoS |
| python-jose | `~3.3` | JWT signing/verification (RS256) |
| httpx | `~0.27` | Async HTTP client for inter-service REST calls |
| structlog | `~24.4` | Structured JSON logging with correlation IDs |
| prometheus-client | `~0.21` | `/metrics` endpoint; energy and throughput tracking |
| codecarbon | `~2.7` | CPU/GPU energy measurement per service (NFR-07) |
| passlib + argon2-cffi | — | Password hashing (argon2id) |
| uvicorn | `~0.32` | ASGI server for all FastAPI services |

### Frontend (TypeScript)

| Library | Version | Why |
|---|---|---|
| React | `^18.3` | Component model; concurrent features |
| Vite | `^5.4` | Fast dev server; ES module native build |
| TypeScript | `^5.4` | Static typing; strict mode enabled |
| TanStack Query | `^5.59` | Server state: caching, background refetch, stale-while-revalidate |
| Zustand | `^5.0` | Lightweight client state (auth token, live alerts); persisted to localStorage |
| react-leaflet + Leaflet | `^4.2` / `^1.9` | Map view with area markers; no paid API token needed |
| Tailwind CSS | `^3.4` | Utility-first styling; fast iteration |
| Axios | — | HTTP client for BFF REST calls |

### Infrastructure (PoC)

| Component | Image | Why |
|---|---|---|
| MQTT broker | `eclipse-mosquitto:2.0` | MQTT 5; persistent sessions; ACL support |
| Kafka backbone | `redpandadata/redpanda:v24.2` | Kafka-API compatible; single binary; no Zookeeper |
| Database | `timescale/timescaledb:2.17.0-pg16` | TimescaleDB hypertables for telemetry + Postgres for operational data |
| Cache / Pub/Sub | `redis:7.4-alpine` | Hot sensor state; alert fan-out to WebSocket clients |
| Metrics | `prom/prometheus:v2.55` | Scrapes all `/metrics` endpoints |
| Dashboards | `grafana/grafana:11.3.0` | Visualizes throughput, latency, and energy consumption |

---

## Documentation index

- **Architecture:** [`architecture.md`](architecture.md), [`workspace.dsl`](workspace.dsl), [`docs/adr/`](docs/adr/)
- **Stack versions:** [`STACK.md`](STACK.md)
- **Per-service docs:** `services/<service>/README.md`
- **Contracts:** [`contracts/README.md`](contracts/README.md)

---

## Contributing

See [`CLAUDE.md`](CLAUDE.md) for conventions. TL;DR:

- Async-first Python; one bounded context per service; no shared databases.
- Format with `ruff format`; lint with `ruff check`; type-check with `mypy --strict`.
- Write an ADR before any architectural change.
- Conventional Commits: `feat(rule-engine): add redundancy escalation`.
