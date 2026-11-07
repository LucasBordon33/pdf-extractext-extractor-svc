"""Descubrimiento dinámico de servicios (implementación de `IServiceDiscovery`)."""

import time
from collections.abc import Callable

from ..logging import get_logger
from ..models import ServiceInstance
from ..settings import ServiceDiscoverySettings
from .client import ConsulAgentClient, ConsulError

logger = get_logger()


class ConsulServiceDiscovery:
    """Resuelve instancias saludables por nombre con caché TTL y round-robin.

    - Caché TTL (default 5 s): amortiza las consultas a Consul; el
      resultado negativo (Consul caído / sin instancias) también se
      cachea para no penalizar cada request ante una caída.
    - Round-robin: reparte las invocaciones entre las instancias
      registradas, base para escalar horizontalmente un servicio.
    - Degrade controlado: nunca lanza por indisponibilidad; devuelve
      `None`/vacío y el llamador aplica su fallback configurado.

    Nota de concurrencia: las operaciones sobre `dict` son atómicas bajo
    el GIL; en el peor caso dos hilos ejecutan la misma consulta, lo que
    es inocuo (consulta idempotente de lectura).
    """

    def __init__(
        self,
        client: ConsulAgentClient,
        settings: ServiceDiscoverySettings,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._settings = settings
        self._clock = clock
        self._cache: dict[str, tuple[float, tuple[ServiceInstance, ...]]] = {}
        self._cursor = 0

    def discover_all(self, service_name: str) -> tuple[ServiceInstance, ...]:
        """Todas las instancias saludables (con caché TTL)."""
        if not self._settings.service_discovery_enabled:
            return ()
        now = self._clock()
        cached = self._cache.get(service_name)
        if cached is not None and cached[0] > now:
            return cached[1]
        try:
            instances = self._client.healthy_instances(service_name)
        except ConsulError as exc:
            logger.warning(
                "Descubrimiento de servicio falló; se devuelve vacío",
                extra={
                    "event": "discovery_failed",
                    "service": service_name,
                    "error": str(exc),
                },
            )
            instances = ()
        ttl = self._settings.discovery_cache_ttl
        self._cache[service_name] = (now + ttl, instances)
        return instances

    def discover(self, service_name: str) -> ServiceInstance | None:
        """Una instancia saludable (round-robin) o `None` si no hay."""
        instances = self.discover_all(service_name)
        if not instances:
            return None
        instance = instances[self._cursor % len(instances)]
        self._cursor += 1
        return instance
