

import uvicorn

from api.app import create_app
from api.dependencies import build_document_service, register
from core.config import get_settings
from core.logging import configure_logging
from domain.services.document_service import DocumentService
from infrastructure.service_discovery import (
    configure_logging as configure_discovery_logging,
)


def create_application():
    """Ensambla la app y registra las dependencias concretas.

    ``configure_logging`` es idempotente y va antes de ``create_app``:
    el middleware del ISSUE-014 ya emite una línea JSON por request.
    """
    settings = get_settings()
    configure_logging(
        level=settings.log_level, fmt=settings.log_format
    )
    # Logging propio para los eventos de service discovery (INC-7).
    configure_discovery_logging(settings.log_level)
    app = create_app()
    register(DocumentService, build_document_service())
    return app


def run() -> None:

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        workers=settings.uvicorn_workers,
        log_level=settings.log_level.lower(),
        limit_concurrency=settings.http_limit_concurrency,
        timeout_keep_alive=int(settings.http_timeout_keep_alive),
        access_log=settings.http_access_log,
    )


app = create_application()


if __name__ == "__main__":
    run()