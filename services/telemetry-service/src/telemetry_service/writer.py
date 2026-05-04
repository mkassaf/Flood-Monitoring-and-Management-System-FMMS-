"""Batched TimescaleDB writer.

Accumulates TelemetryMessage objects in an in-memory buffer and bulk-inserts
them via the PostgreSQL UNNEST trick every BATCH_INTERVAL_S seconds or whenever
the buffer reaches BATCH_MAX_SIZE items (NFR-07).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import asyncpg
import structlog
from prometheus_client import Counter, Histogram

from telemetry_service.models import TelemetryMessage

log = structlog.get_logger(__name__)

# ─── Prometheus metrics ────────────────────────────────────────────────────────

rows_written_total = Counter(
    "telemetry_rows_written_total",
    "Total rows successfully written to tsdb.telemetry",
)

batch_size_histogram = Histogram(
    "telemetry_batch_size_histogram",
    "Number of rows per flush batch",
    buckets=[1, 10, 50, 100, 250, 500, 750, 1000, 1500, 2000],
)

write_latency_seconds = Histogram(
    "telemetry_write_latency_seconds",
    "Time spent executing the bulk INSERT into tsdb.telemetry",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0],
)

write_errors_total = Counter(
    "telemetry_write_errors_total",
    "Number of errors during bulk INSERT",
)

# ─── INSERT statement ──────────────────────────────────────────────────────────

_INSERT_SQL = """
INSERT INTO tsdb.telemetry (
    ts, sensor_id, area_id, status, mode,
    water_level_m, river_flow_velocity_m_s, rainfall_mm_h,
    soil_saturation_pct, wind_speed_m_s, wind_direction_deg, ingested_at
)
SELECT * FROM UNNEST(
    $1::timestamptz[],
    $2::uuid[],
    $3::uuid[],
    $4::int2[],
    $5::text[],
    $6::float8[],
    $7::float8[],
    $8::float8[],
    $9::float8[],
    $10::float8[],
    $11::float8[],
    $12::timestamptz[]
)
ON CONFLICT DO NOTHING
"""


def _parse_dt(value: str) -> datetime:
    """Parse an ISO 8601 UTC string to a timezone-aware datetime."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class BatchWriter:
    """Accumulate telemetry messages and bulk-flush to TimescaleDB."""

    def __init__(
        self,
        pool: asyncpg.Pool[asyncpg.Record],
        batch_interval_s: float,
        batch_max_size: int,
    ) -> None:
        self._pool = pool
        self._batch_interval_s = batch_interval_s
        self._batch_max_size = batch_max_size
        self._buffer: list[TelemetryMessage] = []
        self._flush_event = asyncio.Event()

    async def enqueue(self, msg: TelemetryMessage) -> None:
        """Add a message to the in-memory buffer.

        Signals the flush loop immediately when the buffer reaches
        BATCH_MAX_SIZE to bound latency under burst load.
        """
        self._buffer.append(msg)
        if len(self._buffer) >= self._batch_max_size:
            self._flush_event.set()

    async def run(self) -> None:
        """Main flush loop — runs for the lifetime of the process."""
        log.info("batch_writer.started", interval_s=self._batch_interval_s)
        while True:
            try:
                await asyncio.wait_for(
                    self._flush_event.wait(),
                    timeout=self._batch_interval_s,
                )
            except asyncio.TimeoutError:
                pass  # normal: interval elapsed, time to flush
            self._flush_event.clear()
            await self._flush()

    async def _flush(self) -> None:
        """Extract the current buffer and bulk-insert into tsdb.telemetry."""
        if not self._buffer:
            return

        batch, self._buffer = self._buffer, []
        n = len(batch)
        batch_size_histogram.observe(n)

        # Build parallel arrays for UNNEST — avoids Python-level loop overhead
        ts_arr: list[datetime] = []
        sensor_id_arr: list[str] = []
        area_id_arr: list[str] = []
        status_arr: list[int] = []
        mode_arr: list[str] = []
        water_level_arr: list[float | None] = []
        flow_velocity_arr: list[float | None] = []
        rainfall_arr: list[float | None] = []
        soil_sat_arr: list[float | None] = []
        wind_speed_arr: list[float | None] = []
        wind_dir_arr: list[float | None] = []
        ingested_at_arr: list[datetime] = []

        for msg in batch:
            ts_arr.append(_parse_dt(msg.ts))
            sensor_id_arr.append(msg.sensor_id)
            area_id_arr.append(msg.area_id)
            status_arr.append(msg.status)
            mode_arr.append(msg.mode)
            m = msg.measurements
            water_level_arr.append(m.water_level_m)
            flow_velocity_arr.append(m.river_flow_velocity_m_s)
            rainfall_arr.append(m.rainfall_mm_h)
            soil_sat_arr.append(m.soil_saturation_pct)
            wind_speed_arr.append(m.wind_speed_m_s)
            wind_dir_arr.append(m.wind_direction_deg)
            ingested_at_arr.append(_parse_dt(msg.ingested_at))

        try:
            with write_latency_seconds.time():
                async with self._pool.acquire() as conn:
                    await conn.execute(
                        _INSERT_SQL,
                        ts_arr,
                        sensor_id_arr,
                        area_id_arr,
                        status_arr,
                        mode_arr,
                        water_level_arr,
                        flow_velocity_arr,
                        rainfall_arr,
                        soil_sat_arr,
                        wind_speed_arr,
                        wind_dir_arr,
                        ingested_at_arr,
                    )
            rows_written_total.inc(n)
            log.info("batch_writer.flushed", rows=n)
        except Exception:
            write_errors_total.inc()
            # Re-buffer the batch so messages are not silently dropped.
            # Prepend so ordering is preserved if new messages arrived during flush.
            self._buffer = batch + self._buffer
            log.exception("batch_writer.flush_error", batch_size=n)
            raise
