"""Tests del límite de cola de ``ThreadPoolExtractionPool``.

El semáforo ya está cubierto por los dobles de
``tests/domain/services/test_document_service_pool.py``. Acá se
verifica lo propio del adaptador real: que la cola acotada rechaza
con ``QueueSaturatedError`` en vez de acumular trabajo, y que el
contador no se fugan ni por éxito, ni por excepción, ni por un
``submit`` que falla.
"""

import threading
from concurrent.futures import Future

import pytest

from adapters.concurrency.thread_pool import ThreadPoolExtractionPool
from core.exceptions import QueueSaturatedError
from domain.models.extraction_result import ExtractionResult
from domain.ports.extraction_pool import ExtractionPool

RESULT = ExtractionResult(
    markdown="texto", page_count=1, pages_processed=1, duration_ms=1.0
)


def make_pool(max_concurrent: int = 1, max_queue_depth: int = 4) -> ThreadPoolExtractionPool:
    return ThreadPoolExtractionPool(
        max_workers=2, max_concurrent=max_concurrent, max_queue_depth=max_queue_depth
    )


def ok_work() -> ExtractionResult:
    return RESULT


def blocking_work(release: threading.Event):
    """Trabajo que ocupa un slot hasta que se libera ``release``."""

    def work() -> ExtractionResult:
        release.wait(timeout=5)
        return RESULT

    return work


class TestContract:
    def test_implements_extraction_pool_port(self):
        assert isinstance(make_pool(), ExtractionPool)


class TestQueueSaturation:
    def test_rejects_with_queue_saturated_when_depth_exceeded(self):
        pool = make_pool(max_concurrent=1, max_queue_depth=1)
        release = threading.Event()
        pool.submit(blocking_work(release))

        with pytest.raises(QueueSaturatedError) as exc_info:
            pool.submit(ok_work)

        assert "1" in str(exc_info.value)
        release.set()

    def test_saturated_error_offers_retry_hint(self):
        pool = make_pool(max_concurrent=1, max_queue_depth=1)
        release = threading.Event()
        pool.submit(blocking_work(release))

        with pytest.raises(QueueSaturatedError) as exc_info:
            pool.submit(ok_work)

        assert exc_info.value.status_http == 503
        assert exc_info.value.error_code == "QUEUE_SATURATED"
        assert exc_info.value.retry_after_seconds == 1
        release.set()

    def test_counts_running_work_not_only_queued_work(self):
        """El límite cubre lo que corre más lo pendiente, no solo lo encolado."""
        pool = make_pool(max_concurrent=1, max_queue_depth=2)
        release = threading.Event()
        pool.submit(blocking_work(release))
        pool.submit(blocking_work(release))

        with pytest.raises(QueueSaturatedError):
            pool.submit(ok_work)

        release.set()

    def test_accepts_work_again_once_the_queue_drains(self):
        pool = make_pool(max_concurrent=1, max_queue_depth=1)
        first = pool.submit(ok_work)
        first.result(timeout=5)

        second = pool.submit(ok_work)

        assert second.result(timeout=5) == RESULT


class TestSlotRelease:
    def test_slot_is_released_after_work_fails(self):
        pool = make_pool(max_concurrent=1, max_queue_depth=1)

        def boom() -> ExtractionResult:
            raise RuntimeError("fallo del algoritmo")

        failed = pool.submit(boom)
        with pytest.raises(RuntimeError):
            failed.result(timeout=5)

        # La cola se liberó: un trabajo nuevo entra y no hay rechazo.
        assert pool.submit(ok_work).result(timeout=5) == RESULT

    def test_reservation_is_returned_when_submit_itself_fails(self, monkeypatch):
        """Si el executor rechaza el trabajo, la reserva no debe quedar tomada.

        Es el camino de un ``submit`` que falla porque el pool ya se
        cerró: si la reserva se fugara, el siguiente trabajo sería
        rechazado por cola llena en lugar de llegar al executor.
        """
        pool = make_pool(max_queue_depth=1)
        monkeypatch.setattr(pool._executor, "submit", _raise_unavailable)

        with pytest.raises(RuntimeError):
            pool.submit(ok_work)

        # Llega al executor otra vez (RuntimeError), no a la cola (503).
        with pytest.raises(RuntimeError):
            pool.submit(ok_work)


class TestConcurrencyBound:
    def test_work_never_runs_in_caller_thread(self):
        pool = make_pool()
        worker_threads = []

        def record_thread() -> ExtractionResult:
            worker_threads.append(threading.get_ident())
            return RESULT

        pool.submit(record_thread).result(timeout=5)

        assert worker_threads[0] != threading.get_ident()

    def test_simultaneous_work_never_exceeds_max_concurrent(self):
        max_concurrent = 2
        pool = make_pool(max_concurrent=max_concurrent, max_queue_depth=4)
        overlap = threading.Barrier(max_concurrent)
        guard = threading.Lock()
        active = 0
        peak = 0

        def counted_work() -> ExtractionResult:
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            try:
                # Solo los max_concurrent que llegaron hasta acá se
                # encuentran: la barrera se rompe si el semáforo no los
                # deja correr en paralelo.
                overlap.wait(timeout=5)
            finally:
                with guard:
                    active -= 1
            return RESULT

        futures: list[Future[ExtractionResult]] = [
            pool.submit(counted_work) for _ in range(4)
        ]
        for future in futures:
            future.result(timeout=5)

        assert peak == max_concurrent


def _raise_unavailable(*args, **kwargs):
    raise RuntimeError("executor no disponible")
