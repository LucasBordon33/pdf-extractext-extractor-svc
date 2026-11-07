"""Cliente HTTP mínimo del Agent API de Consul (solo stdlib).

Implementa exclusivamente los tres endpoints que el módulo necesita
(KISS/YAGNI): registro, desregistro y consulta de instancias saludables.

Se usa `urllib` en lugar de `httpx`/`requests` a propósito: el paquete
se vende dentro de cada microservicio y así **ningún servicio necesita
nuevas dependencias ni regenerar su lockfile**. El volumen de llamadas
es mínimo (registro + sondas de discovery cacheadas por TTL).
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..models import ServiceInstance
from ..settings import ServiceDiscoverySettings


class ConsulError(RuntimeError):
    """Fallo de comunicación con el agente de Consul."""


class ConsulAgentClient:
    """Cliente síncrono del HTTP API del agente de Consul."""

    def __init__(self, settings: ServiceDiscoverySettings) -> None:
        self._base_url = settings.consul_base_url.rstrip("/")
        self._timeout = settings.consul_timeout

    def register(self, payload: dict[str, Any]) -> None:
        """`PUT /v1/agent/service/register` (upsert idempotente)."""
        self._request("PUT", "/v1/agent/service/register", payload)

    def deregister(self, service_id: str) -> None:
        """`PUT /v1/agent/service/deregister/{id}` (no-op si no existe)."""
        path = f"/v1/agent/service/deregister/{urllib.parse.quote(service_id, safe='')}"
        self._request("PUT", path)

    def healthy_instances(self, service_name: str) -> tuple[ServiceInstance, ...]:
        """`GET /v1/health/service/{name}?passing=true` -> instancias OK."""
        path = f"/v1/health/service/{urllib.parse.quote(service_name, safe='')}?passing=true"
        entries = self._request("GET", path) or []
        return tuple(
            ServiceInstance(
                id=entry["Service"]["ID"],
                name=entry["Service"]["Service"],
                host=entry["Service"]["Address"] or entry["Node"]["Address"],
                port=int(entry["Service"]["Port"]),
            )
            for entry in entries
        )

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> Any:
        body = None
        headers: dict[str, str] = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self._base_url}{path}", data=body, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise ConsulError(f"Consul respondió {exc.code} para {method} {path}") from exc
        except OSError as exc:  # URLError, timeouts y errores de socket
            raise ConsulError(
                f"Consul inalcanzable en {self._base_url}: {exc}"
            ) from exc
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise ConsulError(f"Respuesta inválida de Consul para {method} {path}") from exc
