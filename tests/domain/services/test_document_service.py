"""Tests de dominio puro para DocumentService.

El extractor se simula con ``unittest.mock`` anclado al contrato
``TextExtractor`` (``spec=``): sin PDFs reales, sin base64, sin PyPDF2.
Esa lógica pertenece a la frontera (api/) y a los adaptadores; aqui
solo se verifica el contrato de delegación del dominio.
"""

from unittest.mock import Mock

import pytest

from core.exceptions import CorruptFileError, EmptyExtractionError
from domain.ports.text_extractor import TextExtractor
from domain.services.document_service import DocumentService

EXTRACTED_TEXT = "texto extraído"


@pytest.fixture
def extractor() -> Mock:
    """Doble del puerto: cumple el contrato por construction (spec)."""
    return Mock(spec=TextExtractor)


class TestHappyPath:
    def test_returns_text_from_extractor(self, extractor):
        extractor.extract.return_value = EXTRACTED_TEXT
        service = DocumentService(extractor)

        result = service.extract_text(content=b"%PDF-1.4 ...", filename="doc.pdf")

        assert result == EXTRACTED_TEXT

    def test_delegates_exact_content_and_filename(self, extractor):
        extractor.extract.return_value = "ok"
        service = DocumentService(extractor)
        content = b"%PDF-1.4 bytes crudos"
        filename = "reporte.pdf"

        service.extract_text(content, filename)

        extractor.extract.assert_called_once_with(content, filename)


class TestErrorPropagation:
    @pytest.mark.parametrize(
        "domain_error",
        [
            CorruptFileError("pdf dañado"),
            EmptyExtractionError("sin texto"),
        ],
        ids=["corrupt-file", "empty-extraction"],
    )
    def test_rethrows_extractor_domain_errors_unchanged(
        self, extractor, domain_error
    ):
        extractor.extract.side_effect = domain_error
        service = DocumentService(extractor)

        with pytest.raises(type(domain_error)) as exc_info:
            service.extract_text(b"contenido", "doc.pdf")

        assert exc_info.value is domain_error


class TestTrustsInput:
    def test_does_not_validate_content_or_filename(self, extractor):
        """El servicio no valida formato ni tamaño: esa lógica es del
        orquestador en la frontera. Cualquier entrada se delega tal cual."""
        extractor.extract.return_value = "algo"
        service = DocumentService(extractor)

        service.extract_text(content=b"", filename="")

        extractor.extract.assert_called_once_with(b"", "")

    def test_never_sees_base64_or_json(self, extractor):
        """La frontera decodifica el transporte: si llegara base64 sin
        decodificar, para el dominio son solo bytes opacos."""
        extractor.extract.return_value = "algo"
        service = DocumentService(extractor)
        raw = b"JVBERi0xLjQ="

        service.extract_text(raw, "doc.pdf")

        extractor.extract.assert_called_once_with(raw, "doc.pdf")
