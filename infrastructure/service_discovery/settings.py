"""Configuración del módulo vía variables de entorno (Twelve-Factor III).

Cada campo se lee de la env var en mayúsculas con el mismo nombre
(mapeo por defecto de pydantic-settings): `CONSUL_HOST`, `CONSUL_PORT`,
`SERVICE_NAME`, `SERVICE_ID`, `SERVICE_HOST`, `SERVICE_PORT`, ...
Nada queda hardcodeado en el código de los servicios.
"""

import os
import socket
from functools import lru_cache
from typing import Any, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


@lru_cache(maxsize=1)
def _detect_container_ip() -> str | None:
    """IP del contenedor en su red primaria (resolución del hostname).

    En un contenedor Docker el hostname resuelve a la IP propia del
    contenedor, lo que permite que el health check de Consul apunte a
    **la instancia exacta** y no a un alias DNS compartido por varias
    réplicas (bajo el alias, un contenedor muerto sigue "passing"
    porque otra réplica responde: registros huérfanos permanentes).
    """
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return None


class ServiceDiscoverySettings(BaseSettings):
    """Ajustes de service discovery leídos de env vars o de `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Interruptor general: permite correr el stack sin Consul ---
    service_discovery_enabled: bool = True

    # --- Agente Consul ---
    consul_host: str = "consul"
    consul_port: int = 8500
    consul_timeout: float = 2.0

    # --- Identidad del servicio local ---
    service_name: str = ""  # requerido para registrarse
    service_id: str = ""  # vacío -> f"{service_name}-{hostname}"
    service_host: str = ""  # si se define, fija la dirección registrada
    service_address_mode: Literal["ip", "dns"] = "ip"
    service_port: int = 8000
    service_health_path: str = "/health"

    # --- Health check registrado en Consul ---
    health_check_interval: str = "10s"
    health_check_timeout: str = "5s"
    deregister_critical_after: str = "60s"

    # --- Registro y descubrimiento ---
    register_retries: int = 1
    register_retry_backoff: float = 0.5
    discovery_cache_ttl: float = 5.0

    @property
    def consul_base_url(self) -> str:
        """URL base del HTTP API del agente de Consul."""
        return f"http://{self.consul_host}:{self.consul_port}"

    @property
    def resolved_service_address(self) -> str:
        """Dirección con la que se registra el servicio y se sondea.

        - `SERVICE_HOST` definido: gana la config explícita (modo dns).
        - Modo `ip` (default): IP del contenedor; el check apunta a la
          instancia exacta, enabling purga por TTL de instancias muertas
          y round-robin real entre réplicas.
        - Modo `dns` sin `SERVICE_HOST`: usa `service_name` (alias del
          compose; comportamiento histórico).
        """
        if self.service_host:
            return self.service_host
        if self.service_address_mode == "ip":
            detected = _detect_container_ip()
            if detected:
                return detected
        return self.service_name

    @property
    def health_check_url(self) -> str:
        """URL que Consul sondeará para validar la salud de la instancia."""
        return (
            f"http://{self.resolved_service_address}:{self.service_port}"
            f"{self.service_health_path}"
        )


def load_settings(**service_defaults: Any) -> ServiceDiscoverySettings:
    """Construye la configuración con precedencia `env var > default`.

    Los kwargs son los valores por defecto del servicio que consume el
    módulo (p. ej. `service_name="validator"`); solo se aplican cuando la
    env var correspondiente no está definida en el entorno o en `.env`.

    Ojo: una env var definida pero VACÍA (p. ej. `SERVICE_HOST=`) cuenta
    como definida; para el modo por IP deja `SERVICE_HOST` sin valor o
    sin declarar.
    """
    applied = {
        key: value
        for key, value in service_defaults.items()
        if os.getenv(key.upper()) is None
    }
    return ServiceDiscoverySettings(**applied)
