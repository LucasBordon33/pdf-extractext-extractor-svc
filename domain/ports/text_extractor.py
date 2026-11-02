"""Puerto de dominio: conversión de PDF a Markdown enriquecido.

Contrato que cualquier adaptador (pdfium, OCR, otro motor) debe
cumplir. El dominio solo conoce bytes ya decodificados: base64, JSON
y HTTP son detalles de transporte resueltos en la capa API.
"""

from abc import ABC, abstractmethod

from domain.models.extraction_result import ExtractionResult


class PdfToMarkdown(ABC):

    @abstractmethod
    def extract(self, content: bytes, filename: str) -> ExtractionResult:
        raise NotImplementedError
