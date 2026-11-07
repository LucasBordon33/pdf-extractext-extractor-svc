"""Modelos del módulo de service discovery."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ServiceInstance:
    """Una instancia saludable de un microservicio.

    `host` es el nombre DNS resoluble dentro de la red Docker compartida
    (p. ej. `validator`, `store`), no una IP efímera: así el resultado del
    discovery es estable y legible en logs.
    """

    id: str
    name: str
    host: str
    port: int

    @property
    def base_url(self) -> str:
        """URL base HTTP para invocar a la instancia."""
        return f"http://{self.host}:{self.port}"
