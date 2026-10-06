"""Tests de dominio puro para DocumentService (contrato de delegación).

El extractor se simula con ``unittest.mock`` anclado al contrato
``PdfToMarkdown`` (``spec=``); el pool con el doble inmediato de
``tests.doubles``. Sin PDFs reales, sin pdfium, sin HTTP.
"""

from unittest.mock import Mock

import pytest

from core.exceptions import CorruptFileError, EmptyExtractionError
from domain.models.extraction_result import ExtractionResult
from domain.ports.text_extractor import PdfToMarkdown
from tests.unit.doubles import make_document_service

RESULT = ExtractionResult(
    markdown="texto extraído",
    page_count=2,
    pages_processed=2,
    duration_ms=7.5,
)


@pytest.fixture
def extractor() -> Mock:
    """Doble del puerto: cumple el contrato por construction (spec)."""
    return Mock(spec=PdfToMarkdown)


class TestHappyPath:
    def test_returns_enriched_result_from_extractor(self, extractor):
        extractor.extract.return_value = RESULT
        service = make_document_service(extractor)

        result = service.extract(content=b"%PDF-1.4 ...", filename="doc.pdf")

        assert result == RESULT

    def test_delegates_exact_content_and_filename(self, extractor):
        extractor.extract.return_value = RESULT
        service = make_document_service(extractor)
        content = b"%PDF-1.4 bytes crudos"
        filename = "reporte.pdf"

        service.extract(content, filename)

        extractor.extract.assert_called_once_with(content, filename)


class TestErrorPropagation:
    @pytest.mark.parametrize(
        ("error_class", "error_code"),
        [
            (CorruptFileError, "CORRUPT_FILE"),
            (EmptyExtractionError, "EMPTY_EXTRACTION"),
        ],
        ids=["corrupt-file", "empty-extraction"],
    )
    def test_rethrows_extractor_domain_errors_unchanged(
        self, extractor, error_class, error_code
    ):
        domain_error = error_class("fallo")
        extractor.extract.side_effect = domain_error
        service = make_document_service(extractor)

        with pytest.raises(error_class) as exc_info:
            service.extract(b"contenido", "doc.pdf")

        assert exc_info.value is domain_error


class TestTrustsInput:
    def test_does_not_validate_content_or_filename(self, extractor):
        """Solo valida tamaño; formato y contenido se delegan al extractor."""
        extractor.extract.return_value = RESULT
        service = make_document_service(extractor)

        service.extract(content=b"", filename="")

        extractor.extract.assert_called_once_with(b"", "")
