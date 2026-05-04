# auth-service

Issues JWTs that carry the user's role and pre-expanded geographic scope. The
single signing authority for the platform.

## Bounded context

Owns `opdb.app_user` and `opdb.refresh_token` writes. The only service that
holds the JWT private key. Every other service holds the public key for
verification (the dashboard-bff is the primary verifier).

See **ADR-007** for the full token contract and the Keycloak migration path.

## Behavior

1. `POST /login` — username + password → access token (60 min) + refresh token (24 h).
   - Password is verified against argon2id hash in `opdb.app_user`.
   - At issuance, the user's `role` + `jurisdiction` JSONB is **expanded** by
     calling geo-service: a city manager's `cities` claim becomes the flat list
     of `area_id`s in those cities. The dashboard-bff then filters with one
     simple `WHERE area_id IN (...)`.
2. `POST /refresh` — refresh token → new access token. Refresh token is
   rotated; the old `jti` is marked revoked.
3. `POST /logout` — revoke a refresh token.
4. `GET /jwks.json` — public key in JWKS format for verifiers.
5. `POST /users` — create a user (admin only — gated in PoC by an admin token
   in env, replaced by proper admin role in Phase 7+).

## Token shape

```json
{
  "sub": "user-uuid",
  "role": "area_manager | city_manager | regional_manager",
  "scope": { "areas": ["area-uuid", ...] },
  "iat": 1700000000,
  "exp": 1700003600,
  "jti": "token-uuid"
}
```

The `scope.areas` field is always a flat list of area UUIDs, regardless of the
user's role. This is the key design property that lets the dashboard-bff treat
all three roles uniformly. See ADR-007 for the size analysis (regional managers
may carry ~1000 areas — measured at ~50 KB token, acceptable).

## Inputs

- REST: login / refresh / logout from frontend (via dashboard-bff).
- REST out: geo-service `POST /scopes/expand`.

## Outputs

- `opdb.app_user` (admin write only) and `opdb.refresh_token` writes.
- `opdb.audit_log`: every login (allowed and denied) is logged.

## Configuration

| Var | Default | Notes |
|---|---|---|
| `POSTGRES_DSN` | required | |
| `GEO_SERVICE_URL` | `http://geo-service:8000` | |
| `JWT_PRIVATE_KEY_PATH` | required | RS256. Mount as docker secret in production. |
| `JWT_PUBLIC_KEY_PATH` | required | Served via `/jwks.json`. |
| `JWT_ACCESS_TTL_S` | `3600` | |
| `JWT_REFRESH_TTL_S` | `86400` | |
| `ARGON2_TIME_COST` | `3` | |
| `ARGON2_MEMORY_COST` | `65536` | KiB. |

## Run locally

```bash
# generate keys first if you haven't:
mkdir -p secrets
openssl genpkey -algorithm RSA -out secrets/jwt_private.pem -pkeyopt rsa_keygen_bits:2048
openssl rsa -in secrets/jwt_private.pem -pubout -out secrets/jwt_public.pem

cd services/auth-service
uv sync
uv run uvicorn auth_service.api:app --port 8000
```

## Tests

- Unit: scope expansion, token signing, password verification, refresh rotation.
- Integration: full login → refresh → logout flow.

## Critical paths

- **Never log tokens or passwords.** Strip from request logs at the middleware
  layer.
- Refresh-token rotation is non-negotiable: a refresh that returns the same
  refresh token would invalidate revocation guarantees.
- Public-key rotation procedure: introduce the new key in `jwks.json` ≥
  `JWT_ACCESS_TTL_S` *before* signing with it, so verifiers have time to pick
  it up. Sign with both old and new during the rollover window. Documented in
  ADR-007.
