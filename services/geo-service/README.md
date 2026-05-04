# geo-service

The system-of-record for the geographic hierarchy and threshold configuration.
A small, low-traffic, transactional service.

## Bounded context

Owns the `opdb.region`, `opdb.city`, `opdb.area`, `opdb.sensor`, and
`opdb.threshold` tables. All other services read this data via the geo-service
REST API.

## Responsibilities

1. CRUD for regions, cities, areas, sensors (FR-18).
2. CRUD for per-area thresholds (FR-17).
3. Resolve a geographic scope: given a city or region, return the flat list of
   `area_id`s it contains. (Used by auth-service at token issuance — ADR-007.)
4. Sensor identity: register a sensor with its area binding and an
   argon2id-hashed token (ADR-006). Plaintext tokens are returned **only at
   creation time** in the API response and never stored.
5. Sensor lifecycle: register, decommission (soft-delete via
   `decommissioned_at`), reassign to a different area.

## REST API (selected)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/regions` | Create a region |
| `GET`  | `/regions/{id}` | Get a region with nested cities |
| `POST` | `/cities` | Create a city under a region |
| `POST` | `/areas` | Create an area under a city |
| `GET`  | `/areas/{id}` | Get an area with sensor count + thresholds |
| `POST` | `/sensors` | Register a sensor; returns the plaintext token **once** |
| `POST` | `/sensors/{id}/decommission` | Soft-delete |
| `GET`  | `/areas/{id}/thresholds` | List thresholds for an area |
| `PUT`  | `/areas/{id}/thresholds/{parameter}` | Set a threshold |
| `POST` | `/scopes/expand` | Body: `{role, jurisdiction}` → returns flat area_id list |

Full spec at `/openapi.json` once running.

## Inputs

- REST: from auth-service (scope expansion), ingestion-gateway (sensor identity),
  rule-engine (thresholds), dashboard-bff (read).

## Outputs

- `opdb` writes for all owned tables.
- Prometheus metrics: standard FastAPI metrics + per-endpoint histograms.

## Configuration

| Var | Default | Notes |
|---|---|---|
| `POSTGRES_DSN` | required | |
| `LOG_LEVEL` | `INFO` | |

## Run locally

```bash
cd services/geo-service
uv sync
uv run uvicorn geo_service.api:app --port 8000
```

## Tests

- Unit: scope expansion logic, threshold validation, soft-delete semantics.
- Integration: full CRUD flow against testcontainers Postgres.

## Critical paths

- The plaintext token returned on `POST /sensors` is shown **once**, never
  retrievable again. Document this prominently in the API response.
- Threshold updates do not push to the rule-engine — rule-engine pulls on a
  60s cache TTL (see rule-engine README). If immediate effect is ever needed,
  add a Redis Pub/Sub `geo:thresholds:updated` channel.
