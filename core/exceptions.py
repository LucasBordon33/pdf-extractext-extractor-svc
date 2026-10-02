"""Excepciones de dominio del servicio de extracción de PDFs.

Independientes de frameworks web: el atributo ``status_http`` es un
contrato informativo que la capa HTTP (api/) traduce a respuestas,
incluido el header ``Retry-After`` cuando ``retry_after_seconds``
esta presente. Estados de saturación (429/503) permiten backpressure
controlado en lugar de dejar que la petición expire en el cliente.
"""

from http import HTTPStatus


class DocumentExtractionError(Exception):
    """Error base para cualquier fallo en la extracción de documentos."""

    error_code: str = "DOCUMENT_EXTRACTION_ERROR"
    status_http: int = HTTPStatus.INTERNAL_SERVER_ERROR
    retry_after_seconds: int | None = None

    def __init__(self, message: str, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        if retry_after_seconds is not None:
            self.retry_after_seconds = retry_after_seconds


class UnsupportedFormatError(DocumentExtractionError):
    """El formato del documento recibido no está soportado."""

    error_code: str = "UNSUPPORTED_FORMAT"
    status_http: int = HTTPStatus.UNSUPPORTED_MEDIA_TYPE


class CorruptFileError(DocumentExtractionError):
    """El archivo está dañado o cifrado sin acceso."""

    error_code: str = "CORRUPT_FILE"
    status_http: int = HTTPStatus.BAD_REQUEST


class FileTooLargeError(DocumentExtractionError):
    """El archivo supera el tamaño máximo permitido."""

    error_code: str = "FILE_TOO_LARGE"
    status_http: int = HTTPStatus.REQUEST_ENTITY_TOO_LARGE


class NotAPdfError(DocumentExtractionError):
    """El body no empieza con el magic number ``%PDF-``.

    Rechazo rápido para basura: evita cargar el motor de extracción.
    """

    error_code: str = "NOT_A_PDF"
    status_http: int = HTTPStatus.UNSUPPORTED_MEDIA_TYPE


class EmptyBodyError(DocumentExtractionError):
    """La petición no trae ningún byte utilizable.

    Body crudo vacío o multipart cuyo campo ``file`` no aporta nada:
    no tiene sentido cargar el motor de extracción.
    """

    error_code: str = "EMPTY_BODY"
    status_http: int = HTTPStatus.BAD_REQUEST


class MissingFileFieldError(DocumentExtractionError):
    """El multipart no incluye el campo ``file`` esperado.

    422: la forma de la petición es válida pero le falta el dato
    obligatorio (ISSUE-012 exige el campo en la convención del grupo).
    """

    error_code: str = "MISSING_FILE"
    status_http: int = HTTPStatus.UNPROCESSABLE_ENTITY


class EmptyExtractionError(DocumentExtractionError):
    """La extracción terminó sin producir contenido."""

    error_code: str = "EMPTY_EXTRACTION"
    status_http: int = HTTPStatus.UNPROCESSABLE_ENTITY


class ExtractionTimeoutError(DocumentExtractionError):
    """Se superó el deadline interno (EXTRACT_TIMEOUT_SECONDS)."""

    error_code: str = "EXTRACTION_TIMEOUT"
    status_http: int = HTTPStatus.SERVICE_UNAVAILABLE


class OverloadedError(DocumentExtractionError):
    """La cola de admisión agotó ADMISSION_TIMEOUT_SECONDS.

    429: el sistema esta saturado pero un reintento (tras esperar)
    puede tener exito.
    """

    error_code: str = "OVERLOADED"
    status_http: int = HTTPStatus.TOO_MANY_REQUESTS


class QueueSaturatedError(DocumentExtractionError):
    """Se superó QUEUE_MAX_SIZE.

    503: mas severa; reintentar de inmediato no ayuda — el emisor
    debería retroceder y respetar el ``retry_after_seconds``.
    """

    error_code: str = "QUEUE_SATURATED"
    status_http: int = HTTPStatus.SERVICE_UNAVAILABLE
