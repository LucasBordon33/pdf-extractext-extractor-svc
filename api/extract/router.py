"""Router de la raíz: probes y métricas.

Solo HTTP y observabilidad. La extracción de PDFs vive exclusivamente
en ``api.v1.router`` (``POST /api/v1/extract``).
"""

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from api.dependencies import get_document_service
from api.metrics import METRICS
from domain.services.document_service import DocumentService

router = APIRouter(tags=["extraction (TP)"])


@router.get(
    "/health",
    summary="Liveness probe en la raíz",
    response_description="200 mientras el proceso está vivo",
)
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/ready",
    summary="Readiness probe en la raíz",
    response_description="200 si puede aceptar trabajo; 503 si está saturado",
)
def ready(
    document_service: DocumentService = Depends(get_document_service),
) -> JSONResponse:
    if document_service.can_accept_work():
        return JSONResponse({"status": "ok", "ready": True}, status_code=200)
    return JSONResponse(
        {"status": "saturated", "ready": False},
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@router.get(
    "/metrics",
    response_class=Response,
    tags=["observability"],
    summary="Métricas de texto Prometheus (ISSUE-014)",
    response_description="200 con contadores, gauges e histogramas",
)
def metrics() -> Response:
    return Response(content=METRICS.render(), media_type="text/plain; version=0.0.4")
