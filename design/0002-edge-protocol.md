# ADR-002 — Edge protocol: MQTT 5 over TLS

**Status:** Accepted (Phase 1)
**Related:** ADR-006 (sensor identity), ADR-003 (broker→backbone bridge)

## Context

Sensors transmit small (<1 KB) telemetry payloads at 60 s nominal frequency, escalating to 5 s under critical conditions (D-01). The system must:

- Handle up to 150,000 long-lived sensor connections.
- Minimize sensor-side energy consumption (NFR-07) — sensors may be solar/battery in the field.
- Encrypt traffic (NFR-04).
- Survive intermittent connectivity (FR-10 implies sensors stay connected across mode changes).
- Report operational status (FR-02) and detect silent failure (FR-07).

The protocol choice is highly path-dependent: it is embedded in firmware, defines the broker, and constrains the identity model.

## Decision

Adopt **MQTT 5 over TLS 1.3** as the sensor-to-platform protocol.

- One **persistent session per sensor**, identified by client ID = `sensor:{uuid}`.
- **Topic structure:** `fmms/area/{area_id}/sensor/{sensor_id}/telemetry` and `.../status`.
- **QoS 1** for telemetry (at-least-once; idempotent on the consumer side via `(sensor_id, ts)` deduplication).
- **MQTT 5 features used:**
  - **Last Will and Testament** to detect disconnects (FR-07: silent failure).
  - **Topic aliases** to reduce per-message overhead at high frequency (NFR-07).
  - **Message expiry** to drop stale telemetry on broker overflow.
  - **Shared subscriptions** so the ingestion gateway can scale horizontally across broker subscribers (NFR-01).

## Considered Alternatives

### A1. CoAP (UDP-based)
- **Pros:** Lower per-message overhead than TCP-based protocols; designed for constrained devices.
- **Cons:** No native long-lived session; requires custom keep-alive and observe-pattern boilerplate; ecosystem maturity is lower than MQTT in industrial monitoring; adaptive frequency state harder to track without sessions.
- **Verdict:** rejected — operational maturity matters more at 150K endpoints than the marginal byte savings.

### A2. HTTPS with periodic POST
- **Pros:** Universal tooling; simple firmware.
- **Cons:** TCP+TLS handshake on every message at 60 s frequency = energy disaster (NFR-07); no native push-down channel for the broker to ask a sensor to change frequency; significantly higher per-message bytes.
- **Verdict:** rejected — fails NFR-07.

### A3. AMQP 1.0
- **Pros:** Rich messaging semantics; broker-agnostic.
- **Cons:** Heavyweight for sensor firmware; ecosystem skewed toward enterprise integration, not IoT; broker resource cost per connection higher than MQTT.
- **Verdict:** rejected — wrong tool for the device class.

### A4. LoRaWAN / NB-IoT (radio-layer protocols)
- **Pros:** Optimal energy on the radio; designed for unattended field sensors.
- **Cons:** Out of scope for the PoC (D-03); these are *transport* technologies that would still terminate at an MQTT bridge in a real deployment. Documenting them now would conflate transport and application protocol.
- **Verdict:** deferred to Phase 7+; PoC simulates MQTT-over-TCP. Architecture is unchanged because the bridge would still expose MQTT inward.

## Consequences

**Positive**
- One persistent connection per sensor → no per-message handshake → energy savings (NFR-07).
- Topic aliases at high frequency reduce bytes per critical-mode message.
- LWT gives free silent-failure detection for FR-07.
- Shared subscriptions let the ingestion gateway scale horizontally without coordinator.

**Negative**
- Per-sensor connection state on the broker scales with sensor count → broker memory grows ~linearly. Mitigated by Mosquitto cluster sizing (production) and by per-area broker affinity.
- MQTT 5 is less universally supported than 3.1.1 in legacy hardware; firmware vendor list narrows. Acceptable for greenfield deployment.
- TLS termination cost on the broker is non-trivial at 150K connections. Mitigated by hardware offload or front-side TLS terminator (HAProxy / NLB) where supported.

**Risks**
- Topic aliases require both client and broker to support MQTT 5 features correctly. Validate during sensor sim development.
