"""Integración Consul del Agent HTTP API.

Implementación concreta de `IServiceRegistry` e `IServiceDiscovery`
sobre el Agent API de Consul (`/v1/agent/service/*`, `/v1/health/*`).
"""

from .client import ConsulAgentClient, ConsulError
from .discovery import ConsulServiceDiscovery
from .registry import ConsulServiceRegistry

__all__ = [
    "ConsulAgentClient",
    "ConsulError",
    "ConsulServiceDiscovery",
    "ConsulServiceRegistry",
]
