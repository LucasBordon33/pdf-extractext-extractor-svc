"""Tests de integración controlada del adaptador PdfiumPdfToMarkdown.

"Controlada": PDFs generados en memoria por ``tests/fixtures/pdf_factory``
(sin I/O de disco), procesados por el extractor REAL (pdfium). El dominio
no participa: aquí se valida el adaptador contra el contrato del puerto.
"""

import pytest

from adapters.extractors.pdf_extractor import PdfiumPdfToMarkdown
from core.exceptions import CorruptFileError, EmptyExtractionError
from domain.models.extraction_result import ExtractionResult
from domain.ports.text_extractor import PdfToMarkdown
from tests.fixtures.pdf_factory import (
    blank_pdf,
    encrypted_pdf,
    pdf_with_text,
)


@pytest.fixture
def extractor() -> PdfToMarkdown:
    return PdfiumPdfToMarkdown()


class TestContract:
    def test_implements_pdf_to_markdown_port(self, extractor):
        assert isinstance(extractor, PdfToMarkdown)


class TestSuccessfulExtraction:
    def test_returns_enriched_extraction_result(self, extractor):
        result = extractor.extract(pdf_with_text("Hola dominio"), "doc.pdf")

        assert isinstance(result, ExtractionResult)
        assert "Hola dominio" in result.markdown
        assert result.page_count == 1
        assert result.pages_processed == 1

    def test_duration_ms_is_measured_and_non_negative(self, extractor):
        result = extractor.extract(pdf_with_text("abc"), "doc.pdf")

        assert result.duration_ms >= 0.0

    def test_reports_page_count_of_multipage_pdf(self, extractor):
        pdf = pdf_with_text("pagina uno", "pagina dos")
        result = extractor.extract(pdf, "multi.pdf")

        assert result.page_count == 2
        assert "pagina uno" in result.markdown
        assert "pagina dos" in result.markdown

    def test_preserves_page_order(self, extractor):
        """Pin de línea de base (ISSUE-022): el orden de páginas se
        conserva en el texto concatenado."""
        pdf = pdf_with_text("primero", "segundo")
        result = extractor.extract(pdf, "orden.pdf")

        assert result.markdown.index("primero") < result.markdown.index("segundo")

    def test_pages_processed_excludes_pages_without_text(self, extractor):
        """Una página en blanco dentro de un PDF mixto no aporta texto:
        page_count la cuenta, pages_processed no."""
        pdf = pdf_with_text("", "con texto")
        result = extractor.extract(pdf, "mixto.pdf")

        assert result.page_count == 2
        assert result.pages_processed == 1


class TestCorruptPdfs:
    @pytest.mark.parametrize(
        "payload",
        [b"", b"esto no es un pdf", b"%PDF-1.4 truncado sin xref"],
        ids=["vacio", "basura", "truncado"],
    )
    def test_corrupt_content_raises_corrupt_file_error(self, extractor, payload):
        with pytest.raises(CorruptFileError) as exc_info:
            extractor.extract(payload, "corrupto.pdf")
        assert "corrupto.pdf" in str(exc_info.value)


class TestPdfsWithoutText:
    def test_scanned_like_pdf_raises_empty_extraction_error(self, extractor):
        """Página en blanco ≈ PDF escaneado: sin capa de texto extraíble."""
        with pytest.raises(EmptyExtractionError):
            extractor.extract(blank_pdf(), "escaneado.pdf")


class TestRestrictedPdfs:
    def test_pdf_with_empty_user_password_is_processed(self, extractor):
        """Permisos restringidos pero legible: extrae (nada) y reporta vacío."""
        with pytest.raises(EmptyExtractionError):
            extractor.extract(encrypted_pdf(user_password=""), "protegido.pdf")

    def test_pdf_with_unknown_password_raises_corrupt_file_error(self, extractor):
        with pytest.raises(CorruptFileError):
            extractor.extract(encrypted_pdf(user_password="secreto"), "bloqueado.pdf")
