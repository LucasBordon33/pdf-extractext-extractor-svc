"""Servicio de dominio: extracción de texto de documentos.

Coordina el flujo de extracción delegando en el puerto ``TextExtractor``
inyectado. No conoce PyPDF2, HTTP, base64 ni JSON: recibe bytes ya
decodificados y devuelve texto plano. Los errores son los de dominio
(``CorruptFileError``, ``EmptyExtractionError``); la traducción a HTTP
ocurre en la capa API.
"""

from domain.ports.text_extractor import TextExtractor


class DocumentService:
    """Coordina la extracción de texto delegando en el extractor."""

    def __init__(self, extractor: TextExtractor) -> None:
        self._extractor = extractor

    def extract_text(self, content: bytes, filename: str) -> str:
        """Devuelve el texto plano del documento.

        :param content: bytes crudos del documento (ya decodificados).
        :param filename: nombre original, usado como contexto de error.
        :raises CorruptFileError: el contenido no puede procesarse.
        :raises EmptyExtractionError: no se obtuvo texto válido.
        """
        return self._extractor.extract(content, filename)
