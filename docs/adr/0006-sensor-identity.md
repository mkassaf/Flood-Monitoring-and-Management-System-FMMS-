# ADR-006 — Sensor identity: per-area X.509 + per-sensor token

**Status:** Accepted (Phase 1)
**Related:** ADR-002 (MQTT), ADR-007 (user auth), NFR-04, NFR-08

## Context

Sensor identity must:

- Cryptographically authenticate each sensor to the broker (NFR-04).
- Allow the ingestion gateway to verify the sensor's claim about its `area_id` (preventing cross-area spoofing).
- Support **150K endpoints** without making certificate operations the dominant cost (NFR-08).
- Support revocation when a sensor is decommissioned or compromised.
- Tolerate intermittent connectivity for sensors in the field.

The naive choice — one X.509 cert per sensor — gives the strongest security but multiplies CA operations by 150K and creates a heavy revocation problem (CRLs at this scale are operationally painful; OCSP is online and adds latency).

## Decision

Two-layer identity:

1. **Per-area X.509 client certificate** for mTLS to the MQTT broker.
   - Each operational *area* (10–200 sensors per Phase 0) shares one client certificate, scoped by Common Name `area:{area_id}`.
   - Broker-level ACL: a connection presenting `CN=area:A` may only publish on `fmms/area/A/...`.
   - This blocks cross-area traffic at the broker layer.
2. **Per-sensor symmetric token** carried in the MQTT 5 connection properties (`Authentication-Method` / `Authentication-Data`).
   - Token is unique per sensor, issued at provisioning, stored in `opdb`.
   - The **ingestion gateway** verifies the token against `opdb` (cached for 5 min in process) and rejects unknown / mismatched sensors.
   - Token rotation on suspicion of compromise is a single-row update in `opdb`; no PKI ceremony.

Combined enforcement:
- **At broker:** mTLS pins the area.
- **At ingestion:** token pins the individual sensor *within* the area.

## Considered Alternatives

### A1. Per-sensor X.509 certificates
- **Pros:** Strongest possible identity model; standard practice.
- **Cons:** 150K cert lifecycle (issuance, renewal, revocation) is a serious operational burden. CRLs grow large; OCSP per connection adds latency. Lost certs require physical re-provisioning.
- **Verdict:** rejected for the *current* scale; would be reconsidered for safety-critical / regulatory contexts.

### A2. Single shared cert + per-sensor token
- **Pros:** Simplest cert ops.
- **Cons:** A leaked cert exposes the entire sensor fleet. No defense-in-depth.
- **Verdict:** rejected — single failure mode.

### A3. Token-only (no mTLS)
- **Pros:** Trivial to issue and rotate.
- **Cons:** Token can be replayed or stolen on the wire if TLS is somehow misconfigured; cross-area spoofing only detectable at the application layer; loses the broker as a security boundary.
- **Verdict:** rejected — TLS is required regardless (NFR-04 in transit), so mTLS is incremental cost.

### A4. OAuth 2.0 device flow
- **Pros:** Token-based, modern, revocable.
- **Cons:** Designed for human-bootstrapped devices, not unattended field sensors; refresh-token rotation at 60s frequency is overhead; not ergonomic for MQTT-native sensors.
- **Verdict:** rejected — wrong design center.

## Consequences

**Positive**
- Two-layer model: a leaked area cert exposes only that area's traffic; a leaked token exposes only one sensor.
- Token rotation is cheap (DB row update); cert rotation is rare (per area, on a long schedule).
- 150K sensors → ~750–15,000 areas (per Phase 0 sizing of 10–200 sensors per area) → manageable cert population.

**Negative**
- The ingestion gateway becomes a security-critical component (the second auth layer). Mitigated by treating it as part of the trust boundary and pen-testing it in Phase 5 (QAS-05).
- Token verification is a synchronous DB hit on first connection; the 5-minute in-process cache amortizes this. The cache is a small DoS surface — a flood of new sensor IDs would force lookups. Rate-limited at the broker.

**Risks**
- If areas become very large (>200 sensors), a single area cert leak becomes more damaging. Re-evaluate threshold in Phase 7+.
- Token storage in `opdb` must be hashed at rest (bcrypt or argon2id), not plaintext.
