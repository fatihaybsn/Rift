"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health_router
from app.api.v1 import v1_router
from app.core.config import Settings
from app.logging import configure_logging, get_logger
from app.middleware import RequestIdMiddleware
from app.observability import configure_tracing, instrument_fastapi

logger = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    # Load configuration
    settings = settings or Settings()

    # Configure structured logging before first startup log entry.
    configure_logging(log_level=settings.log_level)
    configure_tracing(
        service_name=settings.app_name,
        environment=settings.environment,
        exporter_mode=settings.tracing_exporter,
        otlp_endpoint=settings.otlp_endpoint,
    )

    logger.info(
        "creating_app",
        app_name=settings.app_name,
        environment=settings.environment,
        debug=settings.debug,
    )

    # Create FastAPI app
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str | None]:
        return {
            "status": "ok",
            "service": settings.app_name,
            "docs": app.docs_url,
        }

    # Add request correlation middleware
    app.add_middleware(
        RequestIdMiddleware,
        header_name=settings.request_id_header,
    )

    # Basic CORS (MVP keeps it permissive but simple)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(health_router)
    app.include_router(v1_router, prefix=settings.api_prefix)
    instrument_fastapi(app)

    logger.info("app_created", api_prefix=settings.api_prefix)
    return app


# Create the app instance for development servers (e.g., uvicorn app.main:app)
app = create_app()
