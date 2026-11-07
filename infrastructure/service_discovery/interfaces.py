"""Contratos (ports) del módulo de service discovery.

Cualquier backend (Consul, Eureka, etcd, ZooKeeper) se integra
implementando estos Protocol: la lógica de aplicación depende de las
interfaces, nunca de Consul (Dependency Inversion + Open/Closed).
"""

from typing import Protocol, runtime_checkable

from .models import ServiceInstance


@runtime_checkable
class IServiceRegistry(Protocol):
    """Ciclo de vida de registro de la instancia local del servicio."""

    def register(self) -> bool:
        """Registra la instancia local. Idempotente y best-effort.

        Devuelve `True` si quedó registrado. Ante indisponibilidad del
        backend devuelve `False` sin lanzar: el servicio debe poder
        levantarse aunque el plano de discovery no esté disponible.
        """
        ...

    def deregister(self) -> bool:
        """Desregistra la instancia local. Idempotente y best-effort."""
        ...


@runtime_checkable
class IServiceDiscovery(Protocol):
    """Resolución dinámica de instancias saludables por nombre."""

    def discover(self, service_name: str) -> ServiceInstance | None:
        """Devuelve una instancia saludable (round-robin) o `None`.

        No lanza ante indisponibilidad del backend: devuelve `None` y el
        llamador aplica su fallback (p. ej. URL estática de config).
        """
        ...

    def discover_all(self, service_name: str) -> tuple[ServiceInstance, ...]:
        """Devuelve todas las instancias saludables conocidas."""
        ...
