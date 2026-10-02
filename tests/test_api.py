"""Tests end-to-end de la app completa.

Requests reales via TestClient contra ``main.app`` (wiring de
producción: DocumentService + PdfTextExtractor reales en pypdfium2).
Sin overrides de dependencias: se valida la cadena completa
HTTP → frontera (body_reader) → dominio → infraestructura (pdfium).
El body se envía como manda el TP (R2): multipart o binario crudo.
"""

import pytest
from fastapi.testclient import TestClient

import main
from tests.fixtures.pdf_factory import blank_pdf, pdf_with_text
from tests.multipart import multipart_without_file_kwargs

API_URL = "/extract"
EXPECTED_TEXT = "contenido esperado del documento"

PDF_CONTENT_TYPE = "application/pdf"


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Una sola app para todo el módulo: es stateless."""
    return TestClient(main.app)


def post_raw(client: TestClient, content: bytes):
    return client.post(
        API_URL, content=content, headers={"content-type": PDF_CONTENT_TYPE}
    )


def assert_error_response(response, expected_code: str) -> dict:
    """Exige cuerpo normalizado ``ErrorResponse`` con el código dado."""
    payload = response.json()
    assert set(payload) == {"error_code", "message"}
    assert payload["error_code"] == expected_code
    assert payload["message"]
    return payload


class TestProductionWiring:
    def test_uses_production_wiring_without_overrides(self, client):
        """Guardián E2E: si otro test dejara overrides, esto lo delata."""
        assert main.app.dependency_overrides == {}


class TestHappyPath:
    def test_raw_binary_returns_extract_response(self, client):
        pdf = pdf_with_text(EXPECTED_TEXT)

        response = post_raw(client, pdf)

        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == {"content", "page_count"}
        assert EXPECTED_TEXT in payload["content"]
        assert payload["page_count"] == 1

    def test_multipart_returns_same_extract_as_raw_binary(self, client):
        pdf = pdf_with_text(EXPECTED_TEXT)

        raw = post_raw(client, pdf)
        multipart = client.post(
            API_URL, files={"file": ("doc.pdf", pdf, PDF_CONTENT_TYPE)}
        )

        assert raw.status_code == multipart.status_code == 200
        assert raw.json() == multipart.json()
        assert "content" in multipart.json() and multipart.json()["page_count"] == 1

    def test_sets_diagnostic_headers(self, client):
        response = post_raw(client, pdf_with_text(EXPECTED_TEXT))

        assert response.headers["X-Replica"]

    def test_multipart_sets_sanitized_filename_header(self, client):
        response = client.post(
            API_URL, files={"file": ("carpeta/../doc.pdf", pdf_with_text("x"), PDF_CONTENT_TYPE)}
        )

        assert response.status_code == 200
        assert response.headers["X-Filename"] == "doc.pdf"

    def test_scanned_pdf_returns_422_empty_extraction(self, client):
        """PDF legible pero sin capa de texto: error de dominio E2E."""
        response = post_raw(client, blank_pdf())

        assert response.status_code == 422
        assert_error_response(response, "EMPTY_EXTRACTION")


class TestBoundaryErrors:
    def test_empty_body_returns_400(self, client):
        response = client.post(
            API_URL, headers={"content-type": PDF_CONTENT_TYPE}
        )

        assert response.status_code == 400
        assert_error_response(response, "EMPTY_BODY")

    def test_multipart_without_file_field_returns_422(self, client):
        response = client.post(API_URL, **multipart_without_file_kwargs())

        assert response.status_code == 422
        assert_error_response(response, "MISSING_FILE")

    def test_non_pdf_bytes_return_415(self, client):
        response = post_raw(client, b"not a pdf")

        assert response.status_code == 415
        assert_error_response(response, "NOT_A_PDF")

    def test_oversized_body_returns_413_before_reading(self, client):
        oversized = b"%PDF-" + (b"x" * (12 * 1024 * 1024 + 100))

        response = post_raw(client, oversized)

        assert response.status_code == 413
        assert_error_response(response, "FILE_TOO_LARGE")


class TestNormalizedErrorBodies:
    @pytest.mark.parametrize(
        ("request_args", "expected_status", "expected_code"),
        [
            (multipart_without_file_kwargs(), 422, "MISSING_FILE"),
            (
                {"content": b"not a pdf", "headers": {"content-type": PDF_CONTENT_TYPE}},
                415,
                "NOT_A_PDF",
            ),
            (
                {"content": blank_pdf(), "headers": {"content-type": PDF_CONTENT_TYPE}},
                422,
                "EMPTY_EXTRACTION",
            ),
        ],
        ids=["sin-archivo", "no-pdf", "pdf-sin-texto"],
    )
    def test_every_error_case_returns_error_response_shape(
        self, client, request_args, expected_status, expected_code
    ):
        response = client.post(API_URL, **request_args)

        assert response.status_code == expected_status
        assert_error_response(response, expected_code)