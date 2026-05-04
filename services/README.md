# /services

One folder per microservice. Each is independently deployable, has its own
dependencies, its own tests, and its own `README.md`.

## Service index

| Service | Language | Type | Owns |
|---|---|---|---|
| [sensor-simulator](sensor-simulator/) | Python | sim | Synthetic MQTT traffic for the PoC |
| [ingestion-gateway](ingestion-gateway/) | Python | data plane | MQTT → Kafka bridge; sensor identity check |
| [telemetry-service](telemetry-service/) | Python | data plane | Kafka → TimescaleDB writer; Redis hot state |
| [rule-engine](rule-engine/) | Python (Faust) | data plane | Threshold + redundancy logic; alert production |
| [alert-service](alert-service/) | Python | data plane | Alert dedup, prioritization, persistence, fan-out |
| [geo-service](geo-service/) | Python | control plane | Areas, sensors, threshold configuration |
| [auth-service](auth-service/) | Python | control plane | JWT issuance, RBAC scope assertion |
| [dashboard-bff](dashboard-bff/) | Python | edge | REST + WebSocket for the frontend |
| [frontend](frontend/) | TypeScript / React | UI | The map-based dashboard |

## Standard service layout (Python)

```
services/<name>/
├── README.md            # what this service does, contracts, how to run
├── pyproject.toml       # uv-managed; dev deps in [tool.uv]
├── Dockerfile
├── .dockerignore
├── src/
│   └── <name_underscored>/
│       ├── __init__.py
│       ├── __main__.py        # entry point
│       ├── config.py          # pydantic-settings
│       ├── domain/            # pure domain logic; no I/O
│       ├── adapters/          # I/O adapters (kafka, postgres, redis, http)
│       ├── api/               # FastAPI routers (if HTTP-exposed)
│       ├── consumers/         # Kafka consumer wiring (if applicable)
│       └── models/            # generated pydantic models from /contracts
└── tests/
    ├── unit/
    └── integration/
```

## Adding a new service

See `CLAUDE.md` § "Adding a new service".

## Cross-service rules

- **No code imports across services.** If two services need the same logic,
  it's either a contract (event schema) or a small library that gets vendored
  into both — never a runtime cross-import.
- **No shared databases.** Each store has exactly one writer service. Other
  services read via the owning service's REST API or via Kafka events.
- **No synchronous calls on the alert path.** Ingestion → rule-engine →
  alert-service must remain async, bounded, and never block on a control-plane
  service.
