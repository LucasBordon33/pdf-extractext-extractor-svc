"""Configuración central del servicio.

Carga variables de entorno con validaciones mediante pydantic-settings.
Esta capa no conoce FastAPI: cualquier consumidor (API, workers, CLI)
recibe una instancia de ``Settings`` inyectada.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
Environment = Literal["development", "testing", "production"]

DEFAULT_UPLOAD_SIZE_MB = 10
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_ALLOWED_MIME_TYPES = ["application/pdf"]


class Settings(BaseSettings):
    """Configuración del servicio, poblada desde variables de entorno."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    max_upload_size_mb: int = Field(
        default=DEFAULT_UPLOAD_SIZE_MB,
        gt=0,
        description="Tamaño máximo de archivo permitido, en MB.",
    )
    extract_timeout_seconds: int = Field(
        default=DEFAULT_TIMEOUT_SECONDS,
        gt=0,
        description="Tiempo máximo de espera para la extracción, en segundos.",
    )
    allowed_mime_types: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_ALLOWED_MIME_TYPES),
        min_length=1,
        description="Tipos MIME aceptados para procesar.",
    )
    env: Environment = "development"
    log_level: LogLevel = "INFO"

    @field_validator("allowed_mime_types", mode="before")
    @classmethod
    def _split_mime_types(cls, value: object) -> object:
        """Acepta lista JSON o cadena separada por comas desde el entorno."""
        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",")]
            if not parts or any(not part for part in parts):
                raise ValueError("ALLOWED_MIME_TYPES contiene entradas vacías")
            return parts
        return value

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    """Punto único de acceso a la configuración (singleton cacheado)."""
    return Settings()
