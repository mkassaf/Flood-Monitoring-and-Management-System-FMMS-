# ADR-009 — Real-time UI push: WebSocket via dashboard-bff

**Status:** Accepted (Phase 1)
**Related:** ADR-007 (auth), QAS-04, QAS-06

## Context

Managers expect updates to appear "live": new sensor readings, new alerts, status changes. Requirements:

- Latency from event to UI ≤2 s P95 (QAS-04 alert path).
- Up to 50 concurrent manager sessions (FR-13).
- Per-user filtering by jurisdiction scope (NFR-04, FR-12).
- Survives transient network disruption (managers may be on mobile / spotty connections during emergencies).
- Works through corporate proxies / firewalls.

The dashboard-bff is the only user-reachable data-plane service (per ADR-001) and therefore is the only correct fan-out point.

## Decision

Use **WebSocket (WSS)** between the frontend SPA and dashboard-bff for real-time push.

- **Channel model:** one WebSocket per session. On connect, the BFF resolves the user's scope (from JWT — ADR-007) to a flat list of `area_id`s.
- **Server-side fan-out:** dashboard-bff subscribes per-connection to **Redis Pub/Sub** channels `area:{id}:updates`. Telemetry-service and alert-service publish to these channels on every relevant event. Per-area channel cardinality keeps fan-out bounded.
- **Delta-only payloads:** the BFF sends only changed fields (latest reading, status change, new alert). Initial dashboard state is fetched via REST on page load.
- **Reconnection:** client uses exponential backoff with jitter; on reconnect, the BFF replays missed alerts since the client's last-seen alert ID (alerts are durable in `opdb`; telemetry deltas are not — the client just gets the current snapshot).
- **Heartbeat:** ping/pong every 30 s to detect half-open connections.

## Considered Alternatives

### A1. Server-Sent Events (SSE)
- **Pros:** HTTP-native, simpler; auto-reconnect; works through more proxies than WebSocket.
- **Cons:** Unidirectional only — useful here since the data flow is server → client, but we also need client-initiated actions (alert acknowledge, scope change subscriptions) which would need a separate REST round trip. Less efficient at high message rate due to per-event header overhead.
- **Verdict:** rejected — bidirectional channel is cleaner for this use case, and WebSocket support is universally available now.

### A2. Long polling
- **Pros:** Universal compatibility.
- **Cons:** High overhead; latency floor is the polling interval; doesn't satisfy QAS-04 ≤2 s without aggressive polling that wastes server resources.
- **Verdict:** rejected — fails NFR-07 efficiency.

### A3. MQTT-over-WebSocket (the same broker for users)
- **Pros:** Reuse the broker; no separate fan-out.
- **Cons:** Conflates the sensor data plane with the user-facing UX layer — violates ADR-001's principle that the BFF is the only user-reachable data-plane component; complicates RBAC enforcement (broker-level ACLs are coarser than per-area scope filters).
- **Verdict:** rejected — separation of concerns matters more than infrastructure reuse.

### A4. gRPC-Web with server streaming
- **Pros:** Schema-typed; HTTP/2 multiplexing.
- **Cons:** gRPC-Web requires a proxy (Envoy) to translate; bigger learning curve for frontend; ecosystem is smaller for React + maps; advantages don't materialize at this scale.
- **Verdict:** rejected — overkill.

## Consequences

**Positive**
- Per-connection scope filtering at the BFF is the natural enforcement point for RBAC (ADR-007).
- Redis Pub/Sub gives O(connections × areas-of-interest) fan-out — bounded and well within Redis throughput at this scale.
- Delta payloads keep WS traffic small; full snapshots only on initial load and reconnect.

**Negative**
- WebSocket connections are stateful — they limit horizontal scaling of the BFF (each pod holds N connections). Mitigated by sticky load balancing and by setting per-pod connection budget.
- Some corporate proxies still mishandle WS upgrade. Mitigated by WSS (TLS-wrapped) which most proxies pass through.

**Risks**
- Redis Pub/Sub does not buffer — if a BFF pod crashes mid-push, in-flight events are lost on the wire, but durable alerts are recoverable via the reconnect-replay protocol described above.
- At extreme regional manager scope (~50K sensors), per-event push is unsustainable. The BFF aggregates rollups (city/region) for these views and only pushes per-sensor detail when the user drills down.
