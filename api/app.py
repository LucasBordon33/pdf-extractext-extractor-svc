"""Fabrica de la aplicacion FastAPI: ensambla handlers y routers."""

from fastapi import FastAPI

from api.error_handlers import register_exception_handlers
from api.v1.router import router as v1_router


def create_app() -> FastAPI:
    """Construye la app lista para servir o testear."""
    app = FastAPI(
        title="pdf-extractext-extractor-svc",
        version="0.1.0",
        description="Microservicio de extraccion de texto de documentos PDF",
    )
    register_exception_handlers(app)
    app.include_router(v1_router)
    return app
