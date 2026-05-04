"""PoC demo scenarios for the three FMMS use cases.

Run via:
    python -m sensor_simulator.demos case_1
    python -m sensor_simulator.demos case_2
    python -m sensor_simulator.demos case_3
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime

import paho.mqtt.client as mqtt

from sensor_simulator.config import settings
from sensor_simulator.models import Measurements, TelemetryEnvelope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _make_envelope(
    sensor_id: str,
    area_id: str,
    measurements: Measurements,
    *,
    status: int = 1,
    mode: str = "nominal",
) -> TelemetryEnvelope:
    return TelemetryEnvelope(
        sensor_id=sensor_id,
        area_id=area_id,
        ts=_now_iso(),
        status=status,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        measurements=measurements,
    )


def _connect() -> mqtt.Client:
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"fmms-demo-{uuid.uuid4().hex[:6]}",
    )
    client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=30)
    client.loop_start()
    return client


def _publish(client: mqtt.Client, sensor_id: str, envelope: TelemetryEnvelope) -> None:
    payload = envelope.model_dump_json()
    topic = f"sensors/{sensor_id}"
    info = client.publish(topic, payload, qos=1)
    info.wait_for_publish(timeout=5.0)
    # Pretty-print to stdout so demo output is readable
    print(f"  [{envelope.ts}] {topic}")
    print(f"    mode={envelope.mode} status={envelope.status}")
    data = json.loads(payload)["measurements"]
    for k, v in data.items():
        if v is not None:
            print(f"    {k}: {v:.3f}")


# ---------------------------------------------------------------------------
# Case 1 — Single sensor, single area: ramp water_level_m past threshold (3m)
# ---------------------------------------------------------------------------


async def case_1() -> None:
    """Single sensor ramps water_level_m past critical threshold (3 m)."""
    print("\n=== Case 1: Water level rising past flood threshold ===\n")
    client = _connect()
    # Real seeded IDs — Milan District 1
    sensor_id = "9b60ced7-60e7-4d07-b26e-6bbd7f82de28"
    area_id = "fc1bbbfd-db55-4434-a932-24ac733d995d"

    water_level = 1.0
    step = 0.4  # reaches 5 m (> critical_hi=3) within 10 readings

    for i in range(10):
        water_level = min(6.0, water_level + step)
        mode = "critical" if water_level > 3.0 else "nominal"
        meas = Measurements(water_level_m=water_level)
        env = _make_envelope(sensor_id, area_id, meas, mode=mode)
        print(f"Reading {i + 1}/10:")
        _publish(client, sensor_id, env)
        await asyncio.sleep(1.0)

    client.loop_stop()
    client.disconnect()
    print("\nCase 1 complete.\n")


# ---------------------------------------------------------------------------
# Case 2 — Storm scenario: 5 sensors across 3 areas all go critical simultaneously
# ---------------------------------------------------------------------------


async def case_2() -> None:
    """Storm scenario: sensors across multiple areas simultaneously enter critical mode."""
    print("\n=== Case 2: Storm scenario — multi-area simultaneous critical ===\n")
    client = _connect()

    # Real seeded sensors across 3 Florence districts (rainfall critical_hi=30 mm/h)
    sensors = [
        ("6768661b-eefa-4f4d-bad6-08a4f492e623", "11b6fbd1-192d-40ca-8e42-b2d2bccba25f"),
        ("c00cc6c0-d53d-4bdc-8f6f-2ee0c7168cb9", "11b6fbd1-192d-40ca-8e42-b2d2bccba25f"),
        ("3a6a4d49-3268-4c91-9275-0b80805b6637", "b0ec62b5-289e-4e2b-a574-8ae6af781655"),
        ("a7f6f4c0-540f-4556-931e-1ab615b6640a", "b0ec62b5-289e-4e2b-a574-8ae6af781655"),
        ("37c315de-bafd-479c-9dba-c752be37c6d8", "9b254709-db10-4db4-9178-7be73c454f39"),
    ]

    async def sensor_task(sensor_id: str, area_id: str, idx: int) -> None:
        rainfall = 5.0 + idx * 2.0  # staggered starting values, below warning (20)
        for step in range(10):
            # Ramp past critical_hi=30 mm/h within ~5 steps
            rainfall = min(60.0, rainfall + 6.0)
            mode = "critical" if rainfall > 30.0 else ("nominal" if rainfall < 20.0 else "warning")
            meas = Measurements(rainfall_mm_h=rainfall)
            mode = "critical" if rainfall > 30.0 else "nominal"
            env = _make_envelope(sensor_id, area_id, meas, mode=mode)
            print(f"Sensor {idx + 1} step {step + 1}/10:")
            _publish(client, sensor_id, env)
            await asyncio.sleep(1.0)

    tasks = [
        asyncio.create_task(sensor_task(sid, aid, idx))
        for idx, (sid, aid) in enumerate(sensors)
    ]
    await asyncio.gather(*tasks)
    client.loop_stop()
    client.disconnect()
    print("\nCase 2 complete.\n")


# ---------------------------------------------------------------------------
# Case 3 — Redundancy loss: two sensors in same area both go offline
# ---------------------------------------------------------------------------


async def case_3() -> None:
    """Two sensors in the same area — sensor 1 fails, then sensor 2 fails (total redundancy loss)."""
    print("\n=== Case 3: Redundancy loss — both sensors in area go offline ===\n")
    client = _connect()

    # Real seeded IDs — two sensors in Milan District 1
    area_id = "fc1bbbfd-db55-4434-a932-24ac733d995d"
    sensor_a = "9b60ced7-60e7-4d07-b26e-6bbd7f82de28"
    sensor_b = "dcdd6ecd-5cab-469b-8a6b-f51a7c9098c2"

    print("Phase 1: Both sensors healthy")
    for _ in range(3):
        for sid in (sensor_a, sensor_b):
            meas = Measurements(water_level_m=1.5)
            env = _make_envelope(sid, area_id, meas, status=1)
            _publish(client, sid, env)
        await asyncio.sleep(1.0)

    print("\nPhase 2: Sensor A fails (status=0)")
    for _ in range(4):
        meas_a = Measurements(water_level_m=1.5)
        env_a = _make_envelope(sensor_a, area_id, meas_a, status=0)
        _publish(client, sensor_a, env_a)

        meas_b = Measurements(water_level_m=1.6)
        env_b = _make_envelope(sensor_b, area_id, meas_b, status=1)
        _publish(client, sensor_b, env_b)
        await asyncio.sleep(1.0)

    print("\nPhase 3: Sensor B also fails — full redundancy loss!")
    for _ in range(4):
        for sid in (sensor_a, sensor_b):
            meas = Measurements(water_level_m=1.5)
            env = _make_envelope(sid, area_id, meas, status=0)
            _publish(client, sid, env)
        await asyncio.sleep(1.0)

    client.loop_stop()
    client.disconnect()
    print("\nCase 3 complete. Rule engine should have raised a redundancy alert.\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

CASES = {
    "case_1": case_1,
    "case_2": case_2,
    "case_3": case_3,
}


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in CASES:
        print(f"Usage: python -m sensor_simulator.demos <{'|'.join(CASES)}>")
        sys.exit(1)
    asyncio.run(CASES[sys.argv[1]]())


if __name__ == "__main__":
    main()
