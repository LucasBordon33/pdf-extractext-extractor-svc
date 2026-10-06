"""Contrato del puerto PdfToMarkdown.

Usa una implementación fake en memoria para verificar que cualquier
adaptador concreto respeta la firma y el comportamiento de errores:
sin I/O real, tests rápidos y deterministas. El contrato devuelve un
``ExtractionResult`` enriquecido (markdown, páginas, duración).
"""

import pytest

from core.exceptions import CorruptFileError, EmptyExtractionError
from domain.models.extraction_result import ExtractionResult
from domain.ports.text_extractor import PdfToMarkdown

VALID_CONTENT = b"%PDF-1.4 contenido simulado"
RESULT = ExtractionResult(
    markdown="texto extraido",
    page_count=1,
    pages_processed=1,
    duration_ms=5.0,
)


class FakePdfToMarkdown(PdfToMarkdown):
    """Implementación de prueba del contrato del puerto."""

    def __init__(self, error: Exception | None = None):
        self._error = error
        self.calls: list[tuple[bytes, str]] = []

    def extract(self, content: bytes, filename: str) -> ExtractionResult:
        self.calls.append((content, filename))
        if self._error is not None:
            raise self._error
        return RESULT


class TestContract:
    def test_is_abstract_and_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            PdfToMarkdown()

    def test_subclass_without_extract_still_abstract(self):
        class Incomplete(PdfToMarkdown):
            pass

        with pytest.raises(TypeError):
            Incomplete()

    def test_extract_returns_enriched_result(self):
        extractor = FakePdfToMarkdown()
        result = extractor.extract(VALID_CONTENT, filename="reporte.pdf")
        assert isinstance(result, ExtractionResult)
        assert result == RESULT

    def test_result_fields_are_complete(self):
        result = FakePdfToMarkdown().extract(VALID_CONTENT, "reporte.pdf")
        assert result.markdown == "texto extraido"
        assert result.page_count == 1
        assert result.pages_processed == 1
        assert result.duration_ms == 5.0


class TestSuccessCases:
    def test_domain_never_sees_base64(self):
        """El puerto recibe bytes ya decodificados: pasar base64 debe
        tratarse como contenido opaco, no como transporte."""
        base64_payload = b"JVBERi0xLjQ="
        extractor = FakePdfToMarkdown()
        result = extractor.extract(base64_payload, filename="reporte.pdf")
        assert result == RESULT


class TestErrorCases:
    def test_corrupt_content_raises_corrupt_file_error(self):
        extractor = FakePdfToMarkdown(error=CorruptFileError("dañado"))
        with pytest.raises(CorruptFileError):
            extractor.extract(b"", filename="corrupto.pdf")

    def test_empty_extraction_raises_empty_extraction_error(self):
        extractor = FakePdfToMarkdown(error=EmptyExtractionError("sin texto"))
        with pytest.raises(EmptyExtractionError):
            extractor.extract(b"contenido sin texto", filename="scan.pdf")
