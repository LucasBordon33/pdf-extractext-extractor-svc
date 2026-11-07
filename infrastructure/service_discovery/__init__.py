"""Service discovery compartido para los microservicios pdf-extractext.

Capa de **infraestructura** reutilizable que resuelve, para cualquier
microservicio del sistema:

- Registro automático en Consul al iniciar y desregistro al finalizar.
- Health checks HTTP consumidos por Consul (`GET /health`).
- Descubrimiento dinámico de instancias saludables por nombre de servicio.

Diseño:

- Clean Architecture: este paquete es implementación de infraestructura.
  `domain` y `application` solo conocen los contratos de `interfaces.py`
  (Protocol) y la configuración de `settings.py`; Consul es un detalle
  reemplazable (Eureka, etcd, ZooKeeper) sin tocar lógica de negocio.
- Distribución: el paquete se **vende** (copia) dentro de cada servicio
  bajo `infrastructure/service_discovery` porque cada repositorio tiene
  su propio build de Docker. La copia canónica vive aquí
  (`shared/service_discovery/src/service_discovery`) y se propaga con
  `sync_vendored.py`. Los imports internos son relativos para que la
  copia funcione en cualquier namespace.
- KISS/YAGNI: un agente Consul único, checks HTTP, sin Connect, sin
  sidecars, sin ACLs, sin multi-DC. Cliente Consul escrito con stdlib
  (`urllib`) para no añadir dependencias a los locks de los servicios.
"""

from .consul import ConsulAgentClient, ConsulError, ConsulServiceDiscovery, ConsulServiceRegistry
from .fastapi import add_health_route, attach_consul_lifespan
from .interfaces import IServiceDiscovery, IServiceRegistry
from .logging import JsonFormatter, configure_logging, get_logger
from .models import ServiceInstance
from .settings import ServiceDiscoverySettings, load_settings

__version__ = "0.1.0"

__all__ = [
    "ConsulAgentClient",
    "ConsulError",
    "ConsulServiceDiscovery",
    "ConsulServiceRegistry",
    "IServiceDiscovery",
    "IServiceRegistry",
    "JsonFormatter",
    "ServiceDiscoverySettings",
    "ServiceInstance",
    "add_health_route",
    "attach_consul_lifespan",
    "configure_logging",
    "get_logger",
    "load_settings",
]
