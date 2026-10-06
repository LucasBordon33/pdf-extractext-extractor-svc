"""Tests de la jerarquía de excepciones de dominio.

Valida el contrato de cada error: codigo interno, status HTTP
informativo y semantica de reintento (``retry_after_seconds``).
El dominio no conoce FastAPI: solo expone datos para el handler.
"""

import pytest

from core.exceptions import (
    CorruptFileError,
    DocumentExtractionError,
    EmptyExtractionError,
    ExtractionTimeoutError,
    FileTooLargeError,
    NotAPdfError,
    OverloadedError,
    QueueSaturatedError,
    UnsupportedFormatError,
)

CONCRETE_ERRORS = [
    (UnsupportedFormatError, "UNSUPPORTED_FORMAT", 415),
    (CorruptFileError, "CORRUPT_FILE", 400),
    (FileTooLargeError, "FILE_TOO_LARGE", 413),
    (EmptyExtractionError, "EMPTY_EXTRACTION", 422),
    (NotAPdfError, "NOT_A_PDF", 415),
    (ExtractionTimeoutError, "EXTRACTION_TIMEOUT", 503),
    (OverloadedError, "OVERLOADED", 429),
    (QueueSaturatedError, "QUEUE_SATURATED", 503),
]


class TestDocumentExtractionError:
    def test_is_exception_subclass(self):
        assert issubclass(DocumentExtractionError, Exception)

    def test_can_be_raised_with_message(self):
        with pytest.raises(DocumentExtractionError, match="fallo generico"):
            raise DocumentExtractionError("fallo generico")

    def test_exposes_error_code(self):
        assert DocumentExtractionError("x").error_code == "DOCUMENT_EXTRACTION_ERROR"

    def test_exposes_status_http(self):
        assert DocumentExtractionError("x").status_http == 500

    def test_retry_after_defaults_to_none(self):
        assert DocumentExtractionError("x").retry_after_seconds is None

    def test_retry_after_is_overridable(self):
        exc = DocumentExtractionError("x", retry_after_seconds=30)
        assert exc.retry_after_seconds == 30


class TestConcreteExceptions:
    @pytest.mark.parametrize(
        ("exc_class", "error_code", "status_http"), CONCRETE_ERRORS
    )
    def test_exposes_error_code_and_status_http(
        self, exc_class, error_code, status_http
    ):
        exc = exc_class("mensaje de prueba")
        assert exc.error_code == error_code
        assert exc.status_http == status_http

    @pytest.mark.parametrize(
        "exc_class", [row[0] for row in CONCRETE_ERRORS]
    )
    def test_inherits_from_base(self, exc_class):
        assert issubclass(exc_class, DocumentExtractionError)

    @pytest.mark.parametrize(
        "exc_class", [row[0] for row in CONCRETE_ERRORS]
    )
    def test_custom_message_is_preserved(self, exc_class):
        message = "el archivo reporte.pdf no se pudo procesar"
        assert str(exc_class(message)) == message

    @pytest.mark.parametrize(
        "exc_class", [row[0] for row in CONCRETE_ERRORS]
    )
    def test_can_be_raised_and_caught_as_base(self, exc_class):
        with pytest.raises(DocumentExtractionError):
            raise exc_class("cualquier error")

    def test_each_error_code_is_unique(self):
        codes = [exc_class("x").error_code for exc_class, _, _ in CONCRETE_ERRORS]
        assert len(set(codes)) == len(codes)


class TestRetrySemantics:
    def test_all_concrete_errors_default_to_no_retry_hint(self):
        for exc_class, _, _ in CONCRETE_ERRORS:
            assert exc_class("x").retry_after_seconds is None

    def test_overloaded_accepts_retry_hint(self):
        """El orquestador emite el hint cuando agota ADMISSION_TIMEOUT."""
        exc = OverloadedError("cola saturada, espere", retry_after_seconds=10)
        assert exc.retry_after_seconds == 10

    def test_queue_saturated_accepts_retry_hint(self):
        exc = QueueSaturatedError("cola llena", retry_after_seconds=60)
        assert exc.retry_after_seconds == 60

    def test_extraction_timeout_accepts_retry_hint(self):
        exc = ExtractionTimeoutError("deadline agotado", retry_after_seconds=5)
        assert exc.retry_after_seconds == 5

    def test_saturation_errors_map_to_client_retryable_statuses(self):
        """429/503 le dicen al cliente que reintente; 400/413/415/422 no."""
        retryable = {
            OverloadedError.status_http,
            QueueSaturatedError.status_http,
            ExtractionTimeoutError.status_http,
        }
        assert retryable == {429, 503}
