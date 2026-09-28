"""Punto de entrada del microservicio.

Raiz de composicion: aqui (y solo aqui) se instancian los componentes
de infraestructura (PyTextExtractor) y se inyectan en el dominio
(DocumentService), que se registra en el contenedor para el router.
"""

import uvicorn
from fastapi import FastAPI

from adapters.extractors.pdf_extractor import PdfTextExtractor
from api.app import create_app
from api.dependencies import register
from core.config import get_settings
from domain.services.document_service import DocumentService

_HOST = "0.0.0.0"
_PORT = 8000


def build_document_service() -> DocumentService:
    """Wiring manual (DI): infraestructura concreta → dominio."""
    return DocumentService(PdfTextExtractor())


def create_application() -> FastAPI:
    """Ensambla la app FastAPI y registra las dependencias concretas."""
    app = create_app()
    register(DocumentService, build_document_service())
    return app


app = create_application()

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=_HOST,
        port=_PORT,
        log_level=get_settings().log_level.lower(),
    )
