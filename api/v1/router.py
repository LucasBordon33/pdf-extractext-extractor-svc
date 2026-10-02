"""Alias de compatibilidad: ``POST /api/v1/extract``.

El endpoint canónico del TP es ``POST /extract`` (raíz, ADR-TP-3). Este
router queda como alias deprecado que delega en la **misma** función,
para no romper al orquestador (MS1) mientras migra. Registrado solo
para compatibilidad: el wire contract ya no es base64.
"""

from fastapi import APIRouter

from api.extract.router import EXTRACT_RESPONSES, extract_document
from api.extract.schemas import ExtractResponse

router = APIRouter(
    prefix="/api/v1",
    tags=["extraction (legacy alias)"],
)

router.add_api_route(
    "/extract",
    endpoint=extract_document,
    methods=["POST"],
    response_model=ExtractResponse,
    status_code=200,
    summary="(deprecated) Usar POST /extract",
    description=(
        "Alias de compatibilidad del endpoint canónico POST /extract, "
        "que conserva la misma entrada (binario crudo o multipart) y la "
        "misma salida. Está deprecado: el canónico es POST /extract."
    ),
    deprecated=True,
    operation_id="extractDocumentAlias",
    responses=EXTRACT_RESPONSES,
)


@router.get(
    "/health",
    summary="Liveness (alias de GET /health)",
    deprecated=True,
)
def health() -> dict[str, str]:
    """Responde 200 mientras el proceso está vivo (alias de la raíz)."""
    return {"status": "ok"}