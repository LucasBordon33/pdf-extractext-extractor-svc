"""Punto de entrada del microservicio.

Raiz de composicion: aqui (y solo aqui) se instancian los componentes
de infraestructura (PdfTextExtractor, ThreadPoolExtractionPool) y se
inyectan en el dominio (DocumentService) con los limites del entorno.

Port binding (Twelve-Factor III): Uvicorn lee HOST/PORT del entorno
via ``Settings`` — nada de puertos hardcodeados.
"""

import uvicorn
from fastapi import FastAPI

from adapters.concurrency.thread_pool import ThreadPoolExtractionPool
from adapters.extractors.pdf_extractor import PdfTextExtractor
from api.app import create_app
from api.dependencies import register
from core.config import get_settings
from domain.services.document_service import DocumentService


def build_document_service() -> DocumentService:
    """Wiring manual (DI): infraestructura concreta → dominio."""
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
    )


def create_application() -> FastAPI:
    """Ensambla la app y registra las dependencias concretas."""
    app = create_app()
    register(DocumentService, build_document_service())
    return app


app = create_application()


def run() -> None:
    """Arranca el servidor con la configuración del entorno.

    ``limit_concurrency`` es **por proceso**: con ``UVICORN_WORKERS``
    workers el tope efectivo es ``workers x http_limit_concurrency``.
    Uvicorn responde 503 en texto plano, sin ``Retry-After``, y cierra
    la conexión, así que ese cuerpo NO es un ``ErrorResponse``.

    El access log se deja activo a propósito: hoy es la única línea por
    request que emite el servicio. Desactivarlo antes del middleware de
    ISSUE-014 dejaría el runtime sin observabilidad.
    """
    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        workers=settings.uvicorn_workers,
        log_level=settings.log_level.lower(),
        limit_concurrency=settings.http_limit_concurrency,
        timeout_keep_alive=settings.http_timeout_keep_alive,
        access_log=settings.http_access_log,
    )


if __name__ == "__main__":
    run()
