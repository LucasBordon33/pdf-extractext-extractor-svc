"""Tests de concurrencia, deadline y validación del DocumentService.

El pool se dobla con implementaciones de prueba del puerto
``ExtractionPool``: una ejecuta en un thread real (verifica que el
trabajo NUNCA corre en el hilo del request), otra nunca completa
(verifica cancelación + ExtractionTimeoutError).
"""

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from core.exceptions import (
    CorruptFileError,
    EmptyExtractionError,
    ExtractionTimeoutError,
    FileTooLargeError,
    OverloadedError,
    QueueSaturatedError,
)
from domain.models.extraction_result import ExtractionResult
from domain.ports.extraction_pool import ExtractionPool
from domain.ports.text_extractor import PdfToMarkdown
from tests.unit.doubles import ImmediateExtractionPool, make_document_service

RESULT = ExtractionResult(
    markdown="texto", page_count=1, pages_processed=1, duration_ms=1.0
)
JUST_OVER_1_MB = b"x" * (1024 * 1024 + 1)


class RecordingPool(ExtractionPool):
    """Ejecuta en un thread real y registra los trabajos recibidos."""

    def __init__(self) -> None:
        self.submitted = 0
        self._executor = ThreadPoolExecutor(max_workers=1)

    def submit(
        self, work: Callable[[], ExtractionResult]
    ) -> Future[ExtractionResult]:
        self.submitted += 1
        return self._executor.submit(work)


class CancelSpyFuture(Future):
    """Futuro que cuenta las llamadas a cancel."""

    def __init__(self) -> None:
        super().__init__()
        self.cancel_calls = 0

    def cancel(self) -> bool:
        self.cancel_calls += 1
        return True


class NeverCompletingPool(ExtractionPool):
    """Devuelve futuros que nunca terminan (para el deadline)."""

    def __init__(self) -> None:
        self.spy = CancelSpyFuture()

    def submit(
        self, work: Callable[[], ExtractionResult]
    ) -> Future[ExtractionResult]:
        return self.spy


class BlockingExtractor:
    """Extractor que anuncia su entrada y espera a que lo liberen.

    Permite ocupar un lugar de admision desde otro hilo de forma
    determinista, sin dormir y depender de la suerte del scheduler.
    """

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.released = threading.Event()

    def extract(self, content: bytes, filename: str) -> ExtractionResult:
        self.entered.set()
        if not self.released.wait(5):
            raise AssertionError("el test no libero el extractor")
        return RESULT

    def hold_slot(self, service, errors: list) -> threading.Thread:
        """Ocupa un lugar de admision hasta que se llame ``release()``."""
        thread = threading.Thread(
            target=lambda: errors.append(
                _capture(service.extract, b"%PDF-1.4", "ocupa.pdf")
            )
        )
        thread.start()
        assert self.entered.wait(5), "el extractor nunca empezo a trabajar"
        return thread

    def release(self) -> None:
        self.released.set()


class TimeoutOncePool(ExtractionPool):
    """El primer trabajo nunca completa; el siguiente sí.

    Permite comprobar que el lugar de admision se devuelve tras un
    deadline vencido, sin acoplar el test a los internos del servicio.
    """

    def __init__(self) -> None:
        self._calls = 0
        self._executor = ThreadPoolExecutor(max_workers=1)

    def submit(
        self, work: Callable[[], ExtractionResult]
    ) -> Future[ExtractionResult]:
        self._calls += 1
        if self._calls == 1:
            return Future()
        return self._executor.submit(work)


class RejectOncePool(ExtractionPool):
    """Rechaza el primer trabajo con saturación; el siguiente pasa.

    El rechazo ocurre ya con el lugar de admision tomado, así que
    sirve para verificar que ese lugar también se devuelve.
    """

    def __init__(self) -> None:
        self._inner = ImmediateExtractionPool()
        self._calls = 0

    def submit(
        self, work: Callable[[], ExtractionResult]
    ) -> Future[ExtractionResult]:
        self._calls += 1
        if self._calls == 1:
            raise QueueSaturatedError("llena", retry_after_seconds=1)
        return self._inner.submit(work)


def _capture(call, *args) -> Exception | None:
    """Ejecuta ``call`` y devuelve la excepción, o ``None`` si tuvo éxito."""
    try:
        call(*args)
    except Exception as error:
        return error
    return None


class TestHappyPath:
    def test_delegates_to_pool_and_returns_result(self):
        extractor = Mock(spec=PdfToMarkdown)
        extractor.extract.return_value = RESULT
        pool = RecordingPool()
        service = make_document_service(extractor, pool=pool)

        result = service.extract(b"%PDF-1.4", "doc.pdf")

        assert result == RESULT
        assert pool.submitted == 1
        extractor.extract.assert_called_once_with(b"%PDF-1.4", "doc.pdf")

    def test_work_never_runs_in_caller_thread(self):
        worker_threads = []
        extractor = Mock(spec=PdfToMarkdown)
        extractor.extract.side_effect = lambda *args: (
            worker_threads.append(threading.get_ident()) or RESULT
        )
        pool = RecordingPool()
        service = make_document_service(extractor, pool=pool)

        service.extract(b"%PDF-1.4", "doc.pdf")

        assert worker_threads[0] != threading.get_ident()

    def test_duration_ms_is_preserved_for_metrics(self):
        extractor = Mock(spec=PdfToMarkdown)
        extractor.extract.return_value = ExtractionResult(
            markdown="m", page_count=1, pages_processed=1, duration_ms=42.5
        )
        service = make_document_service(extractor)

        assert service.extract(b"x", "doc.pdf").duration_ms == 42.5


class TestDeadline:
    def test_timeout_raises_extraction_timeout_and_cancels_future(self):
        pool = NeverCompletingPool()
        service = make_document_service(
            Mock(spec=PdfToMarkdown), pool=pool, extract_timeout_seconds=0.05
        )

        with pytest.raises(ExtractionTimeoutError) as exc_info:
            service.extract(b"%PDF-1.4", "doc.pdf")

        assert pool.spy.cancel_calls == 1
        assert "doc.pdf" in str(exc_info.value)

    def test_timeout_error_offers_retry_hint(self):
        pool = NeverCompletingPool()
        service = make_document_service(
            Mock(spec=PdfToMarkdown), pool=pool, extract_timeout_seconds=2.5
        )

        with pytest.raises(ExtractionTimeoutError) as exc_info:
            service.extract(b"x", "doc.pdf")

        assert exc_info.value.retry_after_seconds == 3


class TestAdmission:
    """Espera acotada por un lugar de extraccion (429 ``OverloadedError``)."""

    def test_busy_service_rejects_with_overloaded_after_the_timeout(self):
        extractor = BlockingExtractor()
        service = make_document_service(
            extractor,
            pool=RecordingPool(),
            max_concurrent_extractions=1,
            admission_timeout_seconds=0.05,
        )
        errors: list = []
        holder = extractor.hold_slot(service, errors)

        with pytest.raises(OverloadedError) as exc_info:
            service.extract(b"%PDF-1.4", "doc.pdf")

        extractor.release()
        holder.join(timeout=5)
        assert errors == [None]
        assert "doc.pdf" in str(exc_info.value)

    def test_overloaded_error_tells_the_client_to_retry(self):
        extractor = BlockingExtractor()
        service = make_document_service(
            extractor,
            pool=RecordingPool(),
            max_concurrent_extractions=1,
            admission_timeout_seconds=0.05,
        )
        errors: list = []
        holder = extractor.hold_slot(service, errors)

        with pytest.raises(OverloadedError) as exc_info:
            service.extract(b"%PDF-1.4", "doc.pdf")

        extractor.release()
        holder.join(timeout=5)
        assert exc_info.value.retry_after_seconds == 1

    def test_waiting_request_is_admitted_once_a_slot_frees_up(self):
        extractor = BlockingExtractor()
        service = make_document_service(
            extractor,
            pool=RecordingPool(),
            max_concurrent_extractions=1,
            admission_timeout_seconds=5.0,
        )
        errors: list = []
        holder = extractor.hold_slot(service, errors)
        waiters: list = []
        admitted = threading.Event()

        def wait_for_slot() -> None:
            waiters.append(_capture(service.extract, b"%PDF-1.4", "lento.pdf"))
            admitted.set()

        waiter = threading.Thread(target=wait_for_slot)
        waiter.start()
        # El segundo request no debe resolver mientras el lugar esta ocupado.
        assert not admitted.wait(0.2), "admitio antes de que se liberara el lugar"

        extractor.release()
        holder.join(timeout=5)
        waiter.join(timeout=5)

        assert admitted.is_set()
        assert waiters == [None]

    def test_rejected_request_never_reaches_the_pool(self):
        extractor = BlockingExtractor()
        pool = RecordingPool()
        service = make_document_service(
            extractor,
            pool=pool,
            max_concurrent_extractions=1,
            admission_timeout_seconds=0.05,
        )
        errors: list = []
        holder = extractor.hold_slot(service, errors)

        with pytest.raises(OverloadedError):
            service.extract(b"%PDF-1.4", "doc.pdf")

        extractor.release()
        holder.join(timeout=5)
        assert pool.submitted == 1

    def test_oversized_request_does_not_hold_a_slot(self):
        """El tamano se valida antes de admitir: un 413 no ocupa lugar."""
        extractor = Mock(spec=PdfToMarkdown)
        pool = RecordingPool()
        service = make_document_service(
            extractor, pool=pool, max_upload_size_mb=1, max_concurrent_extractions=1
        )

        for _ in range(3):
            with pytest.raises(FileTooLargeError):
                service.extract(JUST_OVER_1_MB, "grande.pdf")

        extractor.extract.return_value = RESULT
        assert service.extract(b"x", "doc.pdf") == RESULT


class TestSlotIsAlwaysReturned:
    """Una fuga de lugar degrada el servicio de forma irreversible."""

    def test_slot_returns_after_success(self):
        extractor = Mock(spec=PdfToMarkdown)
        extractor.extract.return_value = RESULT
        service = make_document_service(
            extractor, max_concurrent_extractions=1
        )

        for _ in range(3):
            assert service.extract(b"x", "doc.pdf") == RESULT

    def test_slot_returns_after_extractor_error(self):
        extractor = Mock(spec=PdfToMarkdown)
        extractor.extract.side_effect = CorruptFileError("roto")
        service = make_document_service(
            extractor, max_concurrent_extractions=1
        )

        with pytest.raises(CorruptFileError):
            service.extract(b"x", "doc.pdf")

        extractor.extract.side_effect = None
        extractor.extract.return_value = RESULT
        assert service.extract(b"x", "doc.pdf") == RESULT

    def test_slot_returns_after_deadline(self):
        extractor = Mock(spec=PdfToMarkdown)
        extractor.extract.return_value = RESULT
        service = make_document_service(
            extractor,
            pool=TimeoutOncePool(),
            extract_timeout_seconds=0.05,
            max_concurrent_extractions=1,
        )

        with pytest.raises(ExtractionTimeoutError):
            service.extract(b"x", "doc.pdf")

        assert service.extract(b"x", "doc.pdf") == RESULT

    def test_slot_returns_after_pool_rejection(self):
        extractor = Mock(spec=PdfToMarkdown)
        extractor.extract.return_value = RESULT
        service = make_document_service(
            extractor, pool=RejectOncePool(), max_concurrent_extractions=1
        )

        with pytest.raises(QueueSaturatedError):
            service.extract(b"x", "doc.pdf")

        assert service.extract(b"x", "doc.pdf") == RESULT


class TestFileSize:
    def test_oversized_content_raises_file_too_large(self):
        extractor = Mock(spec=PdfToMarkdown)
        pool = RecordingPool()
        service = make_document_service(
            extractor, pool=pool, max_upload_size_mb=1
        )

        with pytest.raises(FileTooLargeError) as exc_info:
            service.extract(JUST_OVER_1_MB, "grande.pdf")

        assert "grande.pdf" in str(exc_info.value)
        assert pool.submitted == 0
        extractor.extract.assert_not_called()


class TestErrorPropagation:
    @pytest.mark.parametrize(
        "error_class",
        [CorruptFileError, EmptyExtractionError],
        ids=["corrupt-file", "empty-extraction"],
    )
    def test_extractor_errors_rethrown_unchanged(self, error_class):
        domain_error = error_class("fallo")
        extractor = Mock(spec=PdfToMarkdown)
        extractor.extract.side_effect = domain_error
        service = make_document_service(extractor)

        with pytest.raises(error_class) as exc_info:
            service.extract(b"contenido", "doc.pdf")

        assert exc_info.value is domain_error
