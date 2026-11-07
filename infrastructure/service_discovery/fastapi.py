"""Integración con FastAPI/ASGI: health check y ciclo de vida de registro.

Puntos de integración de la capa de presentación con la infraestructura
de discovery, sin filtrar Consul hacia `application`/`domain`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.types import ASGIApp

from .interfaces import IServiceRegistry
from .logging import get_logger

logger = get_logger()


def add_health_route(app: FastAPI, service_name: str, path: str = "/health") -> None:
    """Publica `GET {path}` con el contrato de health de la plataforma.

    Consul (y los HEALTHCHECK de Docker) sondean este endpoint para
    validar la disponibilidad de la instancia.
    """

    @app.get(path, include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "healthy", "service": service_name}


def attach_consul_lifespan(app: FastAPI, registry: IServiceRegistry) -> None:
    """Envuelve el lifespan existente de la app.

    - Al iniciar (tras el startup de la app): `registry.register()`.
    - Al apagar (shutdown del lifespan): `registry.deregister()`.

    Uvicorn traduce SIGINT/SIGTERM a un apagado gracioso que ejecuta el
    shutdown del lifespan, garantizando el desregistro. Ante SIGKILL u
    OOM, Consul purga el registro vía `DeregisterCriticalServiceAfter`.
    """
    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: ASGIApp) -> AsyncIterator[None]:
        async with previous_lifespan(application):
            registry.register()
            try:
                yield
            finally:
                registry.deregister()

    app.router.lifespan_context = lifespan
    logger.debug(
        "Lifespan de Consul acoplado a la app",
        extra={"event": "lifespan_attached"},
    )
