"""Prometheus counters for the ingestion-gateway.

Defined in a separate module so they can be imported by both ``gateway.py``
(which increments them) and ``api.py`` (which exposes ``/metrics``) without
creating circular dependencies.
"""

from prometheus_client import Counter

MESSAGES_RECEIVED: Counter = Counter(
    "gateway_messages_received_total",
    "Total MQTT messages received by the gateway",
)

MESSAGES_ACCEPTED: Counter = Counter(
    "gateway_messages_accepted_total",
    "Messages that passed validation and were forwarded to Kafka",
)

MESSAGES_REJECTED: Counter = Counter(
    "gateway_messages_rejected_total",
    "Messages rejected by the gateway, labelled by reason",
    ["reason"],
)

KAFKA_PRODUCE_ERRORS: Counter = Counter(
    "gateway_kafka_produce_errors_total",
    "Kafka produce calls that raised an exception",
)
