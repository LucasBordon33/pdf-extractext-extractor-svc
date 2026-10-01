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

import time
from collections.abc import Iterator
from io import BytesIO
from math import inf

import pypdfium2 as pdfium

from core.exceptions import CorruptFileError, EmptyExtractionError
from domain.models.extraction_result import ExtractionResult
from domain.ports.text_extractor import PdfToMarkdown

# Bounds sin limite: recupera texto aunque el contenido se dibuje
# fuera de la caja de la pagina (get_text_bounded sin args trunca).
_UNBOUNDED_LEFT = -inf
_UNBOUNDED = inf


class PdfTextExtractor(PdfToMarkdown):
    """Extrae texto de PDFs con pdfium, con métricas y memoria acotada."""

    def extract(self, content: bytes, filename: str) -> ExtractionResult:
        started = time.perf_counter()
        try:
            with pdfium.PdfDocument(BytesIO(content), autoclose=True) as document:
                page_count = len(document)
                markdown, pages_processed = self._collect_page_texts(document)
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

    def _iter_page_texts(self, document: pdfium.PdfDocument) -> Iterator[str]:
        """Entrega el texto de cada página de forma perezosa.

        Cada ``textpage`` se libera dentro del bucle: el pico de memoria
        nativa es de UNA página a la vez. El conversor a Markdown
        (ISSUE-006) consumira este generador página a página sin duplicar
        el PDF completo en memoria.
        """
        for page in document:
            text_page = page.get_textpage()
            try:
                yield text_page.get_text_bounded(
                    left=_UNBOUNDED_LEFT,
                    bottom=_UNBOUNDED_LEFT,
                    right=_UNBOUNDED,
                    top=_UNBOUNDED,
                )
            finally:
                text_page.close()
                page.close()

    def _collect_page_texts(
        self, document: pdfium.PdfDocument
    ) -> tuple[str, int]:
        pages_processed = 0
        fragments = []
        for text in self._iter_page_texts(document):
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
