"""Prometheus metrics registry for rule-engine.

Centralised here so every module can import individual counters without risk of
re-registering the same metric (which prometheus_client rejects at runtime).
"""

from prometheus_client import Counter

EVENTS_EVALUATED = Counter(
    "rule_events_evaluated_total",
    "Total telemetry messages evaluated by the rule engine.",
)

ALERTS_EMITTED = Counter(
    "rule_alerts_emitted_total",
    "Total alerts emitted, partitioned by kind and severity.",
    ["kind", "severity"],
)

THRESHOLD_CACHE_HITS = Counter(
    "rule_threshold_cache_hits_total",
    "Threshold cache hits (geo-service request avoided).",
)

THRESHOLD_CACHE_MISSES = Counter(
    "rule_threshold_cache_misses_total",
    "Threshold cache misses (geo-service request made).",
)

REDUNDANCY_ESCALATIONS = Counter(
    "rule_redundancy_escalations_total",
    "Total redundancy escalations (operational count reached zero).",
)
