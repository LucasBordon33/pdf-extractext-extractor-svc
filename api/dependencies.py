"""Raíz de composición (composition root).

Único punto del sistema donde se cablean adaptadores concretos con el
dominio: extractor (pdfium), pool de concurrencia (threads + semáforo)
y límites operativos desde la configuración del entorno.
"""

from functools import lru_cache

from adapters.concurrency.thread_pool import ThreadPoolExtractionPool
from adapters.extractors.pdf_extractor import PdfTextExtractor
from api.metrics import METRICS
from core.config import get_settings
from domain.services.document_service import DocumentService

_registry: dict[type, object] = {}


def register(service_type: type, instance: object) -> None:
    """Registra una implementacion concreta para un tipo de servicio."""
    _registry[service_type] = instance


def build_document_service() -> DocumentService:
    """Wiring con los knobs del entorno (unica definicion del grafo).

    ``main.py`` y el composition root usan esta funcion; no hay dos
    definiciones del grafo que puedan divergir.
    """
    settings = get_settings()
    pool = ThreadPoolExtractionPool(
        max_workers=settings.extraction_pool_size,
        max_concurrent=settings.max_concurrent_extractions,
        max_queue_depth=settings.queue_max_size,
    )
    return DocumentService(
        PdfTextExtractor(),
        pool,
        max_upload_size_mb=settings.max_upload_size_mb,
        extract_timeout_seconds=settings.extract_timeout_seconds,
        max_concurrent_extractions=settings.max_concurrent_extractions,
        admission_timeout_seconds=settings.admission_timeout_seconds,
        admission_observer=METRICS.record_admission_wait,
    )


@lru_cache
def _default_document_service() -> DocumentService:
    """Wiring por defecto (defensivo) cuando no hay registro manual."""
    return build_document_service()


def get_document_service() -> DocumentService:
    """Proveedor para FastAPI Depends: registro manual o wiring por defecto."""
    registered = _registry.get(DocumentService)
    if isinstance(registered, DocumentService):
        return registered
    return _default_document_service()
