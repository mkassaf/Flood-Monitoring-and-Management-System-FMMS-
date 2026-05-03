# CLAUDE.md — Working with this repository

This file is the standing brief for any Claude Code session in this repository.
Read it first. If anything you're about to do contradicts it, stop and ask.

---

## What this is

FMMS — Flood Monitoring and Management System. Event-driven microservices that ingest
telemetry from up to 150,000 environmental sensors, evaluate flood-risk thresholds,
and deliver real-time alerts to area / city / regional managers.

This repository is the PoC. Production-scale design is documented; the PoC is the
runnable proof.

**Required reading before doing anything substantial:**
- `architecture.md` — the SAD. Containers, flows, NFR-tactics map.
- `STACK.md` — pinned versions and why.
- `docs/adr/` — every consequential decision and the alternatives that were rejected.
- The `README.md` of the service you're working in.

If a task touches an architectural concern not covered by an existing ADR, stop and
write a new ADR before writing code.

---

## Repository layout

```
.
├── README.md                # human entry point
├── CLAUDE.md                # this file
├── STACK.md                 # pinned tech versions
├── architecture.md          # Phase 1 SAD
├── workspace.dsl            # C4 architecture-as-code
├── Makefile                 # common commands — prefer these over ad-hoc invocations
├── docker-compose.yml       # PoC stack with profiles: infra, app
├── .env.example             # copy to .env and fill before running
├── contracts/               # cross-service wire contracts (JSON Schema, OpenAPI)
├── infra/                   # config for infra components (Mosquitto, Postgres init, Prometheus)
├── services/                # one folder per microservice
│   ├── README.md            # service index + how to add a new one
│   ├── sensor-simulator/    # generates synthetic MQTT traffic for the PoC
│   ├── ingestion-gateway/   # MQTT → Kafka bridge
│   ├── telemetry-service/   # Kafka → TimescaleDB writer + Redis hot state
│   ├── rule-engine/         # threshold + redundancy stream processor (Faust)
│   ├── alert-service/       # alert dedup, prioritization, persistence
│   ├── geo-service/         # areas, sensors, threshold config
│   ├── auth-service/        # JWT issuance, RBAC scopes
│   ├── dashboard-bff/       # REST + WebSocket for the frontend
│   └── frontend/            # React SPA
└── docs/
    └── adr/                 # architectural decision records (MADR format)
```

Each service is self-contained: its own `pyproject.toml` (or `package.json` for the
frontend), `Dockerfile`, `src/`, `tests/`, and `README.md`. **Services never import
each other's code.** They communicate via the contracts in `/contracts` (events on
Kafka) or via REST APIs documented in their own `README.md`.

---

## Conventions

### Languages and runtimes

- **Python services:** Python 3.12, async-first. See `STACK.md` for exact versions.
- **Frontend:** React 18 + TypeScript + Vite + Leaflet.
- **No new languages without an ADR.** Adding Go or Rust to the stack is an
  architectural decision, not a service-level choice.

### Python style

- **Format:** `ruff format` (Black-compatible). Line length 100.
- **Lint:** `ruff check`. Treat warnings as errors in CI.
- **Type check:** `mypy --strict` per service. Public APIs are fully typed.
- **Async:** prefer `async def` for any I/O. Sync code is acceptable for pure CPU work.
- **HTTP:** FastAPI for REST APIs. `httpx.AsyncClient` for outbound calls.
- **Kafka:** `aiokafka` for both producers and consumers.
- **Postgres:** `asyncpg` for raw queries; SQLAlchemy 2.x async only when ORM features
  earn their cost.
- **Redis:** `redis-py` async API.
- **Validation:** Pydantic v2 for request/response bodies and event envelopes.
- **Errors:** raise typed exceptions; let FastAPI map them via exception handlers.
  Never `except Exception:` without re-raising or logging at error level.
- **Logging:** structured JSON via `structlog`. Always include `correlation_id`
  if present in the incoming request or Kafka header.

### Configuration

- **All config via environment variables.** No config files committed with secrets.
- Use `pydantic-settings` to declare required env vars per service. Services fail
  fast on missing config.
- The root `.env.example` lists every variable any service might read. Each service
  README lists the subset it uses.

### Testing

- **Unit tests** in `tests/unit/`. Pure functions and adapters with mocks.
- **Integration tests** in `tests/integration/`. Spin up real infra via testcontainers
  or by depending on `docker compose --profile infra up` running locally.
- **No tests against external services.** All third-party dependencies are mocked or
  containerized.
- Aim for ≥80% line coverage on domain logic. Don't chase coverage on glue code.
- One test file per source file. Test names: `test_<behavior>_<condition>_<expectation>`.

### Commits and branching

- Conventional Commits format: `feat(rule-engine): add redundancy escalation`.
- One service per commit when possible. Cross-service changes go in a single commit
  with a body that explains the contract change.
- Feature branches off `main`. PRs require green CI.

---

## How services communicate

Three channels, in order of preference:

1. **Asynchronous events on Kafka** — the default for the data plane.
   Topic schemas live in `/contracts`. Producers and consumers reference them by
   schema ID via the schema registry.
2. **Synchronous REST** — for the control plane (configuration, queries, auth).
   Each service exposes an OpenAPI 3.1 spec at `/openapi.json`. Generated clients
   live in `services/<caller>/src/clients/<callee>_client.py`.
3. **WebSocket** — only between dashboard-bff and frontend. Documented in
   `services/dashboard-bff/README.md`.

Services never bypass these. No shared database. No direct Redis access from
frontend. No service reading another's tables in `opdb`.

---

## Common commands

All work via `make`. If you find yourself typing a long `docker compose` or `pytest`
incantation, check whether it should become a Makefile target.

```
make help           # list all targets
make up             # bring up infra (broker, DBs, observability)
make up-all         # bring up infra + application services
make down           # tear everything down (preserves volumes)
make clean          # tear down and remove volumes (destructive)
make logs           # tail logs from all services
make psql           # exec into the Postgres container
make redis-cli      # exec into the Redis container
make test           # run all tests across all services
make test-svc SVC=rule-engine  # run tests for one service
make lint           # run ruff + mypy across all Python services
make fmt            # apply ruff format
make load-test      # run the locust scenario against running stack
make energy-report  # generate CodeCarbon report from instrumented run
```

---

## Adding a new service

1. Write or update an ADR if this changes architectural shape.
2. Create `services/<new-service>/` with: `README.md`, `pyproject.toml`, `Dockerfile`,
   `src/<new_service>/__init__.py`, `tests/`.
3. Use an existing service as a template (`services/geo-service` is the simplest
   FastAPI-only example).
4. Add the service to `docker-compose.yml` under the `app` profile.
5. Add a section to the root `README.md` if the service is user-visible.
6. Add scrape config to `infra/prometheus/prometheus.yml`.
7. Document its events in `/contracts` if it produces or consumes any.

---

## Adding an ADR

1. Copy `docs/adr/0001-architectural-style.md` as the template.
2. Number it sequentially (`0011-…`).
3. Status starts as `Proposed`. Move to `Accepted` once merged.
4. Update the ADR index in `architecture.md` §10.
5. If this ADR supersedes a previous one, mark the old one `Superseded by ADR-XXXX`.

---

## Things to never do without explicit approval

- **Add a new dependency** to any service without updating `STACK.md` and explaining
  why. Dependency creep is a maintainability tax.
- **Change a contract schema** in `/contracts` in a backward-incompatible way.
  Backward-incompatible changes need a new schema version and a dual-write window.
- **Block the alert path on a slow downstream call.** Anything in the
  ingestion → rule-engine → alert-service path must remain async and bounded.
- **Use synchronous `requests` or `psycopg2`.** Async-only across Python services.
- **Commit secrets.** `.env` is gitignored; `.env.example` has placeholders only.
- **Add a sync API call from frontend that fans out across many areas.** Use the
  WebSocket delta channel instead — that's why it exists.
- **Write to another service's database.** Each store has exactly one writer.
- **Skip writing the test.** Especially for rule-engine logic — the redundancy
  state machine (FR-08) is the most fragile part of the system.

---

## Energy efficiency reminders (NFR-07 — project-defining)

NFR-07 is a thesis-relevant driver, not boilerplate. Apply these reflexively:

- **Batch writes.** Telemetry-service inserts in 1-second windows, not per-row.
- **Cache aggressively but with TTLs.** Redis is the hot path; don't hit Postgres
  for things that change at most once a minute.
- **Drop redundant work at the edge.** Sensor-simulator suppresses retransmission
  of identical readings within a configurable delta. Edge filtering is cheaper
  than central filtering.
- **Adaptive frequency.** The simulator changes its emission rate based on the
  *measurement value*, not on a wall clock — this models the real FR-10 behavior.
- **Right-size loops.** A 10 ms poll loop for a metric that changes every minute
  is 6,000× wasteful. Use blocking subscriptions or sane intervals.
- **Instrument.** Every Python service runs CodeCarbon. Energy is a first-class
  metric in Grafana, not an afterthought.

---

## When in doubt

- **Architecture question?** Read the relevant ADR. If it doesn't exist, write one.
- **Contract question?** Read `/contracts/README.md`.
- **"Should this be a service or a library?"** If two services would need it,
  it's a contract or a small shared package. If one service needs it, it's
  internal. Don't create cross-service runtime libraries.
- **"Should this be sync or async?"** I/O → async. Pure CPU → sync, in a
  thread pool if it blocks more than ~10 ms.
- **"Should I add a test?"** Yes.
