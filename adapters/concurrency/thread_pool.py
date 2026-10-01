"""Pool de extracción con threads: executor + semáforo + cola acotada.

Implementación del puerto ``ExtractionPool`` para el composition
root. La extracción es CPU-bound (pdfium): threads liberan el GIL
durante el trabajo nativo, así que el paralelismo se consigue sin el
costo de picklear el PDF hacia otro proceso (ADR-TP-5).

Dos topes distintos y por qué ambos hacen falta:

- ``max_concurrent`` (semáforo): cuántos trabajos **corren** a la vez.
- ``max_queue_depth``: cuántos trabajos están **pendientes de
  completarse**, contando los que ya corren. ``ThreadPoolExecutor``
  encola sin tope, así que sin este control una ráfaga de peticiones se
  convierte en trabajo que vence antes de ejecutarse — que es
  justamente el timeout que el TP pide evitar (ADR-TP-7).
"""

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from core.exceptions import QueueSaturatedError
from domain.models.extraction_result import ExtractionResult
from domain.ports.extraction_pool import ExtractionPool

_RETRY_AFTER_SATURATED = 1


class ThreadPoolExtractionPool(ExtractionPool):
    """Ejecuta extracciones en threads con concurrencia y cola acotadas.

    El slot del semáforo se adquiere y libera dentro del trabajo con
    ``with`` (equivalente a try/finally): aunque el futuro se cancele
    o el trabajo falle, nunca queda un slot tomado. El contador de la
    cola se libera en el ``finally`` del mismo trabajo.
    """

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
        """Entrega el trabajo al executor, o lo rechaza si la cola está llena.

        :raises QueueSaturatedError: ya hay ``max_queue_depth`` trabajos
            pendientes de completarse. Se rechaza **antes** de encolar,
            para que el llamador reciba el 503 de inmediato en vez de
            acumular trabajo que no va a llegar.
        """
        self._reserve()
        try:
            return self._executor.submit(self._tracked(work))
        except Exception:
            # El trabajo nunca llegó a correr, así que su ``finally`` no
            # libera nada: la reserva se devuelve acá.
            self._release()
            raise

    def _reserve(self) -> None:
        """Toma un lugar en la cola o lanza ``QueueSaturatedError``."""
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
        """Envuelve el trabajo para devolver su lugar en la cola al terminar."""

        def tracked() -> ExtractionResult:
            try:
                with self._semaphore:
                    return work()
            finally:
                self._release()

        return tracked
