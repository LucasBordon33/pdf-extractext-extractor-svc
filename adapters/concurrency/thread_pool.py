"""Pool de extracción con threads: executor + semáforo (ISSUE-008).

Implementación del puerto ``ExtractionPool`` para el composition
root. La extracción es CPU-bound (pdfium): threads liberan el GIL
durante el trabajo nativo, y el semáforo acota la simultaneidad
independientemente del tamaño del executor.
"""

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from domain.models.extraction_result import ExtractionResult
from domain.ports.extraction_pool import ExtractionPool


class ThreadPoolExtractionPool(ExtractionPool):
    """Ejecuta extracciones en threads con concurrencia acotada.

    El slot del semáforo se adquiere y libera dentro del trabajo con
    ``with`` (equivalente a try/finally): aunque el futuro se cancele
    o el trabajo falle, nunca queda un slot tomado.
    """

    def __init__(self, max_workers: int, max_concurrent: int) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._semaphore = threading.Semaphore(max_concurrent)

    def submit(
        self, work: Callable[[], ExtractionResult]
    ) -> Future[ExtractionResult]:
        def bounded_work() -> ExtractionResult:
            with self._semaphore:
                return work()

        return self._executor.submit(bounded_work)
