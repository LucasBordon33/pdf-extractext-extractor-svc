"""Adaptador de extracción para documentos PDF.

Motor: pypdfium2 (ADR-TP-1) — binding a PDFium, el motor de Chromium.
Cumple el puerto ``PdfToMarkdown`` devolviendo un ``ExtractionResult``
enriquecido (markdown, páginas, duración del algoritmo puro).

Gestión de memoria bajo carga:

- ``content`` se envuelve en ``BytesIO`` UNA sola vez, sin ``.getvalue()``
  ni buffers duplicados.
- ``autoclose=True``: al cerrar el documento, pdfium cierra el stream.
- Los ``textpage`` (el objeto nativo que más memoria retiene) se cierran
  DENTRO del bucle, via un generador perezoso: el pico de memoria es
  una página de texto a la vez, nunca el PDF completo duplicado.
- Toda la dependencia de la librería queda confinada en este módulo.
"""

import threading
import time
from io import BytesIO
from math import inf

import pypdfium2 as pdfium

from adapters.markdown.block_classifier import classify_blocks
from adapters.markdown.markdown_builder import build_document, build_page_markdown
from adapters.markdown.page_segmenter import segment_page
from core.exceptions import CorruptFileError, EmptyExtractionError
from domain.models.extraction_result import ExtractionResult
from domain.ports.text_extractor import PdfToMarkdown

# Bounds sin limite: recupera texto aunque el contenido se dibuje
# fuera de la caja de la pagina (get_text_bounded sin args trunca).
_UNBOUNDED_LEFT = -inf
_UNBOUNDED = inf

# PDFium (la libreria nativa) NO es thread-safe: dos extracciones
# concurrentes en el mismo proceso producen `PdfiumError: Data format
# error` espurios sobre PDFs validos (observado bajo spike: 400
# CORRUPT_FILE intermittentes). La seccion pdfium queda serializada por
# proceso; el paralelismo real lo aportan los workers/replicas, no los
# threads del pool.
_PDFIUM_LOCK = threading.Lock()


class PdfTextExtractor(PdfToMarkdown):
    """Extrae texto de PDFs con pdfium, con métricas y memoria acotada."""

    def extract(self, content: bytes, filename: str) -> ExtractionResult:
        started = time.perf_counter()
        try:
            with _PDFIUM_LOCK:
                with pdfium.PdfDocument(BytesIO(content), autoclose=True) as document:
                    page_count = len(document)
                    page_markdowns, pages_processed = self._render_pages(document)
        except pdfium.PdfiumError as error:
            # PdfiumError hereda de RuntimeError: se traduce SIEMPRE aqui
            # para que la infraestructura no escape del adaptador.
            raise CorruptFileError(
                f"no se pudo procesar el PDF '{filename}': {error}"
            ) from error
        duration_ms = (time.perf_counter() - started) * 1000
        markdown = build_document(page_markdowns)
        self._ensure_text_found(markdown, filename)
        return ExtractionResult(
            markdown=markdown,
            page_count=page_count,
            pages_processed=pages_processed,
            duration_ms=duration_ms,
        )

    def _render_pages(self, document: pdfium.PdfDocument) -> tuple[list[str], int]:
        """Pipeline Markdown por página, liberando recursos en el bucle.

        El pico de memoria nativa es de UNA página a la vez: cada
        textpage se cierra antes de pasar a la siguiente.
        """
        page_markdowns = []
        pages_processed = 0
        for page in document:
            text_page = page.get_textpage()
            try:
                blocks = segment_page(text_page)
                page_markdown = build_page_markdown(classify_blocks(blocks))
            finally:
                text_page.close()
                page.close()
            if page_markdown.strip():
                pages_processed += 1
            page_markdowns.append(page_markdown)
        return page_markdowns, pages_processed

    def _ensure_text_found(self, markdown: str, filename: str) -> None:
        if not markdown.strip():
            raise EmptyExtractionError(
                f"el PDF '{filename}' no contiene texto extraible"
                " (posiblemente escaneado como imagen)"
            )
