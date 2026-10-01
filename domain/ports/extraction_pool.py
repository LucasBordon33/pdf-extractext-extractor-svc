"""Puerto de dominio: pool de extracción (ISSUE-008).

El dominio delega aquí el trabajo pesado: nunca lo ejecuta en el hilo
del request. Las implementaciones gestionan la concurrencia con
semáforo y garantizan la liberación del slot en ``finally``.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from concurrent.futures import Future

from domain.models.extraction_result import ExtractionResult


class ExtractionPool(ABC):
    """Ejecuta trabajos de extracción fuera del hilo del llamador."""

    @abstractmethod
    def submit(
        self, work: Callable[[], ExtractionResult]
    ) -> Future[ExtractionResult]:
        """Entrega un futuro con el resultado del trabajo.

        Contrato:

        - El trabajo corre fuera del hilo del request.
        - ``Future.result(timeout)`` respeta deadlines: al vencer lanza
          ``TimeoutError`` y el llamador puede cancelar con ``cancel()``.
        - ``cancel()`` es best-effort; el slot del semáforo se libera
          en ``finally`` tanto si el trabajo corre, falla o nunca
          llegó a empezar — sin bloqueos permanentes.
        """
        raise NotImplementedError
