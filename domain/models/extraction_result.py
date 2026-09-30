"""Modelo de dominio: resultado enriquecido de una extracción.

Inmutable por diseño: un resultado de extracción es un hecho que ya
ocurrió. Alimenta la respuesta HTTP (markdown, page_count), las
métricas (pages_processed, duration_ms) y el informe del TP.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractionResult:
    """Salida enriquecida del algoritmo de extracción.

    :param markdown: documento Markdown completo (texto plano es un
        subconjunto válido de Markdown).
    :param page_count: páginas totales del PDF.
    :param pages_processed: páginas que aportaron texto.
    :param duration_ms: tiempo del algoritmo puro, sin I/O HTTP.
    """

    markdown: str
    page_count: int
    pages_processed: int
    duration_ms: float

    def __post_init__(self) -> None:
        if self.page_count < 0:
            raise ValueError(f"page_count no puede ser negativo: {self.page_count}")
        if not 0 <= self.pages_processed <= self.page_count:
            raise ValueError(
                f"pages_processed ({self.pages_processed}) debe estar entre"
                f" 0 y page_count ({self.page_count})"
            )
        if self.duration_ms < 0:
            raise ValueError(f"duration_ms no puede ser negativo: {self.duration_ms}")
