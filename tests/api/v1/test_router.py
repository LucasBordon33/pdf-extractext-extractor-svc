"""Tests del endpoint POST /api/v1/extract.

El servicio de dominio se dobla con un stub via dependency override:
el router se prueba sin PyPDF2 ni I/O. Los handlers de excepciones se
prueban con la app completa via TestClient.
"""

import base64

from fastapi.testclient import TestClient

from core.exceptions import (
    CorruptFileError,
    EmptyExtractionError,
    FileTooLargeError,
)
from domain.ports.text_extractor import TextExtractor


class StubExtractor(TextExtractor):
    """Extractor doble: devuelve texto fijo o lanza un error."""

    def __init__(self, result: str = "texto del pdf", error: Exception | None = None):
        self._result = result
        self._error = error

    def extract(self, content: bytes, filename: str) -> str:
        if self._error is not None:
            raise self._error
        return self._result


def make_client(extractor: TextExtractor) -> TestClient:
    from api.app import create_app
    from api.dependencies import get_document_service

    app = create_app()
    app.dependency_overrides[get_document_service] = lambda: _service_from(extractor)
    # raise_server_exceptions=False: el handler de Exception envia el 500
    # pero Starlette siempre re-lanza; asi probamos la respuesta real.
    return TestClient(app, raise_server_exceptions=False)


def _service_from(extractor: TextExtractor):
    from domain.services.document_service import DocumentService

    return DocumentService(extractor)


def valid_body() -> dict:
    return {
        "filename": "reporte.pdf",
        "content_base64": base64.b64encode(b"%PDF-1.4 contenido").decode(),
    }


class TestHappyPath:
    def test_returns_200_with_extracted_text(self):
        client = make_client(StubExtractor(result="hola mundo"))
        response = client.post("/api/v1/extract", json=valid_body())
        assert response.status_code == 200
        assert response.json() == {"filename": "reporte.pdf", "text": "hola mundo"}

    def test_content_type_is_json(self):
        client = make_client(StubExtractor())
        response = client.post("/api/v1/extract", json=valid_body())
        assert response.headers["content-type"].startswith("application/json")


class TestValidationErrors:
    def test_invalid_base64_returns_422_with_error_response(self):
        client = make_client(StubExtractor())
        response = client.post(
            "/api/v1/extract",
            json={"filename": "doc.pdf", "content_base64": "###"},
        )
        assert response.status_code == 422
        body = response.json()
        assert "error_code" in body
        assert "message" in body

    def test_missing_filename_returns_422(self):
        client = make_client(StubExtractor())
        response = client.post(
            "/api/v1/extract",
            json={"content_base64": valid_body()["content_base64"]},
        )
        assert response.status_code == 422


class TestDomainErrors:
    def test_corrupt_file_returns_400_with_error_response(self):
        extractor = StubExtractor(error=CorruptFileError("pdf dañado"))
        client = make_client(extractor)
        response = client.post("/api/v1/extract", json=valid_body())
        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "CORRUPT_FILE"
        assert "pdf dañado" in body["message"]

    def test_file_too_large_returns_413_with_error_response(self):
        extractor = StubExtractor(error=FileTooLargeError("excede 10 MB"))
        client = make_client(extractor)
        response = client.post("/api/v1/extract", json=valid_body())
        assert response.status_code == 413
        assert response.json()["error_code"] == "FILE_TOO_LARGE"

    def test_empty_extraction_returns_422_with_error_response(self):
        extractor = StubExtractor(error=EmptyExtractionError("sin texto"))
        client = make_client(extractor)
        response = client.post("/api/v1/extract", json=valid_body())
        assert response.status_code == 422
        assert response.json()["error_code"] == "EMPTY_EXTRACTION"


class TestUnexpectedErrors:
    def test_unexpected_exception_returns_500_without_leaking_details(self):
        extractor = StubExtractor(error=RuntimeError("secreto interno"))
        client = make_client(extractor)
        response = client.post("/api/v1/extract", json=valid_body())
        assert response.status_code == 500
        body = response.json()
        assert body["error_code"] == "INTERNAL_ERROR"
        assert "secreto interno" not in body["message"]


class TestOpenApi:
    def test_endpoint_documents_response_model(self):
        client = make_client(StubExtractor())
        schema = client.get("/openapi.json").json()
        operation = schema["paths"]["/api/v1/extract"]["post"]
        ref = operation["responses"]["200"]["content"]["application/json"]["schema"]
        assert ref["$ref"] == "#/components/schemas/ExtractResponse"
        assert "400" in operation["responses"]
        assert "413" in operation["responses"]
        assert "422" in operation["responses"]
        assert "500" in operation["responses"]
