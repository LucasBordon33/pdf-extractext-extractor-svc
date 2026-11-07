"""Registro de servicios en Consul (implementación de `IServiceRegistry`)."""

import socket
import time
from typing import Any

from ..logging import get_logger
from ..settings import ServiceDiscoverySettings
from .client import ConsulAgentClient, ConsulError

logger = get_logger()

_PLATFORM_TAG = "pdf-extractext"


class ConsulServiceRegistry:
    """Registra/desregistra la instancia local vía el agente de Consul.

    - `register` es idempotente: el Agent API hace upsert por `ID`.
    - Best-effort: ante Consul caído devuelve `False` y el servicio sigue
      levantado; la ruta crítica nunca depende del plano de discovery.
    - Anti registros huérfanos: el health check lleva
      `DeregisterCriticalServiceAfter`, así Consul purga solo las
      instancias que murieron sin desregistrarse (SIGKILL, OOM).
    """

    def __init__(
        self, client: ConsulAgentClient, settings: ServiceDiscoverySettings
    ) -> None:
        self._client = client
        self._settings = settings

    @property
    def service_id(self) -> str:
        """ID único por contenedor: estable entre workers del mismo host."""
        if self._settings.service_id:
            return self._settings.service_id
        return f"{self._settings.service_name}-{socket.gethostname()}"

    def register(self) -> bool:
        """Registra el servicio con su health check HTTP. Idempotente."""
        settings = self._settings
        if not settings.service_discovery_enabled:
            logger.info("Service discovery deshabilitado", extra={"event": "register_skipped"})
            return False
        if not settings.service_name:
            logger.error(
                "SERVICE_NAME no definido: no se puede registrar en Consul",
                extra={"event": "register_invalid_config"},
            )
            return False

        payload = self._registration_payload()
        retries = max(settings.register_retries, 1)
        for attempt in range(1, retries + 1):
            try:
                self._client.register(payload)
            except ConsulError as exc:
                logger.warning(
                    "Fallo registrando servicio en Consul",
                    extra={
                        "event": "register_failed",
                        "service_id": self.service_id,
                        "service": settings.service_name,
                        "attempt": attempt,
                        "retries": retries,
                        "error": str(exc),
                    },
                )
                if attempt == retries:
                    return False
                time.sleep(settings.register_retry_backoff)
            else:
                logger.info(
                    "Servicio registrado en Consul",
                    extra={
                        "event": "service_registered",
                        "service_id": self.service_id,
                        "service": settings.service_name,
                        "address": settings.resolved_service_address,
                        "port": settings.service_port,
                        "health_check": settings.health_check_url,
                    },
                )
                return True
        return False

    def deregister(self) -> bool:
        """Desregistra el servicio. Idempotente y best-effort."""
        settings = self._settings
        if not settings.service_discovery_enabled or not settings.service_name:
            return False
        try:
            self._client.deregister(self.service_id)
        except ConsulError as exc:
            # Consul purgará el registro crítico tras
            # `deregister_critical_after`; no interrumpe el apagado.
            logger.warning(
                "Fallo desregistrando servicio en Consul",
                extra={
                    "event": "deregister_failed",
                    "service_id": self.service_id,
                    "error": str(exc),
                },
            )
            return False
        logger.info(
            "Servicio desregistrado de Consul",
            extra={"event": "service_deregistered", "service_id": self.service_id},
        )
        return True

    def _registration_payload(self) -> dict[str, Any]:
        settings = self._settings
        address = settings.resolved_service_address
        return {
            "ID": self.service_id,
            "Name": settings.service_name,
            "Address": address,
            "Port": settings.service_port,
            "Tags": [_PLATFORM_TAG],
            "Check": {
                "HTTP": settings.health_check_url,
                "Interval": settings.health_check_interval,
                "Timeout": settings.health_check_timeout,
                "DeregisterCriticalServiceAfter": settings.deregister_critical_after,
            },
        }
