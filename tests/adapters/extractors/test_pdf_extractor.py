"""Tests de integración controlada del adaptador PdfTextExtractor.

"Controlada": PDFs generados en memoria por ``tests/fixtures/pdf_factory``
(sin I/O de disco), procesados por el extractor REAL (PyPDF2). El dominio
no participa: aquí se valida el adaptador contra el contrato del puerto.
"""

import pytest

from adapters.extractors.pdf_extractor import PdfTextExtractor
from core.exceptions import CorruptFileError, EmptyExtractionError
from domain.ports.text_extractor import TextExtractor
from tests.fixtures.pdf_factory import (
    blank_pdf,
    encrypted_pdf,
    pdf_with_text,
)


@pytest.fixture
def extractor() -> TextExtractor:
    return PdfTextExtractor()


class TestContract:
    def test_implements_text_extractor_port(self, extractor):
        assert isinstance(extractor, TextExtractor)


class TestSuccessfulExtraction:
    def test_extracts_text_from_valid_pdf(self, extractor):
        text = extractor.extract(pdf_with_text("Hola dominio"), "doc.pdf")
        assert "Hola dominio" in text

    def test_returns_string_type(self, extractor):
        result = extractor.extract(pdf_with_text("abc"), "doc.pdf")
        assert isinstance(result, str)

    def test_concatenates_text_from_all_pages(self, extractor):
        pdf = pdf_with_text("pagina uno", "pagina dos")
        text = extractor.extract(pdf, "multi.pdf")
        assert "pagina uno" in text
        assert "pagina dos" in text


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
