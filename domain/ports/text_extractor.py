"""Puerto de dominio: conversión de PDF a Markdown enriquecido.

Contrato que cualquier adaptador (pdfium, OCR, otro motor) debe
cumplir. El dominio solo conoce bytes ya decodificados: base64, JSON
y HTTP son detalles de transporte resueltos en la capa API.
"""

from abc import ABC, abstractmethod

from domain.models.extraction_result import ExtractionResult


class PdfToMarkdown(ABC):
    """Convierte un PDF en un ``ExtractionResult`` enriquecido.

    Errores del contrato (definidos en ``core.exceptions``):

    - ``CorruptFileError``: el contenido no puede procesarse
      (archivo dañado, cifrado, bytes que no son un PDF).
    - ``EmptyExtractionError``: el documento se leyó pero no
      produjo texto válido (p. ej. un PDF de solo imágenes).
    """

    @abstractmethod
    def extract(self, content: bytes, filename: str) -> ExtractionResult:
        """Devuelve el resultado enriquecido de la extracción.

        :param content: bytes crudos del documento, ya decodificados
            (sin base64 ni envoltorios de transporte).
        :param filename: nombre original del archivo; útil para
            diagnóstico y contexto en mensajes de error.
        """
        raise NotImplementedError
