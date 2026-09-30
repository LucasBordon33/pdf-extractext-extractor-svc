"""Contenedor manual de dependencias (DI).

``main.py`` registra aqui las instancias concretas (composition
root); los tests sobreescriben con ``app.dependency_overrides``.
Si nadie registro el servicio, se usa el wiring por defecto para
que la app siga siendo funcional de forma aislada.
"""

from functools import lru_cache

from adapters.extractors.pdf_extractor import PdfiumPdfToMarkdown
from domain.services.document_service import DocumentService

_registry: dict[type, object] = {}


def register(service_type: type, instance: object) -> None:
    """Registra una implementacion concreta para un tipo de servicio."""
    _registry[service_type] = instance


@lru_cache
def _default_document_service() -> DocumentService:
    """Wiring por defecto (defensivo) cuando no hay registro manual."""
    return DocumentService(PdfiumPdfToMarkdown())


def get_document_service() -> DocumentService:
    """Proveedor para FastAPI Depends: registro manual o wiring por defecto."""
    registered = _registry.get(DocumentService)
    if registered is not None:
        return registered
    return _default_document_service()
