"""Puerto de dominio: extracción de texto de documentos.

Contrato que cualquier adaptador (PDF, DOCX, imagen+OCR, ...) debe
cumplir. El dominio solo conoce bytes ya decodificados: base64, JSON
y HTTP son detalles de transporte resueltos en la capa API.
"""

from abc import ABC, abstractmethod


class TextExtractor(ABC):
    """Extrae texto plano del contenido binario de un documento.

    Errores del contrato (definidos en ``core.exceptions``):

    - ``CorruptFileError``: el contenido no puede procesarse
      (archivo dañado, bytes que no corresponden al formato, ...).
    - ``EmptyExtractionError``: el documento se leyó pero no
      produjo texto válido (p. ej. un PDF de solo imágenes).
    """

    @abstractmethod
    def extract(self, content: bytes, filename: str) -> str:
        """Devuelve el texto plano contenido en ``content``.

        :param content: bytes crudos del documento, ya decodificados
            (sin base64 ni envoltorios de transporte).
        :param filename: nombre original del archivo; útil para
            diagnóstico y contexto en mensajes de error.
        """
        raise NotImplementedError
