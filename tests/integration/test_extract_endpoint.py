"""Matriz del endpoint canónico ``POST /extract`` (ISSUE-012).

Cubre los dos modos de entrada (R2: multipart/form-data y binario
crudo), la equivalencia entre ambos, la frontera (400/413/415/422),
las probes de vida y el alias de compatibilidad. Usa el wiring de
producción (``main.app``): extremo a extremo real con pypdfium2.
"""

import pytest
from fastapi.testclient import TestClient

import main
from tests.fixtures.pdf_factory import blank_pdf, pdf_with_text
from tests.integration.multipart import multipart_without_file_kwargs

API_URL = "/extract"
PDF_CONTENT_TYPE = "application/pdf"
EXPECTED_TEXT = "contenido esperado del documento"


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Una sola app para todo el módulo: es stateless."""
    return TestClient(main.app)


def assert_extract(payload: dict) -> None:
    """Exige el shape exacto R3: ``{content, page_count}``."""
    assert set(payload) == {"content", "page_count"}
    assert isinstance(payload["content"], str)
    assert isinstance(payload["page_count"], int)
    assert payload["page_count"] >= 1


def assert_error(response, expected_code: str) -> dict:
    payload = response.json()
    assert set(payload) == {"error_code", "message"}
    assert payload["error_code"] == expected_code
    return payload


class TestTwoInputModes:
    def test_multipart_returns_200_with_extract_response(self, client):
        response = client.post(
            API_URL, files={"file": ("doc.pdf", pdf_with_text(EXPECTED_TEXT), PDF_CONTENT_TYPE)}
        )

        assert response.status_code == 200
        assert_extract(response.json())
        assert EXPECTED_TEXT in response.json()["content"]

    def test_raw_binary_returns_200_with_extract_response(self, client):
        response = client.post(
            API_URL,
            content=pdf_with_text(EXPECTED_TEXT),
            headers={"content-type": PDF_CONTENT_TYPE},
        )

        assert response.status_code == 200
        assert_extract(response.json())
        assert EXPECTED_TEXT in response.json()["content"]

    def test_both_modes_return_identical_responses(self, client):
        """Criterio ISSUE-012: respuestas idénticas para el mismo PDF."""
        pdf = pdf_with_text(EXPECTED_TEXT)

        multipart = client.post(
            API_URL, files={"file": ("doc.pdf", pdf, PDF_CONTENT_TYPE)}
        )
        raw = client.post(
            API_URL, content=pdf, headers={"content-type": PDF_CONTENT_TYPE}
        )

        assert multipart.status_code == raw.status_code == 200
        assert multipart.json() == raw.json()

    def test_octet_stream_mode_is_also_raw_binary(self, client):
        response = client.post(
            API_URL,
            content=pdf_with_text("hola"),
            headers={"content-type": "application/octet-stream"},
        )

        assert response.status_code == 200
        assert "hola" in response.json()["content"]

    def test_missing_content_type_defaults_to_raw_binary(self, client):
        response = client.post(API_URL, content=pdf_with_text("hola"))

        assert response.status_code == 200


class TestBoundary:
    def test_empty_body_returns_400(self, client):
        response = client.post(
            API_URL, headers={"content-type": PDF_CONTENT_TYPE}
        )

        assert response.status_code == 400
        assert_error(response, "EMPTY_BODY")

    def test_multipart_without_file_field_returns_422(self, client):
        response = client.post(API_URL, **multipart_without_file_kwargs())

        assert response.status_code == 422
        assert_error(response, "MISSING_FILE")

    def test_oversized_body_returns_413(self, client):
        oversized = b"%PDF-" + (b"x" * (12 * 1024 * 1024 + 100))

        response = client.post(
            API_URL, content=oversized, headers={"content-type": PDF_CONTENT_TYPE}
        )

        assert response.status_code == 413
        assert_error(response, "FILE_TOO_LARGE")

    def test_oversized_chunked_body_without_content_length_returns_413(
        self, client
    ):
        """Chunked sin ``Content-Length``: el tope se corta durante la
        lectura, no por el header (criterio ISSUE-013)."""

        def chunked_oversized_body():
            for _ in range(13):
                yield b"x" * (1024 * 1024)  # 13 MB > tope de 12 MB

        response = client.post(API_URL, content=chunked_oversized_body())

        assert response.status_code == 413
        assert_error(response, "FILE_TOO_LARGE")

    def test_chunked_body_without_content_length_is_accepted(self, client):
        """Un PDF válido chunked viaja y se procesa igual que con header."""
        pdf = pdf_with_text("chunked")

        parts = (part for part in (pdf[:10], pdf[10:]))
        response = client.post(API_URL, content=parts)

        assert response.status_code == 200
        assert "chunked" in response.json()["content"]

    def test_oversized_multipart_file_returns_413(self, client):
        oversized = b"%PDF-" + (b"x" * (12 * 1024 * 1024 + 100))

        response = client.post(
            API_URL, files={"file": ("big.pdf", oversized, PDF_CONTENT_TYPE)}
        )

        assert response.status_code == 413
        assert_error(response, "FILE_TOO_LARGE")

    @pytest.mark.parametrize(
        "content",
        [b"", b"garbage", b"not a pdf at all", blank_pdf()],
        ids=["vacio", "basura", "no-pdf", "pdf-sin-texto"],
    )
    def test_unusable_pdf_bodies_map_to_a_normalized_error(self, client, content):
        if content == b"":
            expected, code = 400, "EMPTY_BODY"
        elif content.startswith(b"%PDF-"):
            expected, code = 422, "EMPTY_EXTRACTION"
        else:
            expected, code = 415, "NOT_A_PDF"

        response = client.post(
            API_URL, content=content, headers={"content-type": PDF_CONTENT_TYPE}
        )

        assert response.status_code == expected
        assert_error(response, code)


class TestProbes:
    def test_health_returns_200(self, client):
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_ready_returns_200_when_the_service_can_accept_work(self, client):
        response = client.get("/ready")

        assert response.status_code == 200
        assert response.json()["ready"] is True


class TestDeprecatedAlias:
    def test_alias_posts_extract_identically_to_the_canonical_endpoint(self, client):
        pdf = pdf_with_text(EXPECTED_TEXT)

        canonical = client.post(
            API_URL, content=pdf, headers={"content-type": PDF_CONTENT_TYPE}
        )
        alias = client.post(
            "/api/v1/extract", content=pdf, headers={"content-type": PDF_CONTENT_TYPE}
        )

        assert canonical.status_code == alias.status_code == 200
        assert canonical.json() == alias.json()

    def test_nested_v1_v1_extract_returns_404(self, client):
        response = client.post(
            "/api/v1/v1/extract",
            content=b"%PDF-1.4 x",
            headers={"content-type": PDF_CONTENT_TYPE},
        )

        assert response.status_code == 404


class TestNoLogicInTheHandler:
    def test_happy_path_never_writes_to_disk(self, client, tmp_path, monkeypatch):
        """El endpoint devuelve el resultado desde memoria: ni un archivo."""

        def watch_home() -> set:
            return set(p.name for p in tmp_path.iterdir())

        monkeypatch.chdir(tmp_path)
        before = watch_home()

        response = client.post(
            API_URL,
            content=pdf_with_text(EXPECTED_TEXT),
            headers={"content-type": PDF_CONTENT_TYPE},
        )

        assert response.status_code == 200
        assert watch_home() == before