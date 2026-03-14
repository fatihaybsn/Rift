"""Health and readiness endpoints."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

health_router = APIRouter(tags=["health"])


@health_router.get("/healthz", summary="Liveness probe")
async def healthz() -> JSONResponse:
    """Liveness probe - returns 200 if service is up."""
    return JSONResponse(content={"status": "healthy", "service": "api-change-radar"})


@health_router.get("/readyz", summary="Readiness probe")
async def readyz() -> JSONResponse:
    """Readiness probe - returns 200 if service is ready to accept traffic."""
    return JSONResponse(content={"status": "ready", "service": "api-change-radar"})
