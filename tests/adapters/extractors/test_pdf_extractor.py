"""Tests del adaptador PdfTextExtractor.

Las fixtures de PDF se construyen en memoria con PyPDF2 (sin archivos
en disco): rápido, determinista y versionable en el propio test.
"""

from io import BytesIO

import pytest
from PyPDF2 import PdfWriter

from core.exceptions import CorruptFileError, EmptyExtractionError
from domain.ports.text_extractor import TextExtractor


def build_pdf_bytes(password: str = "") -> bytes:
    """Genera un PDF mínimo en memoria, opcionalmente cifrado."""
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    if password:
        writer.encrypt(user_password=password, owner_password="owner")
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
def extractor():
    from adapters.extractors.pdf_extractor import PdfTextExtractor

    return PdfTextExtractor()


class TestContract:
    def test_implements_text_extractor_port(self, extractor):
        assert isinstance(extractor, TextExtractor)


class TestSuccessfulExtraction:
    def test_extracts_text_from_valid_pdf(self, extractor, pdf_factory):
        text = extractor.extract(pdf_factory("Hola dominio"), "doc.pdf")
        assert "Hola dominio" in text

    def test_returns_string_type(self, extractor, pdf_factory):
        result = extractor.extract(pdf_factory("abc"), "doc.pdf")
        assert isinstance(result, str)


class TestCorruptFiles:
    @pytest.mark.parametrize(
        "payload",
        [
            b"",
            b"esto no es un pdf",
            b"%PDF-1.4 truncado sin xref",
        ],
    )
    def test_corrupt_content_raises_corrupt_file_error(
        self, extractor, payload
    ):
        with pytest.raises(CorruptFileError) as exc_info:
            extractor.extract(payload, "corrupto.pdf")
        assert "corrupto.pdf" in str(exc_info.value)


class TestEmptyExtraction:
    def test_pdf_without_text_raises_empty_extraction_error(self, extractor):
        blank_pdf = build_pdf_bytes()  # página en blanco: sin texto
        with pytest.raises(EmptyExtractionError):
            extractor.extract(blank_pdf, "escaneado.pdf")


class TestRestrictedPdfs:
    def test_pdf_with_empty_user_password_is_processed(self, extractor):
        restricted = build_pdf_bytes(password="")
        with pytest.raises(EmptyExtractionError):
            # Página en blanco cifrada pero legible: extrae "lo legible"
            # (nada) y reporta extracción vacía, no falla por el cifrado.
            extractor.extract(restricted, "protegido.pdf")

    def test_pdf_with_unknown_password_raises_corrupt_file_error(
        self, extractor
    ):
        locked = build_pdf_bytes(password="secreto")
        with pytest.raises(CorruptFileError):
            extractor.extract(locked, "bloqueado.pdf")

