"""Fabrica de la aplicacion FastAPI: ensambla handlers y routers."""

from fastapi import FastAPI

from api.error_handlers import register_exception_handlers
from api.extract.router import router as extract_router
from api.middleware import RequestContextMiddleware, TimingMiddleware
from api.v1.router import router as v1_router
from infrastructure.consul import attach_consul


def create_app() -> FastAPI:
    app = FastAPI(
        title="pdf-extractext-extractor-svc",
        version="0.1.0",
        description="Microservicio de extraccion de texto de documentos PDF",
    )
    register_exception_handlers(app)
    # Orden importa: el último agregado es el más externo. El contexto
    # (request_id + línea por request) envuelve al de timing (métricas).
    app.add_middleware(TimingMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(extract_router)
    app.include_router(v1_router)
    # Service discovery: registro en Consul al iniciar, desregistro al
    # apagar (SIGINT/SIGTERM). Idempotente y best-effort: si Consul no
    # está disponible, el servicio sigue levantado.
    attach_consul(app)
    return app