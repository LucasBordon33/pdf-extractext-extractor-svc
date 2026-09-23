"""Tests del servicio de dominio DocumentService.

El extractor se dobla con un stub en memoria: el servicio se prueba
aislado de PyPDF2, I/O y cualquier detalle de infraestructura.
"""

import pytest

from core.exceptions import CorruptFileError, EmptyExtractionError
from domain.ports.text_extractor import TextExtractor


class StubTextExtractor(TextExtractor):
    """Doble de prueba configurable: texto fijo o excepción a lanzar."""

    def __init__(self, result: str = "", error: Exception | None = None):
        self._result = result
        self._error = error
        self.calls: list[tuple[bytes, str]] = []

    def extract(self, content: bytes, filename: str) -> str:
        self.calls.append((content, filename))
        if self._error is not None:
            raise self._error
        return self._result


@pytest.fixture
def make_service():
    from domain.services.document_service import DocumentService

    def _build(extractor: TextExtractor) -> tuple:
        return DocumentService(extractor), extractor

    return _build


class TestDelegation:
    def test_delegates_extraction_to_injected_extractor(self, make_service):
        service, stub = make_service(StubTextExtractor(result="texto"))

        service.extract_text(b"contenido-pdf", "reporte.pdf")

        assert stub.calls == [(b"contenido-pdf", "reporte.pdf")]

    def test_returns_plain_text_from_extractor(self, make_service):
        service, _ = make_service(StubTextExtractor(result="texto extraido"))

        result = service.extract_text(b"bytes", "doc.pdf")

        assert result == "texto extraido"


class TestDomainErrors:
    def test_propagates_corrupt_file_error(self, make_service):
        error = CorruptFileError("pdf dañado")
        service, _ = make_service(StubTextExtractor(error=error))

        with pytest.raises(CorruptFileError, match="pdf dañado"):
            service.extract_text(b"basura", "corrupto.pdf")

    def test_propagates_empty_extraction_error(self, make_service):
        error = EmptyExtractionError("sin texto")
        service, _ = make_service(StubTextExtractor(error=error))

        with pytest.raises(EmptyExtractionError, match="sin texto"):
            service.extract_text(b"scan", "escaneado.pdf")


class TestBoundaryRules:
    def test_service_passes_bytes_through_unchanged(self, make_service):
        """El servicio reenvía bytes crudos: nunca decodifica base64
        ni parsea JSON (eso es de la frontera API)."""
        service, stub = make_service(StubTextExtractor(result="ok"))
        raw = b"%PDF-1.4 datos crudos"

        service.extract_text(raw, "doc.pdf")

        forwarded = stub.calls[0][0]
        assert isinstance(forwarded, bytes)
        assert forwarded == raw
