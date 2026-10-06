"""Tests del contrato del TP (ISSUE-011): shapes exactos R2/R3.

Verifica los schemas de ``api/extract/schemas.py``:

- 200 OK : ``{"content": "...", "page_count": N}`` — y **ningún** otro
  campo en el body (R3).
- Errores : ``ErrorResponse{error_code, message, retry_after_seconds?}``
  consistente para todos los códigos del dominio.
- ``page_count`` con ``ge=1`` y ``retry_after_seconds`` con ``ge=0``.
- Ejemplos OpenAPI presentes para que ``/docs`` sea legible.
"""

import json

import pytest
from pydantic import ValidationError

from api.extract.schemas import ErrorResponse, ExtractResponse
from core.exceptions import DocumentExtractionError


def _all_error_classes():
    """Recolecta las subclases concretas de DocumentExtractionError."""

    def walk(cls):
        for subclass in cls.__subclasses__():
            try:
                subclass("x")
            except TypeError:
                continue
            yield subclass
            yield from walk(subclass)

    return list(walk(DocumentExtractionError))


# Cada error concreto del dominio más los dos estados extra que el
# handler puede emitir (VALIDATION_ERROR / INTERNAL_ERROR).
ALL_ERROR_CODES = sorted(
    {exc_class("x").error_code for exc_class in _all_error_classes()}
    | {"VALIDATION_ERROR", "INTERNAL_ERROR"},
)


class TestExtractResponseShape:
    def test_dumps_exact_content_and_page_count(self):
        response = ExtractResponse(content="# Titulo\n\ncuerpo", page_count=292)

        assert response.model_dump() == {
            "content": "# Titulo\n\ncuerpo",
            "page_count": 292,
        }

    def test_model_dump_roundtrip_keeps_exact_shape(self):
        original = ExtractResponse(content="md", page_count=2)
        restored = ExtractResponse.model_validate(original.model_dump())

        assert set(restored.model_dump()) == {"content", "page_count"}
        assert restored == original

    def test_required_fields_are_only_content_and_page_count(self):
        schema = ExtractResponse.model_json_schema()

        assert set(schema["required"]) == {"content", "page_count"}
        assert set(schema["properties"]) == {"content", "page_count"}

    def test_serializes_as_application_json_default(self):
        response = ExtractResponse(content="md", page_count=1)
        payload = response.model_dump_json()
        data = json.loads(payload)

        assert data == {"content": "md", "page_count": 1}

    def test_json_body_has_no_extra_fields(self):
        response = ExtractResponse.model_validate(
            {"content": "md", "page_count": 1}
        )
        assert set(json.loads(response.model_dump_json())) == {
            "content",
            "page_count",
        }


class TestExtractResponseValidation:
    def test_page_count_must_be_at_least_one(self):
        with pytest.raises(ValidationError):
            ExtractResponse(content="md", page_count=0)

    def test_page_count_rejects_negative(self):
        with pytest.raises(ValidationError):
            ExtractResponse(content="md", page_count=-1)

    def test_content_is_required(self):
        with pytest.raises(ValidationError):
            ExtractResponse(page_count=1)

    def test_page_count_must_be_integer(self):
        with pytest.raises(ValidationError):
            ExtractResponse(content="md", page_count="muchas")


class TestErrorResponseShape:
    def test_dumps_error_code_message_and_retry_hint(self):
        error = ErrorResponse(
            error_code="OVERLOADED",
            message="no hay lugar",
            retry_after_seconds=1,
        )

        assert error.model_dump() == {
            "error_code": "OVERLOADED",
            "message": "no hay lugar",
            "retry_after_seconds": 1,
        }

    def test_retry_after_seconds_is_optional_and_defaults_to_none(self):
        error = ErrorResponse(error_code="CORRUPT_FILE", message="roto")

        assert error.model_dump() == {
            "error_code": "CORRUPT_FILE",
            "message": "roto",
            "retry_after_seconds": None,
        }

    def test_required_fields_are_error_code_and_message(self):
        schema = ErrorResponse.model_json_schema()

        assert set(schema["required"]) == {"error_code", "message"}

    @pytest.mark.parametrize("code", ALL_ERROR_CODES)
    def test_is_consistent_for_every_error_code(self, code):
        """Todos los códigos de error del sistema usan el mismo shape."""
        error = ErrorResponse(error_code=code, message="detalle")

        assert set(error.model_dump()) == {
            "error_code",
            "message",
            "retry_after_seconds",
        }
        assert error.error_code == code


class TestErrorResponseValidation:
    def test_retry_after_rejects_negative(self):
        with pytest.raises(ValidationError):
            ErrorResponse(
                error_code="OVERLOADED", message="x", retry_after_seconds=-1
            )

    def test_retry_after_accepts_zero(self):
        error = ErrorResponse(
            error_code="OVERLOADED", message="x", retry_after_seconds=0
        )
        assert error.retry_after_seconds == 0

    def test_error_code_is_required(self):
        with pytest.raises(ValidationError):
            ErrorResponse(message="silencioso")


class TestOpenApiExamples:
    def test_extract_response_exposes_a_real_example(self):
        schema = ExtractResponse.model_json_schema()

        assert "example" in schema
        assert set(schema["example"]) == {"content", "page_count"}
        assert schema["example"]["page_count"] >= 1
        assert "#" in schema["example"]["content"]

    def test_error_response_exposes_an_example(self):
        schema = ErrorResponse.model_json_schema()

        assert "example" in schema
        assert "error_code" in schema["example"]
        assert "message" in schema["example"]


class TestNoLegacyBase64:
    def test_contract_schemas_do_not_mention_content_base64(self):
        import inspect

        import api.extract.schemas as module

        source = inspect.getsource(module)
        assert "content_base64" not in source
        assert "ExtractRequest" not in source