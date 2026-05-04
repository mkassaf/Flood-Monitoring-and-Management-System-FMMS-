# dashboard-bff

The only user-facing data-plane service. Aggregates live + historical data for
the frontend, enforces RBAC, and pushes deltas via WebSocket.

## Bounded context

The **trust boundary** between users and the platform. Validates JWTs,
translates user scope into area-id filters, and applies those filters to every
read. No other service is reachable from the frontend.

See **ADR-009** for the WebSocket protocol and **ADR-007** for the auth model.

## Behavior

### Auth
1. On every request: verify JWT signature using the public key cached from
   `auth-service /jwks.json` (refresh every hour or on `kid` mismatch).
2. Extract `scope.areas` from the token. This is the **only** authorization
   primitive the BFF works with.

### REST endpoints (read-only over telemetry / alerts)
| Method | Path | Purpose |
|---|---|---|
| `GET` | `/me` | Current user's role + jurisdiction summary |
| `GET` | `/areas` | Areas in user scope (with most recent severity) |
| `GET` | `/areas/{id}/sensors` | Sensors in an area + latest reading from Redis |
| `GET` | `/areas/{id}/telemetry?from=&to=&parameter=` | Historical from TimescaleDB |
| `GET` | `/alerts?severity=&kind=&from=&to=` | Historical alerts in scope |
| `GET` | `/alerts/active` | Unacknowledged alerts in scope, ranked by severity |
| `POST` | `/alerts/{id}/acknowledge` | Proxy to alert-service |
| `GET` | `/rollups/region/{id}` | Pre-aggregated regional view (for regional managers) |

### WebSocket: `/ws`
1. Frontend connects with the JWT in the `Authorization` header (or `?token=`
   query param for browser compat).
2. BFF subscribes to Redis Pub/Sub channels `area:{id}:updates` for every
   area in the user's scope.
3. On each Pub/Sub message: BFF re-checks scope (defense in depth) and pushes
   a delta payload to the client.
4. Heartbeat ping/pong every 30 s.
5. On reconnect, client supplies `last_seen_alert_id` and the BFF replays
   missed alerts from `opdb.alert`.

For **regional managers** at extreme scope (~50K sensors), per-event push is
unsustainable. The BFF pushes pre-aggregated region/city rollups instead and
only switches to per-sensor detail when the user drills down.

## Inputs

- REST: from frontend (with JWT).
- REST out: auth-service (JWKS), geo-service (area metadata),
  alert-service (acknowledge proxy).
- Redis: subscribe to `area:*:updates`, read sensor latest snapshots.
- Postgres: read `opdb.alert`, `tsdb.telemetry`, `tsdb.telemetry_1min`.

## Outputs

- Responses to frontend.
- Prometheus metrics:
  - `bff_requests_total{path, status}`
  - `bff_request_seconds{path}` (histogram)
  - `bff_websocket_connections` (gauge)
  - `bff_websocket_messages_pushed_total{kind}`
  - `bff_unauthorized_total{reason}`

## Configuration

| Var | Default | Notes |
|---|---|---|
| `POSTGRES_DSN` | required | |
| `REDIS_URL` | required | |
| `AUTH_SERVICE_URL` | `http://auth-service:8000` | For JWKS. |
| `GEO_SERVICE_URL` | `http://geo-service:8000` | |
| `JWT_PUBLIC_KEY_PATH` | optional | Bootstrap public key; refreshed via JWKS. |
| `WS_HEARTBEAT_INTERVAL_S` | `30` | |
| `WS_MAX_CONNECTIONS_PER_POD` | `200` | Used by HPA in production. |
| `ROLLUP_CACHE_TTL_S` | `30` | |

## Run locally

```bash
cd services/dashboard-bff
uv sync
uv run uvicorn dashboard_bff.api:app --port 8000
```

## Tests

- Unit: scope filter SQL composition, WebSocket message routing, JWKS refresh.
- Integration: end-to-end with real Redis Pub/Sub + Postgres; assert RBAC
  filters reject out-of-scope requests with 403 + audit log entry.

## Critical paths

- **RBAC enforcement on every read.** A forgotten `WHERE area_id IN scope`
  is a security incident. The integration test suite includes a "denied
  access" matrix that must stay green.
- WebSocket fan-out at high regional scope is the highest risk for the
  user-facing path. Don't push per-sensor deltas to a regional manager —
  push rollups and let drill-down trigger a finer subscription.
- The JWKS public key is cached. Stale keys after rotation cause 401s in
  the wild — refresh on first 401 with `kid` mismatch before failing.
