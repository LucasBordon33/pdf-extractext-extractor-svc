"""Raíz de composición (composition root).

Único punto del sistema donde se cablean adaptadores concretos con el
dominio. Cambiar PyPDF2 por otro motor toca solo este archivo.
"""

from functools import lru_cache

from adapters.extractors.pdf_extractor import PdfTextExtractor
from domain.services.document_service import DocumentService


@lru_cache
def get_document_service() -> DocumentService:
    """Construye (y cachea) el servicio de extracción inyectable."""
    return DocumentService(PdfTextExtractor())
