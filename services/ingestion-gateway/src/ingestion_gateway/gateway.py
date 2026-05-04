"""MQTT subscriber + Kafka producer: the core ingestion-gateway worker."""

import asyncio
import json
from datetime import UTC, datetime

import paho.mqtt.client as mqtt
import structlog
from aiokafka import AIOKafkaProducer
from pydantic import ValidationError

from ingestion_gateway.config import Settings
from ingestion_gateway.models import KafkaMessage, TelemetryEnvelope
from ingestion_gateway.sensor_cache import SensorCache
from ingestion_gateway.metrics import (
    MESSAGES_ACCEPTED,
    MESSAGES_RECEIVED,
    MESSAGES_REJECTED,
    KAFKA_PRODUCE_ERRORS,
)

log = structlog.get_logger(__name__)


class Gateway:
    """Bridges MQTT → Kafka with validation and sensor-binding enforcement."""

    def __init__(
        self,
        config: Settings,
        pool,  # asyncpg.Pool — typed loosely to avoid import-time asyncpg requirement
        producer: AIOKafkaProducer,
        cache: SensorCache,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._config = config
        self._pool = pool
        self._producer = producer
        self._cache = cache
        self._loop = loop
        self._mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._mqtt_client.on_connect = self._on_connect
        self._mqtt_client.on_message = self._on_message
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect to MQTT and start the Kafka producer."""
        await self._producer.start()

        # paho's connect() blocks on DNS + TCP — run in thread pool.
        await self._loop.run_in_executor(
            None,
            lambda: self._mqtt_client.connect(
                self._config.mqtt_host, self._config.mqtt_port, keepalive=60
            ),
        )
        # loop_start() spawns the paho network thread.
        self._mqtt_client.loop_start()
        self._started = True
        log.info(
            "gateway.started",
            mqtt_host=self._config.mqtt_host,
            mqtt_port=self._config.mqtt_port,
            kafka_topic=self._config.kafka_topic,
        )

    async def stop(self) -> None:
        """Gracefully shut down MQTT and Kafka connections."""
        if self._started:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()

        # Flush any buffered Kafka messages before stopping.
        try:
            await self._producer.stop()
        except Exception:
            log.exception("gateway.producer_stop_error")

        log.info("gateway.stopped")

    # ------------------------------------------------------------------
    # MQTT callbacks (run in paho's background thread)
    # ------------------------------------------------------------------

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            log.error("mqtt.connect_failed", reason=str(reason_code))
            return
        log.info("mqtt.connected")
        client.subscribe("sensors/+", qos=1)
        log.info("mqtt.subscribed", topic="sensors/+")

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: object,
        msg: mqtt.MQTTMessage,
    ) -> None:
        """Called from paho's network thread — schedule coroutine on the event loop."""
        MESSAGES_RECEIVED.inc()
        asyncio.run_coroutine_threadsafe(self._process(msg), self._loop)

    # ------------------------------------------------------------------
    # Async processing pipeline (runs on the event loop)
    # ------------------------------------------------------------------

    async def _process(self, msg: mqtt.MQTTMessage) -> None:  # noqa: C901 (complexity)
        topic = msg.topic

        # 1. Parse JSON
        try:
            payload = json.loads(msg.payload)
        except json.JSONDecodeError as exc:
            log.warning("gateway.json_parse_error", topic=topic, error=str(exc))
            MESSAGES_REJECTED.labels(reason="schema_invalid").inc()
            return

        # 2. Validate against TelemetryEnvelope schema
        try:
            envelope = TelemetryEnvelope.model_validate(payload)
        except ValidationError as exc:
            log.warning(
                "gateway.schema_invalid",
                topic=topic,
                errors=exc.errors(include_url=False),
            )
            MESSAGES_REJECTED.labels(reason="schema_invalid").inc()
            return

        sensor_id = envelope.sensor_id
        claimed_area_id = envelope.area_id

        # 3. Look up sensor in cache (queries Postgres on miss)
        cached_area_id = await self._cache.get_area_id(sensor_id)

        # 4. Reject unknown sensors
        if cached_area_id is None:
            log.debug("gateway.unknown_sensor", sensor_id=sensor_id, topic=topic)
            MESSAGES_REJECTED.labels(reason="unknown_sensor").inc()
            return

        # 5. Reject area_id spoofing — payload must match the registered binding
        if claimed_area_id != cached_area_id:
            log.warning(
                "gateway.area_mismatch",
                sensor_id=sensor_id,
                claimed_area_id=claimed_area_id,
                registered_area_id=cached_area_id,
            )
            MESSAGES_REJECTED.labels(reason="area_mismatch").inc()
            return

        # 6. Stamp with server-side ingestion time
        ingested_at = datetime.now(UTC).isoformat()
        kafka_msg = KafkaMessage(
            **envelope.model_dump(),
            ingested_at=ingested_at,
        )

        # 7. Produce to Kafka (key = area_id for co-partitioning)
        try:
            await self._producer.send(
                self._config.kafka_topic,
                key=cached_area_id.encode("utf-8"),
                value=json.dumps(kafka_msg.model_dump()).encode("utf-8"),
            )
            MESSAGES_ACCEPTED.inc()
            log.debug(
                "gateway.message_accepted",
                sensor_id=sensor_id,
                area_id=cached_area_id,
                topic=self._config.kafka_topic,
            )
        except Exception as exc:
            log.error(
                "gateway.kafka_produce_error",
                sensor_id=sensor_id,
                area_id=cached_area_id,
                error=str(exc),
            )
            KAFKA_PRODUCE_ERRORS.inc()
            # Do NOT re-raise — alert path must remain robust.
