"""Adaptador de extracción para documentos PDF.

Motor: pypdfium2 (ADR-TP-1) — binding a PDFium, el motor de Chromium.
Cumple el puerto ``PdfToMarkdown`` devolviendo un ``ExtractionResult``
enriquecido (markdown, páginas, duración del algoritmo puro). Toda la
dependencia de la librería queda confinada en este módulo.
"""

import time

import pypdfium2 as pdfium

from core.exceptions import CorruptFileError, EmptyExtractionError
from domain.models.extraction_result import ExtractionResult
from domain.ports.text_extractor import PdfToMarkdown


class PdfiumPdfToMarkdown(PdfToMarkdown):
    """Extrae texto plano de PDFs usando PDFium, con métricas de proceso."""

    def extract(self, content: bytes, filename: str) -> ExtractionResult:
        started = time.perf_counter()
        try:
            with pdfium.PdfDocument(content) as document:
                page_count = len(document)
                markdown, pages_processed = self._read_all_pages(document)
        except pdfium.PdfiumError as error:
            # PdfiumError hereda de RuntimeError: se traduce SIEMPRE aqui
            # para que la infraestructura no escape del adaptador.
            raise CorruptFileError(
                f"no se pudo procesar el PDF '{filename}': {error}"
            ) from error
        duration_ms = (time.perf_counter() - started) * 1000
        self._ensure_text_found(markdown, filename)
        return ExtractionResult(
            markdown=markdown,
            page_count=page_count,
            pages_processed=pages_processed,
            duration_ms=duration_ms,
        )

    def _read_all_pages(self, document: pdfium.PdfDocument) -> tuple[str, int]:
        fragments = []
        pages_processed = 0
        for page in document:
            text_page = page.get_textpage()
            try:
                text = text_page.get_text_range() or ""
            finally:
                text_page.close()
                page.close()
            if text.strip():
                pages_processed += 1
            fragments.append(text)
        return "".join(fragments), pages_processed

    def _ensure_text_found(self, markdown: str, filename: str) -> None:
        if not markdown.strip():
            raise EmptyExtractionError(
                f"el PDF '{filename}' no contiene texto extraible"
                " (posiblemente escaneado como imagen)"
            )
