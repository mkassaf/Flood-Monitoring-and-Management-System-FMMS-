"""Kafka consumer — dedup, persist, fan-out via Redis Pub/Sub."""

from __future__ import annotations

import json

import structlog
from aiokafka import AIOKafkaConsumer
from pydantic import ValidationError
from prometheus_client import Counter, REGISTRY

from alert_service.config import settings
from alert_service.db import insert_alert
from alert_service.models import Alert
from alert_service.publisher import AlertPublisher

log = structlog.get_logger(__name__)

def _counter(name: str, doc: str, labels: list[str] | None = None) -> Counter:
    try:
        return Counter(name, doc, labels or [])
    except ValueError:
        return REGISTRY._names_to_collectors.get(name)  # type: ignore[return-value]


MESSAGES_CONSUMED = _counter("alert_service_messages_consumed_total", "Messages consumed from Kafka", ["topic"])
ALERTS_PERSISTED = _counter("alert_service_alerts_persisted_total", "Alerts inserted into Postgres", ["kind", "severity"])
ALERTS_DEDUPED = _counter("alert_service_alerts_deduplicated_total", "Alerts skipped as duplicates")
PUBLISH_ERRORS = _counter("alert_service_publish_errors_total", "Redis Pub/Sub publish failures")


class AlertConsumer:
    """Subscribes to all three alert topics and drives the processing pipeline."""

    def __init__(self, db_pool: object, publisher: AlertPublisher) -> None:
        self._pool = db_pool
        self._publisher = publisher

    async def start(self) -> None:
        consumer: AIOKafkaConsumer = AIOKafkaConsumer(  # type: ignore[type-arg]
            *settings.KAFKA_TOPICS,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP,
            group_id=settings.KAFKA_CONSUMER_GROUP,
            auto_offset_reset="latest",
            enable_auto_commit=True,
        )
        await consumer.start()
        log.info("alert_consumer.started", topics=settings.KAFKA_TOPICS)
        try:
            async for msg in consumer:
                topic = msg.topic
                MESSAGES_CONSUMED.labels(topic=topic).inc()
                await self._handle(msg.value, topic)
        finally:
            await consumer.stop()
            log.info("alert_consumer.stopped")

    async def _handle(self, raw: bytes, topic: str) -> None:
        try:
            payload = json.loads(raw.decode())
            alert = Alert.model_validate(payload)
        except (json.JSONDecodeError, ValidationError):
            log.warning("alert_consumer.invalid_message", topic=topic, raw=raw[:200])
            return

        inserted = await insert_alert(self._pool, alert)  # type: ignore[arg-type]
        if not inserted:
            ALERTS_DEDUPED.inc()
            log.debug("alert_consumer.deduped", alert_id=alert.alert_id)
            return

        ALERTS_PERSISTED.labels(kind=alert.kind, severity=alert.severity).inc()
        log.info(
            "alert_consumer.persisted",
            alert_id=alert.alert_id,
            kind=alert.kind,
            severity=alert.severity,
            area_id=alert.area_id,
        )

        try:
            await self._publisher.publish(alert)
        except Exception:
            PUBLISH_ERRORS.inc()
            log.exception("alert_consumer.publish_error", alert_id=alert.alert_id)
