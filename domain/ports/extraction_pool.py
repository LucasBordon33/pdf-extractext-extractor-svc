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

    @abstractmethod
    def submit(
        self, work: Callable[[], ExtractionResult]
    ) -> Future[ExtractionResult]:
        raise NotImplementedError
