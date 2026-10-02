"""Punto de entrada del microservicio.

Raiz de composicion: el wiring concreto (PdfTextExtractor,
ThreadPoolExtractionPool, limites) vive en ``api.dependencies`` y se
inyecta en el dominio (DocumentService) con los limites del entorno.

Port binding (Twelve-Factor III): Uvicorn lee HOST/PORT del entorno
via ``Settings`` — nada de puertos hardcodeados.
"""

import uvicorn

from api.app import create_app
from api.dependencies import build_document_service, register
from core.config import get_settings
from core.logging import configure_logging
from domain.services.document_service import DocumentService


def create_application():
    """Ensambla la app y registra las dependencias concretas.

    ``configure_logging`` es idempotente y va antes de ``create_app``:
    el middleware del ISSUE-014 ya emite una línea JSON por request.
    """
    configure_logging(
        level=get_settings().log_level, fmt=get_settings().log_format
    )
    app = create_app()
    register(DocumentService, build_document_service())
    return app


def run() -> None:
    """Arranca el servidor con la configuración del entorno.

    ``limit_concurrency`` es **por proceso**: con ``UVICORN_WORKERS``
    workers el tope efectivo es ``workers x http_limit_concurrency``.
    Uvicorn responde 503 en texto plano, sin ``Retry-After``, y cierra
    la conexión, así que ese cuerpo NO es un ``ErrorResponse``.

    El access log de Uvicorn se deja activo a propósito: complementa la
    línea JSON que ya emite el middleware del ISSUE-014 con la info de
    red (addr/proto) que esa línea no lleva.
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


app = create_application()


if __name__ == "__main__":
    run()