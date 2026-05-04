"""REST API for alert-service."""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from alert_service.config import settings
from alert_service.db import acknowledge_alert, get_alert_by_id, get_alerts, get_pool
from alert_service.models import AcknowledgeRequest, AlertSummary

log = structlog.get_logger(__name__)

app = FastAPI(title="alert-service", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": settings.service_name}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return {"status": "ready", "service": settings.service_name}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/alerts", response_model=list[AlertSummary])
async def list_alerts(
    area_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None, pattern="^(low|medium|high)$"),
    acknowledged: Optional[bool] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[dict]:  # type: ignore[return]
    pool = get_pool()
    area_ids = [area_id] if area_id else None
    return await get_alerts(pool, area_ids, severity, acknowledged, limit, offset)  # type: ignore[return-value]


@app.get("/alerts/{alert_id}")
async def get_alert(alert_id: str) -> dict:  # type: ignore[return]
    pool = get_pool()
    row = await get_alert_by_id(pool, alert_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return row  # type: ignore[return-value]


@app.post("/alerts/{alert_id}/acknowledge", status_code=status.HTTP_204_NO_CONTENT)
async def ack_alert(
    alert_id: str,
    body: AcknowledgeRequest,
    x_user_id: str = Header(..., alias="X-User-Id"),
) -> None:
    pool = get_pool()
    updated = await acknowledge_alert(pool, alert_id, x_user_id, body.reason)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alert not found or already acknowledged",
        )
    log.info("alert.acknowledged", alert_id=alert_id, user_id=x_user_id)
