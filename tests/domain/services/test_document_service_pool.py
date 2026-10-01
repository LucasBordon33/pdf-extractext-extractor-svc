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
)
from domain.models.extraction_result import ExtractionResult
from domain.ports.extraction_pool import ExtractionPool
from domain.ports.text_extractor import PdfToMarkdown
from tests.doubles import make_document_service

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
