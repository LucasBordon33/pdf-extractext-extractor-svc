"""Router de la API v1: endpoint de extracción.

Endpoint deliberadamente delgado: traduce HTTP → llamada al servicio
de dominio. Sin validación de formato, tamaño ni permisos (esa es
responsabilidad del orquestador); el base64 ya fue decodificado por
``ExtractRequest`` en la frontera.
"""

from fastapi import APIRouter, Depends, status

from api.dependencies import get_document_service
from api.v1.schemas import ErrorResponse, ExtractRequest, ExtractResponse
from domain.services.document_service import DocumentService

router = APIRouter(prefix="/api/v1", tags=["extraction"])


@router.get(
    "/health",
    summary="Liveness probe para orquestadores y healthchecks",
)
def health() -> dict[str, str]:
    """Responde 200 mientras el servicio esta vivo."""
    return {"status": "ok"}


@router.post(
    "/extract",
    response_model=ExtractResponse,
    status_code=status.HTTP_200_OK,
    summary="Extrae el texto plano de un documento PDF",
    response_description="Texto extraido correctamente",
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "El archivo esta corrupto o cifrado",
        },
        status.HTTP_413_CONTENT_TOO_LARGE: {
            "model": ErrorResponse,
            "description": "El archivo supera el tamaño maximo permitido",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "Payload invalido o extraccion vacia",
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "model": ErrorResponse,
            "description": "No se logro un lugar de extraccion a tiempo; "
            "reintentar tras Retry-After",
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": "Cola de extraccion o deadline agotados; "
            "reintentar tras Retry-After",
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponse,
            "description": "Error interno inesperado",
        },
    },
)
def extract_text_from_document(
    req: ExtractRequest,
    document_service: DocumentService = Depends(get_document_service),
) -> ExtractResponse:
    """Recibe bytes ya decodificados y delega en el dominio."""
    result = document_service.extract(content=req.content, filename=req.filename)
    return ExtractResponse(
        filename=req.filename, markdown=result.markdown, page_count=result.page_count
    )
