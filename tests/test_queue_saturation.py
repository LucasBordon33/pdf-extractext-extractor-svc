"""Tests de saturación de la cola de extracción, de punta a punta.

``tests/adapters/concurrency/test_thread_pool.py`` verifica el límite en
el adaptador. Acá se verifica lo que el cliente ve: una cola llena se
traduce en 503 con ``Retry-After`` y un mensaje accionable, no en un
timeout de 30 s del lado de la herramienta de carga (ADR-TP-7).

El extractor es lento a propósito: sin saturar la CPU de verdad, la
ráfaga de peticiones es la que llena la cola.
"""

import base64
import threading
import time

import pytest
from fastapi.testclient import TestClient

from adapters.concurrency.thread_pool import ThreadPoolExtractionPool
from api.app import create_app
from api.dependencies import register
from domain.models.extraction_result import ExtractionResult
from domain.ports.text_extractor import PdfToMarkdown
from domain.services.document_service import DocumentService
from tests.fixtures.pdf_factory import pdf_with_text

API_URL = "/api/v1/extract"
SATURATED_STATUS = 503
SATURATED_CODE = "QUEUE_SATURATED"
RETRY_AFTER = "1"

_EXTRACTION_SECONDS = 1.0


class SlowExtractor(PdfToMarkdown):
    """Extractor que tarda lo suficiente para que la ráfaga se acumule."""

    def extract(self, content: bytes, filename: str) -> ExtractionResult:
        time.sleep(_EXTRACTION_SECONDS)
        return ExtractionResult(
            markdown="contenido", page_count=1, pages_processed=1, duration_ms=1000.0
        )


def extract_body(content: bytes, filename: str = "doc.pdf") -> dict:
    return {
        "filename": filename,
        "content_base64": base64.b64encode(content).decode(),
    }


def burst(app, payload: dict, requests: int) -> list:
    """Dispara ``requests`` llamadas simultáneas y devuelve las respuestas."""
    responses: list = []
    guard = threading.Lock()
    start = threading.Event()

    def call() -> None:
        start.wait(timeout=5)
        with TestClient(app) as client:
            response = client.post(API_URL, json=payload)
        with guard:
            responses.append(response)

    threads = [threading.Thread(target=call) for _ in range(requests)]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join(timeout=30)
    return responses


@pytest.fixture
def saturated_app():
    """App con un pool de 1 worker y cola de 1: la segunda ráfaga satura."""
    pool = ThreadPoolExtractionPool(
        max_workers=1, max_concurrent=1, max_queue_depth=1
    )
    register(
        DocumentService,
        DocumentService(
            SlowExtractor(),
            pool,
            max_upload_size_mb=12,
            extract_timeout_seconds=25.0,
        ),
    )
    return create_app()


class TestQueueSaturationIsVisibleToTheClient:
    def test_full_queue_returns_503_instead_of_hanging(self, saturated_app):
        responses = burst(saturated_app, extract_body(pdf_with_text("hola")), 4)

        statuses = sorted(response.status_code for response in responses)
        assert len(responses) == 4
        assert statuses[0] == 200
        assert set(statuses[1:]) == {SATURATED_STATUS}

    def test_saturated_response_carries_retry_after(self, saturated_app):
        responses = burst(saturated_app, extract_body(pdf_with_text("hola")), 4)

        saturated = [r for r in responses if r.status_code == SATURATED_STATUS]
        assert saturated
        for response in saturated:
            assert response.headers["Retry-After"] == RETRY_AFTER

    def test_saturated_body_is_a_normalized_error(self, saturated_app):
        responses = burst(saturated_app, extract_body(pdf_with_text("hola")), 4)

        body = next(
            r.json() for r in responses if r.status_code == SATURATED_STATUS
        )
        assert set(body) == {"error_code", "message"}
        assert body["error_code"] == SATURATED_CODE
        assert "cola de extraccion llena" in body["message"]

    def test_rejection_is_fast_enough_to_beat_the_client_timeout(
        self, saturated_app
    ):
        """La respuesta de saturación no puede tardar más que el timeout
        externo (30 s en Vegeta), o el cliente expira antes de oírla.
        """
        started = time.monotonic()
        responses = burst(saturated_app, extract_body(pdf_with_text("hola")), 4)
        elapsed = time.monotonic() - started

        assert any(r.status_code == SATURATED_STATUS for r in responses)
        assert elapsed < 30

    def test_queue_recovers_after_the_burst_drains(self, saturated_app):
        burst(saturated_app, extract_body(pdf_with_text("hola")), 4)

        with TestClient(saturated_app) as client:
            recovered = client.post(API_URL, json=extract_body(pdf_with_text("hola")))

        assert recovered.status_code == 200
        assert "Retry-After" not in recovered.headers
