

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

    # API
    api_prefix: str = Field(default="/api/v1", description="API route prefix")

    # Database
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/api_change_radar",
        description="SQLAlchemy database URL",
    )
    database_echo: bool = Field(default=False, description="Enable SQLAlchemy SQL echo logging")

    # Request correlation
    request_id_header: str = Field(default="X-Request-ID", description="Header name for request ID")


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
