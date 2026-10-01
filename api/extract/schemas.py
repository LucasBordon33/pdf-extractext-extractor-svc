"""Schemas del contrato R2/R3 (ISSUE-011).

Frontera HTTP del endpoint canónico ``POST /extract``. A diferencia de
la API v1 heredada (base64), este contrato no define request models: la
entrada es binario crudo o multipart, resuelta por el lector de body
(ISSUE-013), nunca por Pydantic. Aquí sólo viven los modelos de salida.

Contrato exacto del TP:

- 200 OK ``application/json``: ``{"content": "<markdown>", "page_count": N}``
- errores: ``ErrorResponse{error_code, message, retry_after_seconds?}``
"""

from pydantic import BaseModel, ConfigDict, Field

# Ejemplo REAL copiado de una corrida: el layout del pipeline de
# ISSUE-006 (titulo en fuente grande + parrafo + item de lista en la
# misma pagina) se extrajo con PdfTextExtractor y dio exactamente este
# Markdown, determinista entre corridas (video:
# ``tests/pipeline/test_markdown_pipeline.py``).
_EXAMPLE_MARKDOWN = (
    "# Titulo Grande\n\n"
    "cuerpo normal\n\n"
    "- item uno"
)


class ExtractResponse(BaseModel):
    """Respuesta exitosa de la extracción (R3)."""

    content: str = Field(
        description="Texto extraído del documento convertido a Markdown (R2/R3).",
    )
    page_count: int = Field(
        ...,
        ge=1,
        description="Páginas totales del PDF procesado.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "content": _EXAMPLE_MARKDOWN,
                "page_count": 1,
            }
        }
    )


class ErrorResponse(BaseModel):
    """Cuerpo estándar de error para todos los fallos del endpoint."""

    error_code: str = Field(description="Código interno del error de dominio.")
    message: str = Field(description="Descripción legible del fallo.")
    retry_after_seconds: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Segundos sugeridos antes de reintentar. Sólo presente en "
            "429/503 (p. ej. el header ``Retry-After``)."
        ),
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error_code": "OVERLOADED",
                "message": "no se logro un lugar de extraccion en 10.0 segundos",
                "retry_after_seconds": 1,
            }
        }
    )