# ADR-007 — User authentication: JWT with scope claims

**Status:** Accepted (Phase 1)
**Related:** ADR-006 (sensor identity), FR-12, NFR-04

## Context

User authentication and authorization must:

- Support three roles: Area Manager, City Manager, Regional Manager (FR-12).
- Carry the user's geographic jurisdiction so authorization can be enforced on every request without an extra DB hit (NFR-03 latency budget).
- Support up to 50 concurrent sessions (FR-13) and is unlikely to exceed a few hundred total accounts (Phase 0 open question 3).
- Scale horizontally with the dashboard-bff replicas (NFR-01).
- Enable audit logging of access decisions (NFR-04).

Phase 0 D-03 explicitly puts production-grade IAM (Keycloak, federated SSO) **out** of PoC scope. This ADR decides the PoC mechanism in a way that does not paint into a corner for production.

## Decision

Use **JWT (JSON Web Token)** with the following claims:

```
{
  "sub": "user-uuid",
  "role": "area_manager" | "city_manager" | "regional_manager",
  "scope": {
    "areas":   ["area-uuid-1", ...],   // for area_manager
    "cities":  ["city-uuid-1", ...],   // for city_manager
    "regions": ["region-uuid-1", ...]  // for regional_manager
  },
  "iat": 1700000000,
  "exp": 1700003600
}
```

- **Signing:** RS256 (asymmetric). Auth-service holds the private key; every other service holds the public key for verification.
- **Token lifetime:** 60 min access token; 24 h refresh token (refresh tokens stored server-side in `opdb`, revocable).
- **Enforcement point:** dashboard-bff is the only user-reachable service; it validates the token on every request and uses the scope claim to filter all reads (`WHERE area_id IN scope`).
- **Scope expansion:** at token issuance time, auth-service expands `cities` → all `area_id`s in that city by querying geo-service, and likewise for regions, so the dashboard-bff filtering is always against a flat list of `area_id`s.
- **Audit:** every denied access logged with `(user_id, attempted_scope, requested_resource, timestamp)`.

Production migration path (out of scope for now but designed for):
- Replace auth-service with Keycloak. Keep the JWT contract identical (same claim shape).
- Frontend OIDC flow → Keycloak → returns JWT in the same shape → dashboard-bff is unchanged.

## Considered Alternatives

### A1. Server-side sessions (cookie + Redis session store)
- **Pros:** Easy revocation; smaller in-flight payload.
- **Cons:** Every request hits the session store → adds latency and a hard dependency on Redis for every dashboard read; doesn't carry scope intrinsically.
- **Verdict:** rejected — JWT pushes scope into the request, removing a per-request lookup.

### A2. JWT without scope claims (scope looked up per request)
- **Pros:** Smaller token; revoking scope is immediate (just update DB).
- **Cons:** Adds a per-request DB hit to geo-service; scales poorly.
- **Verdict:** rejected — per-request scope lookup is a measurable latency tax.

### A3. Keycloak from day one
- **Pros:** Production-grade now, no migration later, federated SSO ready.
- **Cons:** Operational overhead (DB, mail, theming); more than the PoC needs; explicitly out of scope per D-03.
- **Verdict:** deferred to Phase 7+; the JWT contract is designed to make this a drop-in replacement.

### A4. mTLS for users (client certificates)
- **Pros:** Strongest possible auth.
- **Cons:** Operationally hostile for human users (browser cert install); not suited to a web dashboard UX.
- **Verdict:** rejected.

## Consequences

**Positive**
- Stateless authentication on the read path → dashboard-bff scales horizontally without coordination.
- Scope claim eliminates a per-request lookup that would otherwise hit geo-service on every dashboard render.
- Token contract designed for Keycloak migration without code changes downstream.

**Negative**
- 60-minute access tokens mean revoked scopes (e.g., a manager moved to a different jurisdiction) take up to 60 minutes to fully propagate. Mitigated by short-lived tokens; for safety-critical revocations, also push a denylist entry to Redis with the token's `jti` claim.
- Token grows with the size of the user's jurisdiction. A regional manager covering 50 cities × 20 areas/city = 1000 area UUIDs. UUID = 36 chars; 1000 × 36 = 36 KB JSON, ~50 KB token base64. Acceptable for HTTPS but worth measuring.

**Risks**
- Public key rotation on the auth-service requires a rollout window during which both old and new keys are valid for verification. Document the procedure when implementing.
