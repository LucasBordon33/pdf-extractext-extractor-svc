"""Servicio de dominio: extracción de documentos.

Coordina el flujo delegando en el puerto ``PdfToMarkdown`` inyectado.
No conoce pdfium, HTTP, base64 ni JSON: recibe bytes ya decodificados
y devuelve un ``ExtractionResult`` enriquecido. Los errores son los
de dominio; la traducción a HTTP ocurre en la capa API.
"""

from domain.models.extraction_result import ExtractionResult
from domain.ports.text_extractor import PdfToMarkdown


class DocumentService:
    """Coordina la extracción delegando en el adaptador del puerto."""

    def __init__(self, extractor: PdfToMarkdown) -> None:
        self._extractor = extractor

    def extract(self, content: bytes, filename: str) -> ExtractionResult:
        """Devuelve el resultado enriquecido de la extracción.

        :param content: bytes crudos del documento (ya decodificados).
        :param filename: nombre original, usado como contexto de error.
        :raises CorruptFileError: el contenido no puede procesarse.
        :raises EmptyExtractionError: no se obtuvo texto válido.
        """
        return self._extractor.extract(content, filename)
