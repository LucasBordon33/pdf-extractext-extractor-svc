"""Contrato del puerto TextExtractor.

Usa una implementación fake en memoria para verificar que cualquier
adaptador concreto respeta la firma y el comportamiento de errores:
sin I/O real, tests rápidos y deterministas.
"""

import pytest

from core.exceptions import CorruptFileError, EmptyExtractionError
from domain.ports.text_extractor import TextExtractor

VALID_CONTENT = b"%PDF-1.4 contenido simulado"
EXPECTED_TEXT = "texto extraido del documento"


class FakeTextExtractor(TextExtractor):
    """Implementación de prueba del contrato del puerto."""

    def extract(self, content: bytes, filename: str) -> str:
        if not content:
            raise CorruptFileError(f"contenido invalido: {filename}")
        text = EXPECTED_TEXT if content == VALID_CONTENT else ""
        if not text.strip():
            raise EmptyExtractionError(f"sin texto: {filename}")
        return text


class TestContract:
    def test_is_abstract_and_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            TextExtractor()

    def test_subclass_without_extract_still_abstract(self):
        class Incomplete(TextExtractor):
            pass

        with pytest.raises(TypeError):
            Incomplete()

    def test_signature_accepts_content_and_filename(self):
        extractor = FakeTextExtractor()
        text = extractor.extract(VALID_CONTENT, filename="reporte.pdf")
        assert text == EXPECTED_TEXT


class TestSuccessCases:
    def test_returns_plain_text(self):
        extractor = FakeTextExtractor()
        result = extractor.extract(VALID_CONTENT, filename="reporte.pdf")
        assert isinstance(result, str)
        assert result

    def test_domain_never_sees_base64(self):
        """El puerto recibe bytes ya decodificados: pasar base64 debe
        comportarse como contenido no procesable (falta de texto)."""
        base64_payload = b"JVBERi0xLjQ="  # cómo NO debería llegar el dato
        extractor = FakeTextExtractor()
        with pytest.raises(EmptyExtractionError):
            extractor.extract(base64_payload, filename="reporte.pdf")


class TestErrorCases:
    def test_corrupt_content_raises_corrupt_file_error(self):
        extractor = FakeTextExtractor()
        with pytest.raises(CorruptFileError):
            extractor.extract(b"", filename="corrupto.pdf")

    def test_empty_extraction_raises_empty_extraction_error(self):
        extractor = FakeTextExtractor()
        with pytest.raises(EmptyExtractionError):
            extractor.extract(b"contenido sin texto util", filename="scan.pdf")
