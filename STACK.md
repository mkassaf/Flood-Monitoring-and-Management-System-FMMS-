# STACK.md — Pinned technology stack

Every choice here is the consequence of a Phase 1 ADR or an explicit Phase 2 decision.
If you change a version, update this file and explain why in the same commit.

---

## Languages and runtimes

| Component | Version | Rationale |
|---|---|---|
| Python | **3.12.x** | Modern asyncio (TaskGroup, exception groups), good Pydantic v2 support, current LTS-equivalent. Avoid 3.13 until the ecosystem catches up. |
| Node.js | **20.x LTS** | Frontend toolchain only (Vite + React). LTS until April 2026. |
| TypeScript | **5.4+** | For the frontend. |

---

## Application frameworks (Python)

| Library | Version | Used by | Why |
|---|---|---|---|
| FastAPI | `~=0.115` | All HTTP services | Async-native; Pydantic v2 integration; OpenAPI auto-generation. |
| Pydantic | `~=2.9` | All services | v2 perf is materially better; `model_config` ergonomics. |
| pydantic-settings | `~=2.6` | All services | Env-based config with type checking. |
| structlog | `~=24.4` | All services | Structured logging with JSON output. |
| aiokafka | `~=0.12` | ingestion-gateway, telemetry-service, rule-engine, alert-service | Pure-asyncio Kafka client; widely deployed. |
| paho-mqtt | `~=2.1` | sensor-simulator, ingestion-gateway | MQTT 5 support; battle-tested. |
| faust-streaming | `~=0.11` | rule-engine | Maintained community fork. See ADR-005. |
| asyncpg | `~=0.30` | All services touching Postgres | Fastest async Postgres driver. |
| redis | `~=5.2` (redis-py) | telemetry-service, rule-engine, dashboard-bff, alert-service | Async API matured in 5.x. |
| python-jose[cryptography] | `~=3.3` | auth-service, dashboard-bff | JWT signing/verification (RS256). |
| httpx | `~=0.27` | Inter-service REST | Async HTTP client. |
| websockets | `~=13` | dashboard-bff | WebSocket server (FastAPI uses it under the hood, but pin explicitly). |
| codecarbon | `~=2.7` | All Python services | Energy measurement. NFR-07. |
| prometheus-client | `~=0.21` | All Python services | `/metrics` endpoint. |
| opentelemetry-api / -sdk | `~=1.27` | All services | Distributed tracing. |

---

## Frontend

| Library | Version | Why |
|---|---|---|
| React | `^18.3` | Stable; broad ecosystem. |
| Vite | `^5.4` | Fast dev server; standard build tool. |
| react-leaflet + leaflet | `^4.2` / `^1.9` | Map UI. OSM tiles by default. No paid token needed for the PoC. |
| TanStack Query | `^5.59` | Server state for REST queries. |
| Zustand | `^5.0` | Local UI state. Lightweight; no Redux ceremony. |
| Tailwind CSS | `^3.4` | Utility-first; fast iteration. |

---

## Infrastructure (PoC, via Docker Compose)

| Component | Image / Version | Why |
|---|---|---|
| MQTT broker | `eclipse-mosquitto:2.0` | ADR-002. MQTT 5 support via config. |
| Streaming backbone | `redpandadata/redpanda:v24.2` | ADR-003. Kafka-API compatible; single binary; low PoC footprint. |
| RDBMS + TSDB | `timescale/timescaledb:2.17.0-pg16` | ADR-004 + Phase 2 simplification: one Postgres instance with both `tsdb` and `opdb` schemas for the PoC. Production splits them. |
| Cache | `redis:7.4-alpine` | ADR-009; FR-08 redundancy state. |
| Metrics | `prom/prometheus:v2.55` | NFR-10. |
| Dashboards | `grafana/grafana:11.3.0` | NFR-10. |
| Logs | `grafana/loki:3.2` | NFR-10. Optional in PoC profile. |

---

## Infrastructure (Production targets, documented in ADR-008)

| Component | Choice | Notes |
|---|---|---|
| Streaming backbone | Apache Kafka 3.7+ (managed, e.g. MSK or Confluent Cloud) | Kafka API contract preserved from Redpanda. |
| MQTT broker | Mosquitto cluster, 2+ nodes | Or HiveMQ Cloud if managed broker is preferred. |
| RDBMS | Managed PostgreSQL 16 + Timescale Cloud (separate instance for tsdb) | |
| Cache | Managed Redis 7 cluster | |
| Orchestrator | Kubernetes 1.30+ (managed) | EKS / GKE / AKS — choice deferred to Phase 5 BoM. |
| GitOps | Argo CD 2.13+ | |
| Observability | Prometheus + Grafana + Loki + Tempo (or OTel + cloud backend) | |

---

## Developer tooling

| Tool | Version | Purpose |
|---|---|---|
| Docker | 27+ | Container runtime. |
| Docker Compose | v2.30+ | PoC orchestration. |
| ruff | `~=0.7` | Format + lint Python. |
| mypy | `~=1.13` | Static type check. `--strict` per service. |
| pytest | `~=8.3` | Test runner. |
| pytest-asyncio | `~=0.24` | Async test support. |
| testcontainers | `~=4.8` | Integration tests with real infra. |
| locust | `~=2.32` | Load testing for QAS-03 / QAS-04. |
| pre-commit | `~=4.0` | Run ruff + mypy on commit. |

---

## Schema and contract tooling

| Tool | Purpose |
|---|---|
| JSON Schema (draft 2020-12) | Wire format for Kafka events. Stored in `/contracts`. |
| OpenAPI 3.1 | REST API contracts. Auto-generated from FastAPI. |
| `datamodel-code-generator` | Generate Pydantic models from JSON Schema (build step). |
| `openapi-typescript` | Generate frontend TypeScript types from each service's OpenAPI. |

---

## Version pinning policy

- All Python deps use **compatible-release** (`~=X.Y`) pinning in `pyproject.toml`.
- `uv.lock` (or `poetry.lock`) is committed and is the actual source of truth for
  installed versions.
- Major version bumps require an ADR if the dep is in the data-plane critical path
  (aiokafka, paho-mqtt, faust-streaming, asyncpg, FastAPI). Routine deps can be bumped
  without ceremony.
- Renovate or Dependabot is configured (Phase 4 task) to keep things current with
  weekly PRs.
