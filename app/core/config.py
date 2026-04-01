from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    # Settings sınıfı tanımlıyor ve ayarları environment / .env üzerinden okuyacak şekilde kuruyor.

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "api-change-radar"
    environment: Environment = Field(default="development", description="Runtime environment")
    debug: bool = Field(default=False, description="Enable debug mode")
    docs_enabled: bool = Field(
        default=True,
        description="Expose OpenAPI docs and schema routes",
    )

    # Logging
    log_level: LogLevel = Field(default="INFO", description="Structured log level")

    # Tracing
    tracing_exporter: str = Field(
        default="none",
        description="Tracing exporter mode: none, console, or otlp",
    )
    otlp_endpoint: str | None = Field(
        default=None,
        description="Optional OTLP HTTP endpoint (used when tracing_exporter=otlp).",
    )

    # API
    api_prefix: str = Field(default="/api/v1", description="API route prefix")

    # Database
    database_url: str = Field(
        default="postgresql+psycopg://localhost:5432/api_change_radar",
        description="SQLAlchemy database URL",
    )
    database_echo: bool = Field(default=False, description="Enable SQLAlchemy SQL echo logging")

    # Request correlation
    request_id_header: str = Field(default="X-Request-ID", description="Header name for request ID")

    # Optional AI changelog interpretation
    llm_changelog_interpreter_enabled: bool = Field(
        default=False,
        description=(
            "Enable optional LLM changelog interpretation. Deterministic findings "
            "and run lifecycle state remain authoritative."
        ),
    )
    llm_low_confidence_threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Confidence threshold below which AI output requires manual review.",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
