"""Metrics + health surface for the sensor-simulator worker."""

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from sensor_simulator.config import settings

app = FastAPI(title="sensor-simulator", version="0.1.0")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": settings.service_name}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    return {"status": "ready", "service": settings.service_name}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
