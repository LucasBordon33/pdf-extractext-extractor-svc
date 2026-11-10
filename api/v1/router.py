"""Endpoint primario: ``POST /api/v1/extract``.

Solo HTTP, validación de frontera y DI: sin lógica de extracción ni de
Markdown. La entrada se resuelve leyendo el body streaming
(``body_reader``) en el modo que dicte el ``Content-Type``; el servicio
de dominio hace el resto. Marca las cabeceras de diagnóstico
``X-Filename`` (ADR-TP-4) y ``X-Replica``.

Este router expone el único contrato de extracción del servicio. El
antiguo ``POST /extract`` en la raíz fue eliminado; los consumidores
deben apuntar a ``/api/v1/extract``.
"""

import os
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status

from api.body_reader import read_body, read_multipart, sanitize_filename
from api.dependencies import get_document_service
from api.extract.schemas import ErrorResponse, ExtractResponse
from api.metrics import METRICS
from core.config import get_settings
from core.constants import BYTES_PER_MB, DEFAULT_FILENAME
from core.exceptions import NotAPdfError
from domain.services.document_service import DocumentService

router = APIRouter(
    prefix="/api/v1",
    tags=["extraction"],
)

_PDF_MAGIC = b"%PDF-"
_REPLICA_ID = os.environ.get("HOSTNAME") or "unknown"

EXTRACT_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_400_BAD_REQUEST: {
        "model": ErrorResponse,
        "description": "Body vacío o PDF corrupto/cifrado",
    },
    status.HTTP_413_CONTENT_TOO_LARGE: {
        "model": ErrorResponse,
        "description": "El archivo supera el tamaño máximo permitido",
    },
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {
        "model": ErrorResponse,
        "description": "El body no empieza con %PDF-",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": "Multipart sin campo 'file' o extracción vacía",
    },
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": ErrorResponse,
        "description": "No se logró un lugar de extracción a tiempo",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponse,
        "description": "Cola de extracción o deadline agotados",
    },
    status.HTTP_500_INTERNAL_SERVER_ERROR: {
        "model": ErrorResponse,
        "description": "Error interno inesperado",
    },
}


@dataclass(frozen=True)
class ExtractInput:

    content: bytes
    filename: str


async def read_extract_input(request: Request) -> ExtractInput:
    max_bytes = get_settings().max_upload_size_mb * BYTES_PER_MB
    content_type = (request.headers.get("content-type") or "").split(";", 1)[0]
    if content_type.strip().lower() == "multipart/form-data":
        content, original = await read_multipart(request, max_bytes)
    else:
        content = await read_body(request, max_bytes)
        original = DEFAULT_FILENAME
    if not content.startswith(_PDF_MAGIC):
        raise NotAPdfError(
            "el body no empieza con el magic number '%PDF-': no es un PDF"
        )
    return ExtractInput(content=content, filename=sanitize_filename(original))


@router.post(
    "/extract",
    response_model=ExtractResponse,
    status_code=status.HTTP_200_OK,
    summary="Extrae el texto de un PDF a Markdown",
    response_description="Extracción exitosa",
    responses=EXTRACT_RESPONSES,
)
def extract_document(
    response: Response,
    input_data: ExtractInput = Depends(read_extract_input),
    document_service: DocumentService = Depends(get_document_service),
) -> ExtractResponse:
    METRICS.record_bytes(len(input_data.content))
    METRICS.extractions_in_flight.inc()
    try:
        result = document_service.extract(
            content=input_data.content, filename=input_data.filename
        )
        METRICS.record_pages(result.page_count)
        response.headers["X-Filename"] = input_data.filename
        response.headers["X-Replica"] = _REPLICA_ID
        return ExtractResponse(content=result.markdown, page_count=result.page_count)
    finally:
        METRICS.extractions_in_flight.dec()


@router.get(
    "/health",
    summary="Liveness (alias de GET /health)",
    deprecated=True,
)

def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", summary="Readiness probe para Docker")
def readiness_check() -> dict[str, str]:
    return {"status": "ready"}
