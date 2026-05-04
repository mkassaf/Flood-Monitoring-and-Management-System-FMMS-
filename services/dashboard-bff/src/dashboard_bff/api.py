"""REST + WebSocket API for the dashboard BFF."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Optional

import httpx
import structlog
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from dashboard_bff.auth import UserContext, get_current_user, get_current_user_ws
from dashboard_bff.config import settings
from dashboard_bff.db import (
    get_alerts_for_user,
    get_area_thresholds,
    get_areas_for_user,
    get_pool,
    get_telemetry,
)
from dashboard_bff.hot_state import get_area_summary

log = structlog.get_logger(__name__)

app = FastAPI(title="dashboard-bff", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/auth/login")
async def proxy_login(body: dict[str, Any]) -> Any:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.AUTH_SERVICE_URL}/auth/login",
            json=body,
            timeout=10.0,
        )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


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


@app.get("/dashboard/me")
async def me(user: UserContext = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "user_id": user.user_id,
        "email": user.email,
        "role": user.role,
        "jurisdiction": user.jurisdiction,
        "area_ids": user.area_ids,
    }


@app.get("/dashboard/areas")
async def list_areas(user: UserContext = Depends(get_current_user)) -> list[dict[str, Any]]:
    if not user.area_ids:
        return []
    pool = get_pool()
    areas = await get_areas_for_user(pool, user.area_ids)
    redis = app.state.redis  # type: ignore[attr-defined]
    enriched = []
    for area in areas:
        area_id = str(area["area_id"])
        summary = await get_area_summary(redis, area_id, [])
        enriched.append({**area, "live_summary": summary})
    return enriched


@app.get("/dashboard/areas/{area_id}")
async def area_detail(
    area_id: str,
    user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
    if area_id not in user.area_ids:
        raise HTTPException(status_code=403, detail="Area not in your jurisdiction")
    pool = get_pool()
    areas = await get_areas_for_user(pool, [area_id])
    if not areas:
        raise HTTPException(status_code=404, detail="Area not found")
    thresholds = await get_area_thresholds(pool, area_id)
    redis = app.state.redis  # type: ignore[attr-defined]
    summary = await get_area_summary(redis, area_id, [])
    return {**areas[0], "thresholds": thresholds, "live_summary": summary}


@app.get("/dashboard/areas/{area_id}/telemetry")
async def area_telemetry(
    area_id: str,
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    limit: int = Query(1000, ge=1, le=5000),
    user: UserContext = Depends(get_current_user),
) -> list[dict[str, Any]]:
    if area_id not in user.area_ids:
        raise HTTPException(status_code=403, detail="Area not in your jurisdiction")
    pool = get_pool()
    return await get_telemetry(pool, [area_id], start, end, limit)


@app.get("/dashboard/alerts")
async def list_alerts(
    severity: Optional[str] = Query(None, pattern="^(low|medium|high)$"),
    acknowledged: Optional[bool] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: UserContext = Depends(get_current_user),
) -> list[dict[str, Any]]:
    pool = get_pool()
    return await get_alerts_for_user(pool, user.area_ids, severity, acknowledged, limit, offset)


@app.post("/dashboard/alerts/{alert_id}/acknowledge", status_code=204)
async def ack_alert(
    alert_id: str,
    reason: str = Query(..., min_length=1),
    user: UserContext = Depends(get_current_user),
) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"http://alert-service:8000/alerts/{alert_id}/acknowledge",
            json={"reason": reason},
            headers={"X-User-Id": user.user_id},
            timeout=5.0,
        )
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Alert not found or already acknowledged")
    if resp.status_code != 204:
        raise HTTPException(status_code=502, detail="Alert service error")


@app.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket, token: str = Query(...)) -> None:
    pool = get_pool()
    try:
        user = await get_current_user_ws(token, pool)
    except ValueError as exc:
        await websocket.close(code=4001, reason=str(exc))
        return

    await websocket.accept()
    log.info("ws.connected", user_id=user.user_id, area_count=len(user.area_ids))

    redis = app.state.redis  # type: ignore[attr-defined]
    pubsub = redis.pubsub()

    channels = [f"alerts:area:{aid}" for aid in user.area_ids]
    if user.role == "regional_manager":
        channels.append("alerts:high_severity")

    if not channels:
        await websocket.close(code=4003, reason="No areas in jurisdiction")
        return

    await pubsub.subscribe(*channels)
    heartbeat_task: asyncio.Task[None] | None = None
    try:
        heartbeat_task = asyncio.create_task(_ws_heartbeat(websocket))
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    await websocket.send_text(message["data"])
                except WebSocketDisconnect:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
        await pubsub.unsubscribe(*channels)
        await pubsub.aclose()
        log.info("ws.disconnected", user_id=user.user_id)


async def _ws_heartbeat(websocket: WebSocket) -> None:
    while True:
        await asyncio.sleep(settings.WS_HEARTBEAT_INTERVAL_S)
        try:
            await websocket.send_text(json.dumps({"type": "heartbeat"}))
        except Exception:
            break
