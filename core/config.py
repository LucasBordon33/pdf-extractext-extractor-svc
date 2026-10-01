"""Configuración central del servicio (Twelve-Factor II y III).

Toda la configuración proviene de variables de entorno — nunca del
código — con defaults razonables para que ``docker compose up --build``
funcione sin ``.env``. Esta capa solo define variables: ningún
comportamiento de negocio vive aqui.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LogFormat = Literal["json", "text"]
Environment = Literal["development", "testing", "production"]

DEFAULT_ALLOWED_MIME_TYPES = ["application/pdf"]


class Settings(BaseSettings):
    """Configuración del servicio, poblada desde variables de entorno.

    Referencias: ADR-TP-5 (concurrencia), ADR-TP-6/7 (admisión),
    Twelve-Factor III (port binding) y XI (logs a stdout).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Port binding (Twelve-Factor III) ---
    port: int = Field(
        default=8000, ge=1, le=65535, description="Puerto HTTP; Uvicorn lo lee."
    )
    host: str = Field(
        default="0.0.0.0", min_length=1, description="Interfaz de binding."
    )

    # --- Tamaño y timeouts ---
    max_upload_size_mb: int = Field(
        default=12,
        gt=0,
        description="Tope por request en MB; PDFs oficiales llegan a ~9 MB.",
    )
    extract_timeout_seconds: float = Field(
        default=25.0,
        gt=0,
        description="Deadline interno de extraccion, por debajo del timeout externo.",
    )
    admission_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        description=(
            "Espera maxima por un lugar de extraccion; agotada -> 429"
            " (ADR-TP-6/7). Debe quedar por debajo del timeout del cliente."
        ),
    )

    # --- Concurrencia (ADR-TP-5) ---
    uvicorn_workers: int = Field(
        default=2, ge=1, description="Procesos HTTP por replica."
    )
    extraction_pool_size: int = Field(
        default=2, ge=1, description="Tamaño del pool que ejecuta la extraccion."
    )
    max_concurrent_extractions: int = Field(
        default=4,
        ge=1,
        description="Lugares de extraccion por proceso; acota la admision y la cola.",
    )
    queue_max_size: int = Field(
        default=64,
        ge=1,
        description="Tope de trabajos pendientes en el pool; al superarlo -> 503.",
    )

    # --- Formatos ---
    allowed_mime_types: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_ALLOWED_MIME_TYPES),
        min_length=1,
        description="Tipos MIME aceptados para procesar.",
    )

    # --- Entorno y logs (Twelve-Factor XI: stdout) ---
    env: Environment = "development"
    log_level: LogLevel = "INFO"
    log_format: LogFormat = "json"

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
