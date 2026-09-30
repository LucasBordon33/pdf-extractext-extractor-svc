"""Punto de entrada del microservicio.

Raiz de composicion: aqui (y solo aqui) se instancian los componentes
de infraestructura (PdfiumPdfToMarkdown) y se inyectan en el dominio
(DocumentService), que se registra en el contenedor para el router.

Port binding (Twelve-Factor III): Uvicorn lee HOST/PORT del entorno
via ``Settings`` â€” nada de puertos hardcodeados.
"""

import uvicorn
from fastapi import FastAPI

from adapters.extractors.pdf_extractor import PdfiumPdfToMarkdown
from api.app import create_app
from api.dependencies import register
from core.config import get_settings
from domain.services.document_service import DocumentService


def build_document_service() -> DocumentService:
    """Wiring manual (DI): infraestructura concreta â†’ dominio."""
    return DocumentService(PdfiumPdfToMarkdown())


def create_application() -> FastAPI:
    """Ensambla la app y registra las dependencias concretas."""
    app = create_app()
    register(DocumentService, build_document_service())
    return app


app = create_application()


def run() -> None:
    """Arranca el servidor con la configuraciÃ³n del entorno."""
    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        workers=settings.uvicorn_workers,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
