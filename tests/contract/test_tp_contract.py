"""Tests de contrato del TP: la promesa pública del servicio.

Dos garantías, ambas exigidas por el enunciado:

1. **Shape exacto R3**: una respuesta 200 de ``POST /extract`` es
   exactamente ``{"content": str, "page_count": int}`` — ni un campo
   más, ni uno menos.
2. **Markdown no vacío con un PDF del dataset**: la muestra oficial
   debe producir contenido no vacío y con la estructura esperada
   (separador de páginas entre ambas).

La muestra vive versionada en ``tests/fixtures/official_sample.pdf``
(un PDF multipágina con texto real) porque el dataset oficial no es
redistribuible ni bajable en CI; el archivo es su representante y el
mismo que usa el smoke de carga de k6 (``load/k6-smoke.js``). Si la
cátedra publica el dataset, basta con reemplazar el archivo: los
asserts de contrato no cambian.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main

API_URL = "/extract"
PDF_CONTENT_TYPE = "application/pdf"

OFFICIAL_SAMPLE = (
    Path(__file__).resolve().parent.parent / "fixtures" / "official_sample.pdf"
).read_bytes()


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Wiring de producción completo: HTTP → dominio → pypdfium2."""
    return TestClient(main.app)


class TestExtractResponseContract:
    def test_multipart_response_is_exactly_content_and_page_count(self, client):
        response = client.post(
            API_URL,
            files={"file": ("dataset.pdf", OFFICIAL_SAMPLE, PDF_CONTENT_TYPE)},
        )

        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == {"content", "page_count"}
        assert isinstance(payload["content"], str)
        assert isinstance(payload["page_count"], int)

    def test_raw_binary_response_is_exactly_content_and_page_count(self, client):
        response = client.post(
            API_URL,
            content=OFFICIAL_SAMPLE,
            headers={"content-type": PDF_CONTENT_TYPE},
        )

        assert response.status_code == 200
        assert set(response.json()) == {"content", "page_count"}


class TestOfficialDatasetPdf:
    def test_dataset_pdf_produces_non_empty_markdown(self, client):
        response = client.post(
            API_URL,
            files={"file": ("dataset.pdf", OFFICIAL_SAMPLE, PDF_CONTENT_TYPE)},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["content"].strip()
        assert "Informe de extraccion de contenido del TP" in payload["content"]

    def test_dataset_pdf_reports_its_real_page_count(self, client):
        response = client.post(
            API_URL,
            content=OFFICIAL_SAMPLE,
            headers={"content-type": PDF_CONTENT_TYPE},
        )

        assert response.json()["page_count"] == 2

    def test_dataset_markdown_keeps_pages_separated(self, client):
        """El contrato de salida conserva la estructura del documento."""
        response = client.post(
            API_URL,
            content=OFFICIAL_SAMPLE,
            headers={"content-type": PDF_CONTENT_TYPE},
        )

        assert "\n---\n" in response.json()["content"]
