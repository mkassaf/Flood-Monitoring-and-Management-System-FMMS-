"""Kafka consumer loop — reads telemetry, runs evaluators, emits alerts."""

from __future__ import annotations

import json
from typing import Any

import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from pydantic import ValidationError
from redis.asyncio import Redis

from rule_engine.config import settings
from rule_engine.metrics import ALERTS_EMITTED, EVENTS_EVALUATED
from rule_engine.models import Alert, TelemetryMessage
from rule_engine.redundancy_tracker import RedundancyTracker
from rule_engine.threshold_cache import ThresholdCache
from rule_engine.threshold_evaluator import evaluate_thresholds

log = structlog.get_logger(__name__)

# Sliding window of recent sensor values used for trend computation.
# keyed by (sensor_id, parameter) → list[float] (max 5 entries)
_sensor_history: dict[tuple[str, str], list[float]] = {}
_HISTORY_MAX = 5


def _update_history(sensor_id: str, param: str, value: float) -> list[float]:
    key = (sensor_id, param)
    history = _sensor_history.get(key, [])
    history = (history + [value])[-_HISTORY_MAX:]
    _sensor_history[key] = history
    return history[:-1]  # return history *before* adding current value


async def _emit_alert(producer: AIOKafkaProducer, alert: Alert) -> None:  # type: ignore[type-arg]
    topic = alert.kafka_topic()
    try:
        payload = alert.model_dump_json().encode()
        await producer.send(topic, value=payload, key=alert.area_id.encode())
        ALERTS_EMITTED.labels(kind=alert.kind, severity=alert.severity).inc()
    except Exception:
        log.exception("consumer.kafka_produce_error", topic=topic, alert_id=alert.alert_id)


class RuleEngineConsumer:
    """Manages the Kafka consumer loop and alert emission pipeline."""

    def __init__(
        self,
        redis_client: Redis,  # type: ignore[type-arg]
        threshold_cache: ThresholdCache,
        redundancy_tracker: RedundancyTracker,
    ) -> None:
        self._redis = redis_client
        self._threshold_cache = threshold_cache
        self._redundancy_tracker = redundancy_tracker
        self._consumer: AIOKafkaConsumer | None = None  # type: ignore[type-arg]
        self._producer: AIOKafkaProducer | None = None  # type: ignore[type-arg]

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            settings.kafka_topic,
            bootstrap_servers=settings.kafka_bootstrap,
            group_id=settings.kafka_consumer_group,
            auto_offset_reset="latest",
            value_deserializer=lambda b: json.loads(b.decode()),
            enable_auto_commit=True,
        )
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.alert_kafka_bootstrap,
            compression_type="gzip",
        )
        await self._consumer.start()
        await self._producer.start()
        log.info("rule_engine.consumer.started", topic=settings.kafka_topic)

        try:
            async for msg in self._consumer:
                await self._process(msg.value)
        finally:
            await self._consumer.stop()
            await self._producer.stop()
            log.info("rule_engine.consumer.stopped")

    async def _process(self, raw: Any) -> None:
        try:
            event = TelemetryMessage.model_validate(raw)
        except ValidationError:
            log.warning("rule_engine.invalid_message", raw=str(raw)[:200])
            return

        EVENTS_EVALUATED.inc()

        # 1 — Threshold evaluation
        thresholds = await self._threshold_cache.get_thresholds(event.area_id)
        params = list(event.measurements.as_param_dict().keys())
        existing: dict[str, list[float]] = {
            p: _update_history(event.sensor_id, p, event.measurements.as_param_dict()[p])
            for p in params
        }
        threshold_alerts = evaluate_thresholds(event, thresholds, existing)

        # 2 — Redundancy tracking
        redundancy_alerts = await self._redundancy_tracker.on_sensor_reading(
            sensor_id=event.sensor_id,
            area_id=event.area_id,
            parameters=params,
            status=event.status,
            ts_event=event.ts,
        )

        # 3 — Emit all alerts
        assert self._producer is not None  # noqa: S101
        for alert in threshold_alerts + redundancy_alerts:
            await _emit_alert(self._producer, alert)

        # 4 — Update sensor latest in Redis (for watchdog)
        await self._redis.set(
            f"sensor:{event.sensor_id}:latest",
            event.model_dump_json(),
            ex=settings.sensor_silence_timeout_s * 2,
        )
