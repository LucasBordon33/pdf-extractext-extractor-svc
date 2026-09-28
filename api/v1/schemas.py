"""Schemas de request/response de la API v1.

Esta es la frontera HTTP: aqui (y solo aqui) se resuelven los detalles
de transporte — base64, JSON, nombres de campos wire. El dominio recibe
``ExtractRequest.content`` en bytes crudos ya decodificados.
"""

import base64
import binascii
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator

_EXAMPLE_B64 = base64.b64encode(b"%PDF-1.4 contenido de ejemplo").decode()


def _decode_base64(payload: str) -> bytes:
    """Decodifica base64 estricto; lanza ValueError si es invalido."""
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("contenido base64 invalido") from error


class ExtractRequest(BaseModel):
    """Solicitud de extracción: documento codificado en base64."""

    model_config = {
        "json_schema_extra": {
            "example": {
                "filename": "reporte.pdf",
                "content_base64": _EXAMPLE_B64,
            }
        }
    }

    filename: str = Field(
        min_length=1, description="Nombre original del archivo."
    )
    content_base64: str = Field(
        min_length=1,
        description="Contenido del documento codificado en base64.",
    )
    content: bytes = Field(
        default=b"",
        exclude=True,
        repr=False,
        description="Contenido decodificado; interno, no serializable.",
    )

    @field_validator("content_base64")
    @classmethod
    def _reject_invalid_base64(cls, value: str) -> str:
        """Asegura que el payload es base64 valido (422 con loc del campo)."""
        _decode_base64(value)
        return value

    @model_validator(mode="after")
    def _decode_content(self) -> Self:
        """Almacena los bytes decodificados para el dominio."""
        self.content = _decode_base64(self.content_base64)
        return self


class ExtractResponse(BaseModel):
    """Respuesta exitosa de la extracción."""

    model_config = {
        "json_schema_extra": {
            "example": {"filename": "reporte.pdf", "text": "texto extraido"}
        }
    }

    filename: str = Field(description="Nombre del archivo procesado.")
    text: str = Field(description="Texto plano extraido del documento.")


class ErrorResponse(BaseModel):
    """Cuerpo estandar de error para todos los fallos de la API."""

    model_config = {
        "json_schema_extra": {
            "example": {
                "error_code": "CORRUPT_FILE",
                "message": "el PDF 'doc.pdf' esta dañado",
            }
        }
    }

    error_code: str = Field(description="Codigo interno del error de dominio.")
    message: str = Field(description="Descripcion legible del fallo.")
