"""Tests de los schemas de la frontera HTTP (API v1).

Verifican que la decodificación de base64 ocurre en la frontera:
ExtractRequest expone ``content`` en bytes listo para el dominio.
"""

import base64

import pytest
from pydantic import ValidationError

from api.v1.schemas import ErrorResponse, ExtractRequest, ExtractResponse

VALID_PDF_SNIPPET = b"%PDF-1.4 hola dominio"
VALID_B64 = base64.b64encode(VALID_PDF_SNIPPET).decode()


class TestExtractRequestDecoding:
    def test_decodes_base64_to_content_bytes(self):
        request = ExtractRequest(
            filename="reporte.pdf", content_base64=VALID_B64
        )
        assert request.content == VALID_PDF_SNIPPET
        assert isinstance(request.content, bytes)

    def test_keeps_original_base64_field(self):
        request = ExtractRequest(
            filename="reporte.pdf", content_base64=VALID_B64
        )
        assert request.content_base64 == VALID_B64

    def test_empty_base64_is_invalid(self):
        with pytest.raises(ValidationError):
            ExtractRequest(filename="doc.pdf", content_base64="")


class TestExtractRequestErrors:
    @pytest.mark.parametrize(
        "bad_payload",
        [
            "esto no es base64!!!",
            "JVBERi0xLj",  # padding incorrecto (longitud no canónica)
            "###",
        ],
    )
    def test_invalid_base64_raises_validation_error(self, bad_payload):
        with pytest.raises(ValidationError) as exc_info:
            ExtractRequest(filename="doc.pdf", content_base64=bad_payload)
        errors = exc_info.value.errors()
        assert any(error["loc"] == ("content_base64",) for error in errors)

    def test_missing_filename_raises_validation_error(self):
        with pytest.raises(ValidationError):
            ExtractRequest(content_base64=VALID_B64)

    def test_filename_must_not_be_empty(self):
        with pytest.raises(ValidationError):
            ExtractRequest(filename="", content_base64=VALID_B64)


class TestExtractResponse:
    def test_serializes_to_dict(self):
        response = ExtractResponse(
            filename="doc.pdf", markdown="texto extraido", page_count=2
        )
        data = response.model_dump()
        assert data == {
            "filename": "doc.pdf",
            "markdown": "texto extraido",
            "page_count": 2,
        }

    def test_roundtrip_serialization(self):
        original = ExtractResponse(
            filename="doc.pdf", markdown="texto", page_count=1
        )
        restored = ExtractResponse.model_validate(original.model_dump())
        assert restored == original

    def test_json_serialization(self):
        response = ExtractResponse(filename="doc.pdf", markdown="texto", page_count=1)
        assert '"markdown"' in response.model_dump_json()


class TestErrorResponse:
    def test_builds_error_payload(self):
        error = ErrorResponse(error_code="CORRUPT_FILE", message="pdf dañado")
        assert error.model_dump() == {
            "error_code": "CORRUPT_FILE",
            "message": "pdf dañado",
        }

    def test_reusable_for_any_error_code(self):
        for code in ("UNSUPPORTED_FORMAT", "FILE_TOO_LARGE", "EMPTY_EXTRACTION"):
            error = ErrorResponse(error_code=code, message="detalle")
            assert error.error_code == code


class TestOpenApiDocumentation:
    def test_models_expose_json_schema_examples(self):
        for model in (ExtractRequest, ExtractResponse, ErrorResponse):
            schema = model.model_json_schema()
            assert "example" in schema
