"""Tests del endpoint POST /api/v1/extract.

El servicio de dominio se dobla con un stub via dependency override:
el router se prueba sin PyPDF2 ni I/O. La matriz completa (ambos modos
de entrada, frontera, probes) vive en tests/integration/test_extract_endpoint.py;
acá se verifica el mapeo de errores de dominio.
"""

import pytest
from fastapi.testclient import TestClient

from core.exceptions import (
    CorruptFileError,
    EmptyExtractionError,
    FileTooLargeError,
)
from domain.models.extraction_result import ExtractionResult
from domain.ports.text_extractor import PdfToMarkdown
from tests.integration.multipart import multipart_without_file_kwargs
from tests.unit.doubles import make_document_service

PDF_BYTES = b"%PDF-1.4 contenido"


class StubExtractor(PdfToMarkdown):
    """Extractor doble: devuelve un resultado fijo o lanza un error."""

    def __init__(self, result: str = "texto del pdf", error: Exception | None = None):
        self._result = result
        self._error = error

    def extract(self, content: bytes, filename: str) -> ExtractionResult:
        if self._error is not None:
            raise self._error
        return ExtractionResult(
            markdown=self._result, page_count=1, pages_processed=1, duration_ms=1.0
        )


def make_client(extractor: PdfToMarkdown) -> TestClient:
    from api.app import create_app
    from api.dependencies import get_document_service

    app = create_app()
    app.dependency_overrides[get_document_service] = lambda: make_document_service(
        extractor
    )
    # raise_server_exceptions=False: el handler de Exception envia el 500
    # pero Starlette siempre re-lanza; asi probamos la respuesta real.
    return TestClient(app, raise_server_exceptions=False)


API_URL = "/api/v1/extract"


def post_raw(client: TestClient, url: str = API_URL, content: bytes = PDF_BYTES):
    return client.post(url, content=content, headers={"content-type": "application/pdf"})


def post_multipart(client: TestClient, url: str = API_URL):
    return client.post(
        url, files={"file": ("reporte.pdf", PDF_BYTES, "application/pdf")}
    )


class TestExtractEndpoint:
    def test_raw_binary_returns_extract_response(self):
        client = make_client(StubExtractor(result="hola mundo"))
        response = post_raw(client)

        assert response.status_code == 200
        assert response.json() == {"content": "hola mundo", "page_count": 1}

    def test_multipart_returns_same_response_as_raw(self):
        client = make_client(StubExtractor(result="hola mundo"))

        raw = post_raw(client)
        multipart = post_multipart(client)

        assert raw.json() == multipart.json() == {"content": "hola mundo", "page_count": 1}

    def test_sets_diagnostic_headers(self):
        client = make_client(StubExtractor())
        response = post_raw(client)

        assert response.headers["X-Filename"] == "documento.pdf"
        assert response.headers["X-Replica"]


class TestBoundaryErrors:
    @pytest.mark.parametrize(
        ("request_args", "expected_status", "expected_code"),
        [
            (
                # body crudo vacio
                {"headers": {"content-type": "application/pdf"}},
                400,
                "EMPTY_BODY",
            ),
            (
                # multipart sin el campo 'file' obligatorio
                multipart_without_file_kwargs(),
                422,
                "MISSING_FILE",
            ),
            (
                # binario que no empieza con %PDF-
                {
                    "content": b"esto no es pdf",
                    "headers": {"content-type": "application/pdf"},
                },
                415,
                "NOT_A_PDF",
            ),
        ],
        ids=["body-vacio", "sin-archivo", "no-pdf"],
    )
    def test_boundary_errors_return_normalized_error(
        self, request_args, expected_status, expected_code
    ):
        client = make_client(StubExtractor())
        response = client.post(API_URL, **request_args)

        assert response.status_code == expected_status
        body = response.json()
        assert set(body) == {"error_code", "message"}
        assert body["error_code"] == expected_code


class TestDomainErrors:
    def test_corrupt_file_returns_400_with_error_response(self):
        client = make_client(StubExtractor(error=CorruptFileError("pdf dañado")))
        response = post_raw(client)

        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "CORRUPT_FILE"
        assert "pdf dañado" in body["message"]

    def test_file_too_large_returns_413_with_error_response(self):
        client = make_client(StubExtractor(error=FileTooLargeError("excede 10 MB")))
        response = post_raw(client)

        assert response.status_code == 413
        assert response.json()["error_code"] == "FILE_TOO_LARGE"

    def test_empty_extraction_returns_422_with_error_response(self):
        client = make_client(StubExtractor(error=EmptyExtractionError("sin texto")))
        response = post_raw(client)

        assert response.status_code == 422
        assert response.json()["error_code"] == "EMPTY_EXTRACTION"


class TestUnexpectedErrors:
    def test_unexpected_exception_returns_500_without_leaking_details(self):
        client = make_client(StubExtractor(error=KeyError("secreto interno")))
        response = post_raw(client)

        assert response.status_code == 500
        body = response.json()
        assert body["error_code"] == "INTERNAL_ERROR"
        assert "secreto interno" not in body["message"]


class TestOpenApi:
    def test_endpoint_documents_response_model(self):
        client = make_client(StubExtractor())
        schema = client.get("/openapi.json").json()
        operation = schema["paths"][API_URL]["post"]
        ref = operation["responses"]["200"]["content"]["application/json"]["schema"]
        assert ref["$ref"] == "#/components/schemas/ExtractResponse"
        for status_code in ("400", "413", "415", "422", "500"):
            assert status_code in operation["responses"]
