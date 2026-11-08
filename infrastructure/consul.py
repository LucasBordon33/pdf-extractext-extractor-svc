"""Integración Consul del microservicio extractor.

La implementación (cliente, registro, health, lifespan) vive en el
paquete compartido `infrastructure.service_discovery`; aquí solo se
liga la identidad del servicio con el entorno (composition root).

Nota multi-worker: con `UVICORN_WORKERS > 1` cada proceso ejecuta el
lifespan, pero todos comparten el mismo `SERVICE_ID` (nombre+hostname
del contenedor) y el Agent API hace upsert idempotente, por lo que el
contenedor queda registrado una única vez. El desregistro también es
idempotente; si un worker muere sin desregistrar, Consul purga el
registro tras `DEREGISTER_CRITICAL_AFTER`.
"""

from fastapi import FastAPI

from infrastructure.service_discovery import (
    ConsulAgentClient,
    ConsulServiceRegistry,
    attach_consul_lifespan,
    load_settings,
)

_SERVICE_DEFAULTS = {
    "service_name": "extractor",
    "service_port": 8002,
    "service_health_path": "/health",
}


def build_registry() -> ConsulServiceRegistry:
    """Registro de Consul configurado con la identidad del extractor."""
    settings = load_settings(**_SERVICE_DEFAULTS)
    return ConsulServiceRegistry(ConsulAgentClient(settings), settings)


def attach_consul(app: FastAPI) -> None:
    """Registro al iniciar y desregistro al apagar (SIGINT/SIGTERM)."""
    attach_consul_lifespan(app, build_registry())
