# sensor-simulator

Generates synthetic MQTT traffic that looks like a real sensor fleet. Used to
exercise the PoC end-to-end and to drive load tests for QAS-03 / QAS-04.

## Bounded context

This service is **not** part of the production system. In production, real sensor
firmware (or a LoRa/NB-IoT bridge) would publish to the MQTT broker. The
simulator stands in for that source.

## Behavior

- Spawns `SIM_SENSOR_COUNT` virtual sensors (default 1,000), distributed across
  `SIM_AREA_COUNT` areas (default 20) — Phase 0 D-02 PoC scale.
- Each sensor owns its own asyncio task and one MQTT 5 session.
- Publishes to `fmms/area/{area_id}/sensor/{sensor_id}/telemetry`.
- Emits at `SIM_NOMINAL_INTERVAL_S` (default 60s) when nominal,
  `SIM_CRITICAL_INTERVAL_S` (default 5s) when critical (Phase 0 D-01).
- A sensor enters critical mode when its locally simulated value crosses a
  configured threshold — modeling FR-10 honestly.
- Edge filtering: suppresses retransmission of an identical reading within a
  configurable delta (energy efficiency — NFR-07).
- Periodic operational status (`status=0/1`) with a small failure-rate to
  exercise FR-07 / FR-08 paths.

## Demo modes

`python -m sensor_simulator.demos <case>` drives a scripted scenario that the
demo Make targets invoke:

- `case_1` — One sensor in one area crosses a water-level threshold. Validates
  the Phase 0 Case 1 flow.
- `case_2` — Coordinated rainfall across multiple regions. Validates Case 2
  burst behavior.
- `case_3` — Two redundant sensors in one area; first fails (low-priority
  malfunction); second fails (escalation to high-priority). Validates Case 3.

## Inputs

- Area + sensor inventory: read from geo-service at startup.
  - In standalone mode (no geo-service running), uses a baked-in fixture.

## Outputs

- MQTT publishes — see contract `contracts/telemetry-envelope.schema.json`.
- Prometheus metrics on `:8000/metrics`:
  - `sim_sensors_total`
  - `sim_messages_published_total{mode}`
  - `sim_critical_mode_active{area_id}`
  - `sim_edge_filter_dropped_total`

## Configuration (env vars)

| Var | Default | Notes |
|---|---|---|
| `MQTT_HOST` | `mosquitto` | |
| `MQTT_PORT` | `1883` | |
| `SIM_SENSOR_COUNT` | `1000` | Phase 0 D-02. |
| `SIM_AREA_COUNT` | `20` | |
| `SIM_NOMINAL_INTERVAL_S` | `60` | |
| `SIM_CRITICAL_INTERVAL_S` | `5` | |
| `SIM_FAILURE_RATE_PCT` | `0.1` | Synthetic per-cycle sensor failure probability. |
| `SIM_EDGE_FILTER_DELTA` | `0.01` | Suppress identical readings within ±1%. |

## Run locally

```bash
cd services/sensor-simulator
uv sync
MQTT_HOST=localhost SIM_SENSOR_COUNT=10 python -m sensor_simulator
```

In Docker Compose: comes up with `make up-all` automatically.

## Tests

- Unit: deterministic value-generation behavior, edge-filter logic, mode
  transitions.
- Integration: connects to a containerized Mosquitto and asserts the published
  payload conforms to the schema.
