import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from core.exceptions import QueueSaturatedError
from domain.models.extraction_result import ExtractionResult
from domain.ports.extraction_pool import ExtractionPool

_RETRY_AFTER_SATURATED = 1


class ThreadPoolExtractionPool(ExtractionPool):

    def __init__(
        self,
        *,
        max_workers: int,
        max_concurrent: int,
        max_queue_depth: int,
    ) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._semaphore = threading.Semaphore(max_concurrent)
        self._max_queue_depth = max_queue_depth
        self._lock = threading.Lock()
        self._outstanding = 0

    def submit(
        self, work: Callable[[], ExtractionResult]
    ) -> Future[ExtractionResult]:
        self._reserve()
        try:
            return self._executor.submit(self._tracked(work))
        except Exception:
            # El trabajo nunca llegó a correr, así que su ``finally`` no
            # libera nada: la reserva se devuelve acá.
            self._release()
            raise

    def _reserve(self) -> None:
        with self._lock:
            if self._outstanding >= self._max_queue_depth:
                raise QueueSaturatedError(
                    f"cola de extraccion llena: {self._outstanding} trabajos"
                    f" pendientes de un maximo de {self._max_queue_depth}",
                    retry_after_seconds=_RETRY_AFTER_SATURATED,
                )
            self._outstanding += 1

    def _release(self) -> None:
        with self._lock:
            self._outstanding -= 1

    def _tracked(
        self, work: Callable[[], ExtractionResult]
    ) -> Callable[[], ExtractionResult]:

        def tracked() -> ExtractionResult:
            try:
                with self._semaphore:
                    return work()
            finally:
                self._release()

        return tracked
