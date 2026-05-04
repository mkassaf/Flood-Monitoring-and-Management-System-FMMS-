"""Kafka consumer for the 'telemetry' topic.

Decodes each message as a TelemetryMessage, hands it to the BatchWriter for
persistence, and updates the Redis hot state per reading.  Invalid messages are
logged and counted but never block the consumer loop.
"""

from __future__ import annotations

import json

import structlog
from aiokafka import AIOKafkaConsumer
from prometheus_client import Counter
from pydantic import ValidationError

from telemetry_service.config import settings
from telemetry_service.hot_state import HotStateUpdater
from telemetry_service.models import TelemetryMessage
from telemetry_service.writer import BatchWriter

log = structlog.get_logger(__name__)

# ─── Prometheus metrics ────────────────────────────────────────────────────────

messages_consumed_total = Counter(
    "telemetry_messages_consumed_total",
    "Total Kafka messages received by the consumer",
)

messages_parse_errors_total = Counter(
    "telemetry_messages_parse_errors_total",
    "Kafka messages that failed JSON / Pydantic validation",
)


class TelemetryConsumer:
    """Wraps an AIOKafkaConsumer and drives the writer + hot-state pipeline."""

    def __init__(self) -> None:
        self._consumer: AIOKafkaConsumer | None = None

    async def start(self, writer: BatchWriter, hot_state: HotStateUpdater) -> None:
        """Start consuming.  Runs until cancelled."""
        self._consumer = AIOKafkaConsumer(
            settings.KAFKA_TOPIC,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP,
            group_id=settings.KAFKA_CONSUMER_GROUP,
            auto_offset_reset=settings.KAFKA_AUTO_OFFSET_RESET,
            enable_auto_commit=True,
            value_deserializer=lambda raw: raw,  # we decode ourselves for better error handling
        )
        await self._consumer.start()
        log.info(
            "kafka_consumer.started",
            topic=settings.KAFKA_TOPIC,
            group=settings.KAFKA_CONSUMER_GROUP,
        )
        try:
            async for record in self._consumer:
                messages_consumed_total.inc()
                await self._handle(record.value, writer, hot_state)
        finally:
            await self._consumer.stop()
            log.info("kafka_consumer.stopped")

    async def _handle(
        self,
        raw: bytes,
        writer: BatchWriter,
        hot_state: HotStateUpdater,
    ) -> None:
        """Parse one Kafka record and fan out to writer + hot state."""
        try:
            payload = json.loads(raw)
            msg = TelemetryMessage.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, UnicodeDecodeError):
            messages_parse_errors_total.inc()
            log.warning("kafka_consumer.parse_error", raw_preview=raw[:200])
            return

        try:
            await writer.enqueue(msg)
        except Exception:
            log.exception("kafka_consumer.enqueue_error", sensor_id=msg.sensor_id)

        try:
            await hot_state.update(msg)
        except Exception:
            log.exception("kafka_consumer.hot_state_error", sensor_id=msg.sensor_id)
