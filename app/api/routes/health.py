"""Health and readiness endpoints."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from app.observability import collect_metrics_payload, metrics_content_type

health_router = APIRouter(tags=["health"])


@health_router.get("/healthz", summary="Liveness probe")
async def healthz() -> JSONResponse:
    """Liveness probe - returns 200 if service is up."""
    return JSONResponse(content={"status": "healthy", "service": "api-change-radar"})


@health_router.get("/readyz", summary="Readiness probe")
async def readyz() -> JSONResponse:
    """Readiness probe - returns 200 if service is ready to accept traffic."""
    return JSONResponse(content={"status": "ready", "service": "api-change-radar"})


@health_router.get("/metrics", summary="Prometheus metrics")
async def metrics() -> Response:
    """Expose Prometheus-compatible application metrics."""
    payload = collect_metrics_payload()
    return Response(content=payload, media_type=metrics_content_type())
