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
```

Once everything is healthy:

| URL | What |
|---|---|
| http://localhost:3000 | Frontend (React SPA) |
| http://localhost:8080 | Dashboard BFF (REST + WebSocket) |
| http://localhost:9090 | Prometheus |
| http://localhost:3001 | Grafana (admin / `${GRAFANA_PASSWORD}`) |
| http://localhost:1883 | Mosquitto MQTT (TCP) |
| http://localhost:9092 | Redpanda (Kafka API) |
| http://localhost:5432 | Postgres + TimescaleDB |
| http://localhost:6379 | Redis |

To watch the system handle a Phase 0 use case end-to-end:

```bash
make demo-case-1     # threshold breach → area + city manager alerted
make demo-case-2     # multi-region storm
make demo-case-3     # malfunction with backup + escalation
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
| `docker-compose.yml` | PoC orchestration. |
| `Makefile` | Common commands. |

---

## Documentation index

- **Architecture:** `architecture.md`, `workspace.dsl`, `docs/adr/`.
- **Requirements:** `phase0-requirements-and-scoping.md` (Phase 0 deliverable).
- **Per-service docs:** `services/<service>/README.md`.
- **Contracts:** `contracts/README.md`.

---

## Contributing

See `CLAUDE.md` for conventions. TL;DR:

- Async-first Python; one bounded context per service; no shared databases.
- Format with `ruff format`; lint with `ruff check`; type-check with `mypy --strict`.
- ADR for any architectural change.
- Conventional Commits.
