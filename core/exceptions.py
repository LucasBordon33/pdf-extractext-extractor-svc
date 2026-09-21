"""Excepciones de dominio del servicio de extracción de PDFs.

Estas excepciones son independientes de frameworks web. El atributo
``status_http`` es solo un contrato informativo que la capa HTTP
(api/) traduce a respuestas, sin acoplar el dominio a FastAPI.
"""

from http import HTTPStatus


class DocumentExtractionError(Exception):
    """Error base para cualquier fallo en la extracción de documentos."""

    error_code: str = "DOCUMENT_EXTRACTION_ERROR"
    status_http: int = HTTPStatus.INTERNAL_SERVER_ERROR

    def __init__(self, message: str) -> None:
        super().__init__(message)


class UnsupportedFormatError(DocumentExtractionError):
    """El formato del documento recibido no está soportado."""

    error_code: str = "UNSUPPORTED_FORMAT"
    status_http: int = HTTPStatus.UNSUPPORTED_MEDIA_TYPE


class CorruptFileError(DocumentExtractionError):
    """El archivo está dañado o no puede leerse."""

    error_code: str = "CORRUPT_FILE"
    status_http: int = HTTPStatus.UNPROCESSABLE_ENTITY


class FileTooLargeError(DocumentExtractionError):
    """El archivo supera el tamaño máximo permitido."""

    error_code: str = "FILE_TOO_LARGE"
    status_http: int = HTTPStatus.REQUEST_ENTITY_TOO_LARGE


class EmptyExtractionError(DocumentExtractionError):
    """La extracción terminó sin producir contenido."""

    error_code: str = "EMPTY_EXTRACTION"
    status_http: int = HTTPStatus.UNPROCESSABLE_ENTITY
