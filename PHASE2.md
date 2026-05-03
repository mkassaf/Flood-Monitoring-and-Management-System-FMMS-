# FMMS — Phase 2: Technology Stack & Project Skeleton

**Project:** Flood Monitoring and Management System (FMMS)
**Course:** Software Architectures 2024–2025 — Prof. Henry Muccini, UnivAQ
**Document purpose:** Record the technology choices made in Phase 2 (versions
pinned in `STACK.md`), describe the resulting repository structure, and define
the handoff to Phase 3 implementation sprints.

---

## 1. What Phase 2 produced

A complete, immediately usable monorepo skeleton:

```
fmms/
├── README.md, CLAUDE.md, STACK.md, architecture.md
├── workspace.dsl                  # C4 as code (from Phase 1)
├── docker-compose.yml             # full PoC stack with profiles
├── Makefile                       # all common dev commands
├── .env.example, .gitignore, .pre-commit-config.yaml
├── contracts/                     # JSON Schema for telemetry + alert events
├── infra/                         # Mosquitto, Postgres init, Prometheus configs
├── docs/adr/                      # 10 ADRs from Phase 1 + TEMPLATE.md
└── services/                      # 9 services, each with:
    ├── README.md
    ├── pyproject.toml | package.json
    ├── Dockerfile
    ├── src/<module>/
    │   ├── __init__.py
    │   ├── __main__.py            # entry point with /healthz, /metrics
    │   ├── api.py
    │   └── config.py              # pydantic-settings
    └── tests/{unit,integration}/
```

Key property: **`docker compose --profile infra --profile app up -d --build`
will succeed today** against this skeleton — every service builds, starts,
exposes `/healthz`, and registers with Prometheus. The Phase 3 sprints replace
placeholder `__main__.py` worker loops with real consumers and routers, but
the orchestration glue is already correct.

---

## 2. Stack choices and what backs them

The detailed list with versions is in `STACK.md`. The choices that needed
judgment beyond Phase 1's ADRs:

### 2.1 Python 3.12, async-first
Python 3.12 has a stable asyncio surface (TaskGroup, ExceptionGroup) and good
Pydantic v2 support. 3.13 was rejected because several deps in our stack
(`faust-streaming`, `aiokafka`) lag on major Python releases. Async is
mandatory across services because every data-plane service is I/O-bound — a
sync `psycopg2` or `requests` call on the alert path is a regression risk
called out in `CLAUDE.md`.

### 2.2 Redpanda for the PoC backbone
ADR-003 already explained why. The Phase 2 commitment: **the implementation
uses only the Kafka client API** (`aiokafka`, no Redpanda admin tooling),
preserving the production migration path to Apache Kafka.

### 2.3 Single Postgres instance for `opdb` + `tsdb` in the PoC
The Phase 1 architecture cleanly separates the operational store from the
telemetry store. In the PoC they live as **two schemas in one Postgres
instance** to keep the Compose stack small. The `init.sql` file makes the
schemas explicit so the production split is mechanical:

```
poc:    postgres → schemas: opdb, tsdb
prod:   postgres-op (managed RDBMS) + timescale-cloud (separate)
```

### 2.4 uv-managed Python deps
Each service has a `pyproject.toml` with `~=` (compatible-release) pinning. A
lock file (`uv.lock` or `poetry.lock`) is committed and is the actual source
of truth for installed versions. Renovate / Dependabot is a Phase 4 task.

### 2.5 Single-file artifact generation strategy
Every Python service has the same shape (`src/<mod>/{__init__,__main__,api,config}.py`
+ `tests/{unit,integration}/`). This uniformity matters for Claude Code: each
sprint can apply patterns learned in one service to the next without
re-discovering the layout.

---

## 3. The contracts directory

`contracts/` is the **single source of truth for everything that crosses a
service boundary**. Two files:

- `telemetry-envelope.schema.json` — the MQTT/Kafka payload format.
- `alert.schema.json` — the alert envelope shared by all three alert topics.

REST contracts (OpenAPI) are auto-generated from FastAPI per service. Frontend
TypeScript types are generated from each service's OpenAPI spec.

`contracts/README.md` documents the **schema evolution rules** in detail: which
changes are safe in-place (additive, with defaults), and which require a new
schema version + dual-write window. This is the document to reach for when a
breaking change is contemplated in any future phase.

---

## 4. CLAUDE.md — the most consequential file

Implementation quality across every future sprint depends on this file. It
encodes:

- **Required reading** — `architecture.md`, `STACK.md`, `docs/adr/`,
  per-service `README.md`. Listed in the order Claude Code should read them.
- **Conventions** — async-first, ruff + mypy strict, structured logging,
  pydantic-settings for config, no shared databases.
- **Communication rules** — Kafka events (default), REST (control plane),
  WebSocket (frontend only). No services importing each other's code.
- **Common commands** — every multi-step operation lives in the Makefile.
- **Things to never do without approval** — adding deps, breaking contracts,
  blocking the alert path, sync I/O, committing secrets.
- **Energy-efficiency reminders** for NFR-07 — batching, caching, edge
  filtering, adaptive frequency, right-sized loops, instrumentation. These
  are listed because energy efficiency is the thesis-relevant driver and
  applying it consistently across services is what makes Phase 5's
  measurements credible.

If any future Claude Code session ever produces code that contradicts
`CLAUDE.md`, the file is wrong, the code is wrong, or both — and the conflict
must be resolved before merging.

---

## 5. Per-service READMEs

Every service has a `README.md` that documents:

- Bounded context (what this service owns; what it must not touch).
- Behavior (the ordered steps it performs).
- Inputs (REST + Kafka + cache reads).
- Outputs (writes + metrics).
- Configuration (env vars).
- Run-locally command.
- Test scope (unit + integration responsibilities).
- **Critical paths** (regression risks specific to that service).

The "critical paths" sections are the most valuable part. Examples:

- `ingestion-gateway`: token verification compares against argon2id hashes
  — plaintext comparison would be a security regression.
- `telemetry-service`: COPY is the only acceptable insertion mode at the load
  envelope; per-row INSERT will not meet QAS-03 throughput.
- `rule-engine`: pure-function domain logic is the portability surface to
  Flink (ADR-005); do not let it grow I/O.
- `alert-service`: the priority topic uses a separate consumer group so
  bulk-topic backlog cannot delay priority-1 alerts.
- `dashboard-bff`: a forgotten `WHERE area_id IN scope` is a security
  incident.

---

## 6. Things worth flagging before Phase 3

These are choices made in Phase 2 where reasonable people might disagree;
flag them explicitly so they don't become silent assumptions.

### 6.1 PoC simplifications that defer real complexity

The following are **explicitly simpler in the PoC** than in production:

- One Postgres instance hosting both schemas (vs. two managed services).
- Mosquitto with `allow_anonymous true` (vs. mTLS + per-area cert ACLs).
  The per-sensor token check in the ingestion-gateway is still real.
- Single Redpanda broker (vs. 3-broker Kafka cluster with RF=3, min ISR=2).
- JWT keys read from filesystem paths (vs. mounted as Docker / K8s secrets
  from a real secret store).
- Frontend served by Vite preview (vs. a CDN-fronted static deployment).

Each of these is a reversible PoC choice. The architecture documents the
production version; the Compose stack runs the PoC version. If your supervisor
expects production-grade infrastructure in the demo, raise these now — they
double the Phase 2/3 effort.

### 6.2 Faust vs. Flink

ADR-005 picked `faust-streaming` for the PoC. Phase 2 confirms this choice by
pinning `faust-streaming ~= 0.11`. If during Phase 3 the load test shows Faust
cannot meet QAS-04 burst latency on the PoC machine, the evacuation path is to
Flink — but the rule-engine code is structured (pure functions for
`evaluate_thresholds` and `update_redundancy`) so the migration is tractable.

### 6.3 No schema registry in the PoC

`/contracts` is the source of truth; Pydantic models are generated from it at
build time. A real schema registry (Apicurio / Confluent) is documented in
`contracts/README.md` but not deployed. This is fine at PoC scale (one team,
one repo, atomic schema changes) but would be inadequate in a real deployment
with independent producer/consumer release cycles.

### 6.4 Energy measurement is via CodeCarbon, not Scaphandre

CodeCarbon is cross-platform (Linux, macOS — relevant if the team runs the
PoC on M-series Apple hardware) but is an *estimate*. Scaphandre gives true
RAPL-based readings on Linux. The Phase 5 energy report should document this
and, where possible, cross-validate CodeCarbon estimates against Scaphandre on
a Linux host. This concern is the same one you raised about the master's
student paper — it carries directly into FMMS validation.

### 6.5 Component-level diagrams are still textual

`architecture.md` §4 documents the component-level decomposition for the three
highest-risk containers in prose. We deliberately did not commit Structurizr
`component` views in Phase 1 or Phase 2 because they churn during
implementation. **Phase 4** (after the first vertical slice is complete) is
when those views become worth the maintenance cost.

---

## 7. Demo data and seed flows

The Make targets `demo-case-1`, `demo-case-2`, `demo-case-3` are wired into
the sensor-simulator (`python -m sensor_simulator.demos <case>`). Phase 3's
first sprint implements these so that there is always a one-command path to
reproducing the Phase 0 use cases. This is non-negotiable for the final
project demo.

---

## 8. Exit criteria for Phase 2

- [x] Every Phase 1 ADR is committed under `docs/adr/`.
- [x] `STACK.md` pins versions for every dependency.
- [x] `docker-compose.yml` brings up the full PoC stack.
- [x] `Makefile` exposes the standard developer commands.
- [x] `.env.example` lists every env var any service might read.
- [x] Every service has a `README.md`, a `pyproject.toml` (or `package.json`),
      a `Dockerfile`, and a runnable scaffold that exposes `/healthz` and
      `/metrics`.
- [x] `CLAUDE.md` is in place and complete.
- [x] `contracts/` holds the cross-service wire formats with documented
      evolution rules.

---

## 9. Handoff to Phase 3

Phase 3 is **6 implementation sprints of ~1 week each**, as laid out in the
original plan:

| Sprint | Vertical slice |
|---|---|
| S1 | Sensor sim → MQTT → Kafka end-to-end with one synthetic message type |
| S2 | TimescaleDB writer + simple threshold rule engine + alert producer |
| S3 | Auth + geo-service + RBAC + Case 3 redundancy escalation |
| S4 | Dashboard BFF + frontend with map and real-time WebSocket |
| S5 | Wire all three Phase 0 use cases as `make demo-case-*`; load test |
| S6 | Energy report; cost BoM; final SAD updates |

**For each sprint, the Claude Code workflow is:**

1. Open the sprint goal in the chat.
2. Claude Code reads `CLAUDE.md`, then the relevant service `README.md`(s),
   then the related ADR(s).
3. Claude Code proposes the change, identifies any contract change, and writes
   the code + tests in the same change.
4. `make lint && make test-svc SVC=<svc>` must pass before the change is
   merged.
5. Architectural changes (adding a service, breaking a contract, adding a
   runtime dependency) require a new ADR before code lands.

The skeleton is now complete. Phase 3, Sprint 1 can begin immediately on a
fresh Claude Code session in this repository.
