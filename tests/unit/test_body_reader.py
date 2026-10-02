"""Tests unitarios de ``api.body_reader`` (ISSUE-013): streaming R11.

El proyecto es síncrono a propósito (endpoint ``def`` en el threadpool
de FastAPI, pool de threads ADR-TP-5, dominio puro). Las únicas piezas
``async`` son las que el protocolo ASGI exige (``read_body`` y
``read_multipart``, y ni siquiera se testean aquí): sus decisiones de
umbral están extraídas como helpers síncronos, que es lo que estas
pruebas cubren. El loop async sobre el socket y el flujo completo se
ejercitan por HTTP en ``tests/integration/`` (así la suite no necesita
pytest-asyncio).
"""

from types import SimpleNamespace

import pytest

from api.body_reader import (
    _build_multipart_parser,
    _declared_length,
    _ensure_declared_within,
    _ensure_not_empty,
    _ensure_room,
    sanitize_filename,
)
from core.exceptions import EmptyBodyError, FileTooLargeError, MissingFileFieldError

MAX_BYTES = 1024 * 1024  # tope de 1 MB para las pruebas
_BOUNDARY = b"----unitboundary"


def multipart_body(content: bytes, filename: str | None = "doc.pdf") -> bytes:
    """Body multipart válido con el campo ``file`` (filename opcional)."""
    disposition = b'Content-Disposition: form-data; name="file"'
    if filename is not None:
        disposition += b'; filename="' + filename.encode() + b'"'
    return (
        b"--" + _BOUNDARY + b"\r\n" + disposition + b"\r\n"
        b"Content-Type: application/pdf\r\n\r\n"
        + content
        + b"\r\n--" + _BOUNDARY + b"--\r\n"
    )


def collect_multipart(body: bytes) -> tuple[bytes, str]:
    """Idéntico a ``read_multipart`` pero alimentando bytes síncronos."""
    parser, collector = _build_multipart_parser(MAX_BYTES, _BOUNDARY)
    for start in range(0, len(body), 7):
        parser.write(body[start : start + 7])
    parser.finalize()
    return collector.result()


class TestDeclaredLength:
    def test_missing_header_yields_none(self):
        request = SimpleNamespace(headers={})

        assert _declared_length(request) is None

    def test_non_numeric_header_yields_none(self):
        request = SimpleNamespace(headers={"content-length": "12 MB"})

        assert _declared_length(request) is None

    def test_valid_header_is_parsed(self):
        request = SimpleNamespace(headers={"content-length": "524288"})

        assert _declared_length(request) == 524288


class TestThresholdHelpers:
    def test_declared_length_over_cap_raises(self):
        with pytest.raises(FileTooLargeError):
            _ensure_declared_within(MAX_BYTES + 1, MAX_BYTES)

    def test_declared_length_at_cap_is_accepted(self):
        _ensure_declared_within(MAX_BYTES, MAX_BYTES)

    def test_missing_declared_length_is_accepted(self):
        _ensure_declared_within(None, MAX_BYTES)

    def test_room_at_the_exact_cap_is_accepted(self):
        _ensure_room(MAX_BYTES - 4, 4, MAX_BYTES)

    def test_room_one_byte_over_the_cap_raises(self):
        with pytest.raises(FileTooLargeError):
            _ensure_room(MAX_BYTES, 1, MAX_BYTES)

    def test_empty_content_raises(self):
        with pytest.raises(EmptyBodyError):
            _ensure_not_empty(b"")

    def test_non_empty_content_passes(self):
        _ensure_not_empty(b"%PDF-")


class TestMultipartParsing:
    def test_extracts_the_file_part_with_filename(self):
        content = b"%PDF-1.4 datos"

        payload, filename = collect_multipart(multipart_body(content))

        assert payload == content
        assert filename == "doc.pdf"

    def test_missing_file_field_raises(self):
        body = (
            b"--" + _BOUNDARY + b"\r\n"
            b'Content-Disposition: form-data; name="nota"\r\n\r\n'
            b"hola\r\n--" + _BOUNDARY + b"--\r\n"
        )

        with pytest.raises(MissingFileFieldError):
            collect_multipart(body)

    def test_file_without_filename_raises(self):
        with pytest.raises(MissingFileFieldError):
            collect_multipart(multipart_body(b"%PDF-1.4", filename=None))

    def test_empty_file_part_raises(self):
        with pytest.raises(EmptyBodyError):
            collect_multipart(multipart_body(b""))

    def test_file_above_cap_is_aborted(self):
        content = b"x" * (MAX_BYTES + 1)

        with pytest.raises(FileTooLargeError):
            collect_multipart(multipart_body(content, filename="big.pdf"))


class TestSanitizeFilename:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("../../etc/passwd", "passwd"),
            ("..\\..\\etc\\passwd", "passwd"),
            ("doc.pdf", "doc.pdf"),
            ("", "documento.pdf"),
        ],
    )
    def test_returns_only_the_basename(self, raw, expected):
        assert sanitize_filename(raw) == expected

    def test_strips_control_bytes_and_newlines(self):
        name = sanitize_filename("reporte.pdf\x00\r\n.doc")

        assert "\n" not in name and "\r" not in name and "\x00" not in name
        assert name == "reporte.pdf.doc"

    def test_long_names_are_truncated(self):
        assert len(sanitize_filename("a" * 300 + ".pdf")) <= 128