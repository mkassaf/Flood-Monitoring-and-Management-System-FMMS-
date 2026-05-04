"""Entry point for the sensor-simulator worker."""

from __future__ import annotations

import asyncio
import logging
import signal

import structlog
import uvicorn
from codecarbon import EmissionsTracker

from sensor_simulator.api import app
from sensor_simulator.config import settings
from sensor_simulator.simulator import Simulator

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        logging.getLevelName(settings.log_level.upper())
    ),
)

logger = structlog.get_logger(__name__)


async def run_metrics_server() -> None:
    config = uvicorn.Config(
        app,
        host="0.0.0.0",  # noqa: S104
        port=settings.metrics_port,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    loop = asyncio.get_running_loop()
    simulator = Simulator(settings)
    stop_event = asyncio.Event()

    def _handle_shutdown(sig: signal.Signals) -> None:
        logger.info("shutdown signal received", signal=sig.name)
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_shutdown, sig)

    tracker = EmissionsTracker(
        project_name="sensor-simulator",
        output_dir="/tmp",  # noqa: S108
        log_level="error",
        save_to_file=True,
    )
    tracker.start()
    metrics_task: asyncio.Task[None] | None = None

    try:
        await simulator.start()

        # Run the metrics server concurrently; stop when signalled.
        metrics_task = asyncio.create_task(run_metrics_server())

        logger.info(
            "sensor-simulator running",
            sensor_count=settings.sim_sensor_count,
            area_count=settings.sim_area_count,
        )

        await stop_event.wait()
    finally:
        logger.info("shutting down")
        if metrics_task is not None:
            metrics_task.cancel()
            try:
                await metrics_task
            except asyncio.CancelledError:
                pass
        await simulator.stop()
        tracker.stop()
        logger.info("shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
