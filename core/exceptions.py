"""Excepciones de dominio del servicio de extracción de PDFs.

Independientes de frameworks web: el atributo ``status_http`` es un
contrato informativo que la capa HTTP (api/) traduce a respuestas,
incluido el header ``Retry-After`` cuando ``retry_after_seconds``
esta presente. Estados de saturación (429/503) permiten backpressure
controlado en lugar de dejar que la petición expire en el cliente.
"""

from http import HTTPStatus


class DocumentExtractionError(Exception):

    error_code: str = "DOCUMENT_EXTRACTION_ERROR"
    status_http: int = HTTPStatus.INTERNAL_SERVER_ERROR
    retry_after_seconds: int | None = None

    def __init__(self, message: str, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        if retry_after_seconds is not None:
            self.retry_after_seconds = retry_after_seconds


class UnsupportedFormatError(DocumentExtractionError):

    error_code: str = "UNSUPPORTED_FORMAT"
    status_http: int = HTTPStatus.UNSUPPORTED_MEDIA_TYPE


class CorruptFileError(DocumentExtractionError):

    error_code: str = "CORRUPT_FILE"
    status_http: int = HTTPStatus.BAD_REQUEST


class FileTooLargeError(DocumentExtractionError):

    error_code: str = "FILE_TOO_LARGE"
    status_http: int = HTTPStatus.REQUEST_ENTITY_TOO_LARGE


class NotAPdfError(DocumentExtractionError):

    error_code: str = "NOT_A_PDF"
    status_http: int = HTTPStatus.UNSUPPORTED_MEDIA_TYPE


class EmptyBodyError(DocumentExtractionError):
    error_code: str = "EMPTY_BODY"
    status_http: int = HTTPStatus.BAD_REQUEST


class MissingFileFieldError(DocumentExtractionError):

    error_code: str = "MISSING_FILE"
    status_http: int = HTTPStatus.UNPROCESSABLE_ENTITY


class EmptyExtractionError(DocumentExtractionError):

    error_code: str = "EMPTY_EXTRACTION"
    status_http: int = HTTPStatus.UNPROCESSABLE_ENTITY


class ExtractionTimeoutError(DocumentExtractionError):

    error_code: str = "EXTRACTION_TIMEOUT"
    status_http: int = HTTPStatus.SERVICE_UNAVAILABLE


class OverloadedError(DocumentExtractionError):

    error_code: str = "OVERLOADED"
    status_http: int = HTTPStatus.TOO_MANY_REQUESTS


class QueueSaturatedError(DocumentExtractionError):

    error_code: str = "QUEUE_SATURATED"
    status_http: int = HTTPStatus.SERVICE_UNAVAILABLE
