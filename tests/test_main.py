"""Tests del punto de entrada: wiring DI, handlers globales y docs."""

import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import main
from api.dependencies import get_document_service
from core.exceptions import CorruptFileError
from domain.ports.text_extractor import TextExtractor
from domain.services.document_service import DocumentService


class ExplodingExtractor(TextExtractor):
    """Doble que lanza la excepción indicada en cada extracción."""

    def __init__(self, error: Exception):
        self._error = error

    def extract(self, content: bytes, filename: str) -> str:
        raise self._error


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture
def fail_with():
    """Instala un extractor que falla; limpia el override al salir."""

    def _install(error: Exception):
        main.app.dependency_overrides[get_document_service] = lambda: (
            DocumentService(ExplodingExtractor(error))
        )

    yield _install
    main.app.dependency_overrides.pop(get_document_service, None)


def request_body(pdf_factory, text: str = "Hola desde main") -> dict:
    return {
        "filename": "reporte.pdf",
        "content_base64": base64.b64encode(pdf_factory(text)).decode(),
    }


class TestAppInitialization:
    def test_app_is_fastapi_instance(self):
        assert isinstance(main.app, FastAPI)

    def test_openapi_metadata_is_configured(self):
        assert main.app.title == "pdf-extractext-extractor-svc"
        assert main.app.version == "0.1.0"
        assert main.app.description


class TestManualDIWiring:
    def test_build_document_service_wires_real_extractor(self, pdf_factory):
        service = main.build_document_service()
        assert isinstance(service, DocumentService)
        text = service.extract_text(pdf_factory("documento real"), "doc.pdf")
        assert "documento real" in text

    def test_endpoint_resolves_registered_service(self, client, pdf_factory):
        """Integración: main → router → DocumentService → PdfTextExtractor."""
        response = client.post("/api/v1/extract", json=request_body(pdf_factory))
        assert response.status_code == 200
        assert "Hola desde main" in response.json()["text"]


class TestRouterRegistration:
    def test_extract_route_is_mounted_at_api_v1(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/v1/extract" in paths


class TestGlobalExceptionHandlers:
    def test_value_error_returns_422(self, client, fail_with, pdf_factory):
        fail_with(ValueError("valor invalido"))
        response = client.post("/api/v1/extract", json=request_body(pdf_factory))
        assert response.status_code == 422
        assert response.json()["error_code"] == "VALUE_ERROR"

    def test_runtime_error_returns_400(self, client, fail_with, pdf_factory):
        fail_with(RuntimeError("fallo en runtime"))
        response = client.post("/api/v1/extract", json=request_body(pdf_factory))
        assert response.status_code == 400
        assert response.json()["error_code"] == "RUNTIME_ERROR"

    def test_memory_error_returns_413(self, client, fail_with, pdf_factory):
        fail_with(MemoryError("sin memoria"))
        response = client.post("/api/v1/extract", json=request_body(pdf_factory))
        assert response.status_code == 413
        assert response.json()["error_code"] == "MEMORY_ERROR"

    def test_unexpected_error_returns_500_without_leaking(
        self, client, fail_with, pdf_factory
    ):
        fail_with(ZeroDivisionError("secreto interno"))
        response = client.post("/api/v1/extract", json=request_body(pdf_factory))
        assert response.status_code == 500
        body = response.json()
        assert body["error_code"] == "INTERNAL_ERROR"
        assert "secreto interno" not in body["message"]

    def test_domain_errors_keep_their_own_mapping(
        self, client, fail_with, pdf_factory
    ):
        fail_with(CorruptFileError("pdf roto"))
        response = client.post("/api/v1/extract", json=request_body(pdf_factory))
        assert response.status_code == 400
        assert response.json()["error_code"] == "CORRUPT_FILE"


class TestDocumentation:
    def test_swagger_docs_are_accessible(self, client):
        assert client.get("/docs").status_code == 200

    def test_openapi_reflects_schemas_with_examples(self, client):
        schemas = client.get("/openapi.json").json()["components"]["schemas"]
        for name in ("ExtractRequest", "ExtractResponse", "ErrorResponse"):
            assert name in schemas
        assert "example" in schemas["ExtractRequest"]
