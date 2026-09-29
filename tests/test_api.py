"""Tests end-to-end de la app completa.

Request realista: JSON con base64 via TestClient contra ``main.app``
(wiring de producción: DocumentService + PdfTextExtractor reales).
Sin overrides de dependencias: se valida la cadena completa
HTTP → frontera (schemas) → dominio → infraestructura (PyPDF2).
"""

import base64

import pytest
from fastapi.testclient import TestClient

import main
from tests.fixtures.pdf_factory import blank_pdf, pdf_with_text

API_URL = "/api/v1/extract"
EXPECTED_TEXT = "contenido esperado del documento"


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Una sola app para todo el módulo: es stateless."""
    return TestClient(main.app)


def extract_body(content: bytes, filename: str = "doc.pdf") -> dict:
    """Serializa el payload como lo hace un cliente real: base64 en JSON."""
    return {
        "filename": filename,
        "content_base64": base64.b64encode(content).decode(),
    }


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
    def test_valid_pdf_returns_200_with_extracted_text(self, client):
        pdf = pdf_with_text(EXPECTED_TEXT)

        response = client.post(API_URL, json=extract_body(pdf))

        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == {"filename", "text"}
        assert payload["filename"] == "doc.pdf"
        assert EXPECTED_TEXT in payload["text"]

    def test_scanned_pdf_returns_422_empty_extraction(self, client):
        """PDF legible pero sin capa de texto: error de dominio E2E."""
        response = client.post(API_URL, json=extract_body(blank_pdf()))

        assert response.status_code == 422
        assert_error_response(response, "EMPTY_EXTRACTION")


class TestInvalidBase64:
    def test_undecodable_base64_returns_422_with_normalized_error(self, client):
        response = client.post(
            API_URL,
            json={"filename": "doc.pdf", "content_base64": "###INVALID###"},
        )

        assert response.status_code == 422
        payload = assert_error_response(response, "VALIDATION_ERROR")
        assert "content_base64" in payload["message"]


class TestUnparseableBinary:
    def test_non_pdf_bytes_return_400_with_normalized_error(self, client):
        """Base64 válido de binario no-PDF: la frontera acepta, el
        adaptador (PyPDF2) reporta corrupción → error de dominio."""
        response = client.post(API_URL, json=extract_body(b"not a pdf"))

        assert response.status_code == 400
        payload = assert_error_response(response, "CORRUPT_FILE")
        assert "doc.pdf" in payload["message"]


class TestNormalizedErrorBodies:
    @pytest.mark.parametrize(
        ("body", "expected_status", "expected_code"),
        [
            (
                {"filename": "doc.pdf", "content_base64": "###"},
                422,
                "VALIDATION_ERROR",
            ),
            (extract_body(b"not a pdf"), 400, "CORRUPT_FILE"),
            (extract_body(blank_pdf()), 422, "EMPTY_EXTRACTION"),
        ],
        ids=["base64-invalido", "binario-no-pdf", "pdf-sin-texto"],
    )
    def test_every_error_case_returns_error_response_shape(
        self, client, body, expected_status, expected_code
    ):
        response = client.post(API_URL, json=body)

        assert response.status_code == expected_status
        assert_error_response(response, expected_code)
