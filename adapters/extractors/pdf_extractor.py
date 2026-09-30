"""Adaptador de extracción de texto para documentos PDF.

Motor: pypdfium2 (ADR-TP-1) — binding a PDFium, el motor de Chromium:
sustancialmente más rápido que PyPDF2 y con mantenimiento activo.
Toda la dependencia de la librería queda confinada en este módulo:
el dominio y el resto del sistema solo conocen el contrato abstracto.
"""

import pypdfium2 as pdfium

from core.exceptions import CorruptFileError, EmptyExtractionError
from domain.ports.text_extractor import TextExtractor


class PdfTextExtractor(TextExtractor):
    """Extrae texto plano de documentos PDF recibidos como bytes."""

    def extract(self, content: bytes, filename: str) -> str:
        try:
            with pdfium.PdfDocument(content) as document:
                text = self._read_all_pages(document)
        except pdfium.PdfiumError as error:
            # PdfiumError hereda de RuntimeError: se traduce SIEMPRE aqui
            # para que la infraestructura no escape del adaptador.
            raise CorruptFileError(
                f"no se pudo procesar el PDF '{filename}': {error}"
            ) from error
        self._ensure_text_found(text, filename)
        return text

    def _read_all_pages(self, document: pdfium.PdfDocument) -> str:
        fragments = []
        for page in document:
            text_page = page.get_textpage()
            try:
                fragments.append(text_page.get_text_range() or "")
            finally:
                text_page.close()
                page.close()
        return "".join(fragments)

    def _ensure_text_found(self, text: str, filename: str) -> None:
        if not text.strip():
            raise EmptyExtractionError(
                f"el PDF '{filename}' no contiene texto extraible"
                " (posiblemente escaneado como imagen)"
            )
