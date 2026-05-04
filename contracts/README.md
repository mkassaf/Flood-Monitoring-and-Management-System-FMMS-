# /contracts

Cross-service wire contracts. **Single source of truth** for everything that
crosses a service boundary.

## Files

| File | What |
|---|---|
| `telemetry-envelope.schema.json` | Sensor-to-system telemetry. MQTT payload format and Kafka `telemetry.{shard}` topic schema. |
| `alert.schema.json` | Rule-engine output. Schema for all three alert topics. |

REST contracts (OpenAPI) live with their respective services and are auto-generated
from FastAPI. Each service exposes its OpenAPI spec at `/openapi.json` and frontend
clients are generated from it at build time.

## Evolution rules

These rules exist because broker consumers cannot be redeployed atomically with
producers, and the rule engine in particular maintains state across schema changes.

### Backward-compatible changes (safe)

Allowed in a minor version bump (e.g. `1.0.0` → `1.1.0`):

- Adding an **optional** field with a default.
- Adding a new enum value to an `enum` field that consumers treat with a default
  fallback. Consumers must implement that fallback **before** the new value is
  produced — this is a coordinated change.
- Loosening a numeric range (raising a maximum, lowering a minimum).
- Adding documentation.

### Breaking changes (require a new topic)

Forbidden in-place; require a major version bump and a parallel topic for the
duration of the dual-write window:

- Removing or renaming any field.
- Tightening a constraint (narrowing an enum, tightening a range).
- Changing a type.
- Changing the partitioning semantics.

### Process for a breaking change

1. Open an ADR proposing the new schema.
2. Publish the new schema as `<name>/2.0.0` alongside `1.0.0`.
3. Producers dual-write to both `topic.v1` and `topic.v2` for a window long
   enough to drain consumer lag (≥7 days for high-volume topics, matching the
   Kafka retention).
4. Migrate consumers off `topic.v1` one at a time.
5. Stop dual-writing. Delete `topic.v1` after the retention window.
6. Mark the v1 schema as deprecated; remove from the repo after 30 days.

## Generating Pydantic models

Each Python service that consumes a contract generates Pydantic models from these
schemas as a build step:

```bash
datamodel-codegen \
  --input contracts/telemetry-envelope.schema.json \
  --output services/<svc>/src/<svc>/models/telemetry.py \
  --use-schema-description \
  --target-python-version 3.12
```

The generated file is committed (so reading the code does not require running the
generator) but is regenerated on every change to the schema. CI fails if the
committed file is stale.

## Generating frontend types

Frontend types are generated from each service's OpenAPI spec, not directly from
JSON Schema:

```bash
openapi-typescript \
  http://localhost:8080/openapi.json \
  -o services/frontend/src/types/api.ts
```

## Schema registry (production)

In production the contracts are also published to a schema registry (Apicurio or
Confluent OSS), and Kafka producers/consumers reference schemas by ID rather than
embedding them. This is out of PoC scope but the schemas in this folder are the
exact source that would be uploaded.
