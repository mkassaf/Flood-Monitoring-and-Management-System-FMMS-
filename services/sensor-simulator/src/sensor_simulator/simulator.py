"""Simulator orchestrator: manages the sensor pool and the MQTT connection."""

from __future__ import annotations

import asyncio
import random
import uuid
from typing import Any

import paho.mqtt.client as mqtt
import structlog
from prometheus_client import Counter

from sensor_simulator.config import Settings
from sensor_simulator.sensor import PARAM_META, Sensor

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
MESSAGES_PUBLISHED = Counter(
    "sim_messages_published_total",
    "Total MQTT messages published by the simulator",
    labelnames=["area_id"],
)
MESSAGES_SUPPRESSED = Counter(
    "sim_messages_suppressed_total",
    "Total messages suppressed by the delta edge filter",
    labelnames=["area_id"],
)

# Number of active params chosen per sensor (inclusive bounds)
MIN_ACTIVE_PARAMS = 2
MAX_ACTIVE_PARAMS = 4


def _make_id(index: int) -> str:
    """Create a stable UUID from an integer index."""
    return str(uuid.UUID(int=index))


def _build_mqtt_client(settings: Settings) -> mqtt.Client:
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"sensor-simulator-{uuid.uuid4().hex[:8]}",
    )
    client.enable_logger(logger=None)  # disable paho's own logger; we use structlog
    return client


class Simulator:
    """Manages the full sensor pool and their asyncio tasks."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: mqtt.Client | None = None
        self._tasks: list[asyncio.Task[Any]] = []
        self._log = logger.bind(service="simulator")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect to MQTT broker, then spawn one asyncio task per sensor."""
        settings = self._settings
        self._log.info(
            "starting simulator",
            sensor_count=settings.sim_sensor_count,
            area_count=settings.sim_area_count,
            mqtt_host=settings.mqtt_host,
            mqtt_port=settings.mqtt_port,
        )

        client = _build_mqtt_client(settings)
        self._client = client

        # Connect synchronously in a thread pool so we don't block the event loop.
        await asyncio.to_thread(
            client.connect,
            settings.mqtt_host,
            settings.mqtt_port,
            60,  # keepalive seconds
        )
        client.loop_start()  # paho background thread for network I/O
        self._log.info("MQTT connected")

        # Deterministic RNG: sensors stay stable across restarts.
        rng = random.Random(42)  # noqa: S311
        all_params = list(PARAM_META.keys())

        sensors = []
        for i in range(settings.sim_sensor_count):
            sensor_id = _make_id(i)
            area_id = _make_id(settings.sim_sensor_count + (i % settings.sim_area_count))
            k = rng.randint(MIN_ACTIVE_PARAMS, MAX_ACTIVE_PARAMS)
            active_params = rng.sample(all_params, k)
            sensor_rng = random.Random(rng.getrandbits(64))  # noqa: S311
            sensors.append(
                Sensor(
                    sensor_id=sensor_id,
                    area_id=area_id,
                    active_params=active_params,
                    nominal_interval=settings.sim_nominal_interval_s,
                    critical_interval=settings.sim_critical_interval_s,
                    fault_probability=settings.sim_fault_probability,
                    delta_filter_pct=settings.sim_delta_filter_pct,
                    rng=sensor_rng,
                )
            )

        self._tasks = [
            asyncio.create_task(
                sensor.run(client, MESSAGES_PUBLISHED, MESSAGES_SUPPRESSED),
                name=f"sensor-{sensor.sensor_id}",
            )
            for sensor in sensors
        ]
        self._log.info("sensor tasks created", count=len(self._tasks))

    async def stop(self) -> None:
        """Cancel all sensor tasks and disconnect from MQTT."""
        self._log.info("stopping simulator")

        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        if self._client is not None:
            self._client.loop_stop()
            await asyncio.to_thread(self._client.disconnect)
            self._client = None

        self._log.info("simulator stopped")
