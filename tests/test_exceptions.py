import pytest

from core.exceptions import (
    CorruptFileError,
    DocumentExtractionError,
    EmptyExtractionError,
    FileTooLargeError,
    UnsupportedFormatError,
)


class TestDocumentExtractionError:
    def test_is_exception_subclass(self):
        assert issubclass(DocumentExtractionError, Exception)

    def test_can_be_raised_with_message(self):
        with pytest.raises(DocumentExtractionError, match="fallo generico"):
            raise DocumentExtractionError("fallo generico")

    def test_exposes_error_code(self):
        exc = DocumentExtractionError("fallo generico")
        assert exc.error_code == "DOCUMENT_EXTRACTION_ERROR"

    def test_exposes_status_http(self):
        exc = DocumentExtractionError("fallo generico")
        assert exc.status_http == 500


class TestConcreteExceptions:
    @pytest.mark.parametrize(
        ("exc_class", "error_code", "status_http"),
        [
            (UnsupportedFormatError, "UNSUPPORTED_FORMAT", 415),
            (CorruptFileError, "CORRUPT_FILE", 422),
            (FileTooLargeError, "FILE_TOO_LARGE", 413),
            (EmptyExtractionError, "EMPTY_EXTRACTION", 422),
        ],
    )
    def test_exposes_error_code_and_status_http(
        self, exc_class, error_code, status_http
    ):
        exc = exc_class("mensaje de prueba")
        assert exc.error_code == error_code
        assert exc.status_http == status_http

    @pytest.mark.parametrize(
        "exc_class",
        [
            UnsupportedFormatError,
            CorruptFileError,
            FileTooLargeError,
            EmptyExtractionError,
        ],
    )
    def test_inherits_from_base(self, exc_class):
        assert issubclass(exc_class, DocumentExtractionError)

    @pytest.mark.parametrize(
        "exc_class",
        [
            UnsupportedFormatError,
            CorruptFileError,
            FileTooLargeError,
            EmptyExtractionError,
        ],
    )
    def test_custom_message_is_preserved(self, exc_class):
        message = "el archivo reporte.pdf no se pudo procesar"
        exc = exc_class(message)
        assert str(exc) == message

    @pytest.mark.parametrize(
        "exc_class",
        [
            UnsupportedFormatError,
            CorruptFileError,
            FileTooLargeError,
            EmptyExtractionError,
        ],
    )
    def test_can_be_raised_and_caught_as_base(self, exc_class):
        with pytest.raises(DocumentExtractionError):
            raise exc_class("cualquier error")

    def test_each_error_code_is_unique(self):
        codes = {
            cls("x").error_code
            for cls in (
                UnsupportedFormatError,
                CorruptFileError,
                FileTooLargeError,
                EmptyExtractionError,
            )
        }
        assert len(codes) == 4
