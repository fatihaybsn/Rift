"""V1 API routes."""

from fastapi import APIRouter

from app.api.v1.reports import reports_router
from app.api.v1.runs import runs_router

# The router is mounted at the api_prefix defined in settings (default: "/api/v1").
# Routes defined here are relative to that prefix.
v1_router = APIRouter(tags=["v1"])


# Placeholder route to verify router is active
@v1_router.get("/", summary="API v1 root")
async def v1_root() -> dict:
    """Root endpoint for API v1."""
    return {"message": "API v1 is available"}


# Future route modules will be included here:
v1_router.include_router(runs_router)
v1_router.include_router(reports_router)
