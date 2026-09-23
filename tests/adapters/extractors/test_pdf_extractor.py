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
    def test_extracts_text_from_valid_pdf(self, extractor):
        # Un PDF real con texto: usamos reportlab si está, si no, un PDF
        # mínimo con stream de texto escrito a mano.
        text = extractor.extract(_pdf_with_text("Hola dominio"), "doc.pdf")
        assert "Hola dominio" in text

    def test_returns_string_type(self, extractor):
        result = extractor.extract(_pdf_with_text("abc"), "doc.pdf")
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


def _pdf_with_text(text: str) -> bytes:
    """PDF mínimo con una página conteniendo ``text`` visible."""
    stream = f"BT /F1 12 Tf 10 40 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
        + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    buffer = BytesIO()
    buffer.write(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(buffer.tell())
        buffer.write(f"{index} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_pos = buffer.tell()
    buffer.write(f"xref\n0 {len(objects) + 1}\n".encode())
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets:
        buffer.write(f"{offset:010d} 00000 n \n".encode())
    buffer.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF".encode()
    )
    return buffer.getvalue()
