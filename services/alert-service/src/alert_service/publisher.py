"""Redis Pub/Sub publisher for real-time alert fan-out."""

from __future__ import annotations

import structlog
from prometheus_client import Counter
from redis.asyncio import Redis

from alert_service.models import Alert

log = structlog.get_logger(__name__)

# ─── Metrics ──────────────────────────────────────────────────────────────────

publish_errors_total = Counter(
    "alert_service_publish_errors_total",
    "Number of Redis publish failures.",
)


class AlertPublisher:
    """Publishes alerts to Redis Pub/Sub channels for dashboard-bff fan-out."""

    def __init__(self, redis_client: Redis) -> None:  # type: ignore[type-arg]
        self._redis = redis_client

    async def publish(self, alert: Alert) -> None:
        """Publish the alert to its area channel and, if high severity, the global channel.

        Errors are logged and counted but never re-raised — the alert path must not
        block on a slow downstream (architecture.md NFR alert-path constraint).
        """
        payload = alert.model_dump_json()
        area_channel = f"alerts:area:{alert.area_id}"

        try:
            await self._redis.publish(area_channel, payload)
            log.debug(
                "publisher.published",
                alert_id=alert.alert_id,
                channel=area_channel,
            )
        except Exception:
            publish_errors_total.inc()
            log.error(
                "publisher.area_channel_failed",
                alert_id=alert.alert_id,
                channel=area_channel,
                exc_info=True,
            )

        if alert.severity == "high":
            try:
                await self._redis.publish("alerts:high_severity", payload)
                log.debug(
                    "publisher.published_high_severity",
                    alert_id=alert.alert_id,
                )
            except Exception:
                publish_errors_total.inc()
                log.error(
                    "publisher.high_severity_channel_failed",
                    alert_id=alert.alert_id,
                    exc_info=True,
                )
