"""Tests de backpressure de punta a punta: lo que el cliente ve.

Hay dos controles de rechazo y cada uno necesita una configuración
distinta para poder dispararse, porque se评测 evalúan en momentos
distintos de la petición:

- **Admisión (429)**: el request espera por un lugar de extracción. Si
  la espera vence → ``OverloadedError``. Se dispara con pocos lugares.
- **Cola del pool (503)**: el request ya tiene lugar y el trabajo no
  entra al pool → ``QueueSaturatedError``. Se dispara con cola chica
  y **muchos** lugares de admisión, porque un lugar por request es lo
  que vuelve inalcanzable el tope de la cola.

Sin esa distinción ambos tests son invisibles: con un solo lugar de
admisión nunca se acumulan trabajos pendientes, y con una cola
generosa nunca se satura. Es también la razón por la que el 503 solo
es alcanzable si ``QUEUE_MAX_SIZE < MAX_CONCURRENT_EXTRACTIONS``.

El extractor es lento a propósito: la ráfaga de peticiones es la que
llena los topes, no la CPU.
"""

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

API_URL = "/extract"
PDF_CONTENT_TYPE = "application/pdf"
SATURATED_STATUS = 503
SATURATED_CODE = "QUEUE_SATURATED"
OVERLOADED_STATUS = 429
OVERLOADED_CODE = "OVERLOADED"
RETRY_AFTER = "1"
CLIENT_TIMEOUT_SECONDS = 30

_DEFAULT_EXTRACTION_SECONDS = 1.0


class SlowExtractor(PdfToMarkdown):
    """Extractor que tarda lo suficiente para que la ráfaga se acumule."""

    def __init__(self, seconds: float = _DEFAULT_EXTRACTION_SECONDS) -> None:
        self._seconds = seconds

    def extract(self, content: bytes, filename: str) -> ExtractionResult:
        time.sleep(self._seconds)
        return ExtractionResult(
            markdown="contenido",
            page_count=1,
            pages_processed=1,
            duration_ms=self._seconds * 1000,
        )


def raw_payload(content: bytes) -> dict:
    """Kwargs de POST para enviar el PDF como binario crudo (R2)."""
    return {"content": content, "headers": {"content-type": PDF_CONTENT_TYPE}}


def build_app(
    *,
    max_concurrent: int,
    admission_timeout: float,
    queue_depth: int,
    extraction_seconds: float = _DEFAULT_EXTRACTION_SECONDS,
):
    """App de un solo proceso con los topes de backpressure a elección."""
    pool = ThreadPoolExtractionPool(
        max_workers=1, max_concurrent=1, max_queue_depth=queue_depth
    )
    register(
        DocumentService,
        DocumentService(
            SlowExtractor(extraction_seconds),
            pool,
            max_upload_size_mb=12,
            extract_timeout_seconds=25.0,
            max_concurrent_extractions=max_concurrent,
            admission_timeout_seconds=admission_timeout,
        ),
    )
    return create_app()


def burst(app, payload: dict, requests: int) -> list:
    """Dispara ``requests`` llamadas simultáneas y devuelve las respuestas."""
    responses: list = []
    guard = threading.Lock()
    start = threading.Event()

    def call() -> None:
        start.wait(timeout=5)
        with TestClient(app) as client:
            response = client.post(API_URL, **payload)
        with guard:
            responses.append(response)

    threads = [threading.Thread(target=call) for _ in range(requests)]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join(timeout=CLIENT_TIMEOUT_SECONDS)
    return responses


def statuses(responses: list) -> list[int]:
    return sorted(response.status_code for response in responses)


def codes(responses: list, status: int) -> list[dict]:
    return [r.json() for r in responses if r.status_code == status]


def payload_for(text: str = "hola") -> dict:
    return raw_payload(pdf_with_text(text))


@pytest.fixture
def saturated_app():
    """Cola de 1 con admision amplia: el tope que salta es el del pool."""
    return build_app(
        max_concurrent=8, admission_timeout=10.0, queue_depth=1
    )


@pytest.fixture
def overloaded_app():
    """Un solo lugar y espera mínima: el tope que salta es la admisión."""
    return build_app(
        max_concurrent=1, admission_timeout=0.05, queue_depth=64
    )


class TestQueueSaturationIsVisibleToTheClient:
    def test_full_queue_returns_503_instead_of_hanging(self, saturated_app):
        responses = burst(saturated_app, payload_for(), 4)

        assert len(responses) == 4
        assert statuses(responses) == [200, 503, 503, 503]

    def test_saturated_response_carries_retry_after(self, saturated_app):
        responses = burst(saturated_app, payload_for(), 4)

        saturated = [r for r in responses if r.status_code == SATURATED_STATUS]
        assert saturated
        for response in saturated:
            assert response.headers["Retry-After"] == RETRY_AFTER

    def test_saturated_body_is_a_normalized_error(self, saturated_app):
        responses = burst(saturated_app, payload_for(), 4)

        bodies = codes(responses, SATURATED_STATUS)
        assert len(bodies) == 3
        for body in bodies:
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
        responses = burst(saturated_app, payload_for(), 4)
        elapsed = time.monotonic() - started

        assert SATURATED_STATUS in statuses(responses)
        assert elapsed < CLIENT_TIMEOUT_SECONDS

    def test_queue_recovers_after_the_burst_drains(self, saturated_app):
        burst(saturated_app, payload_for(), 4)

        with TestClient(saturated_app) as client:
            recovered = client.post(API_URL, **payload_for())

        assert recovered.status_code == 200
        assert "Retry-After" not in recovered.headers


class TestAdmissionIsVisibleToTheClient:
    def test_no_free_slot_returns_429_with_retry_after(self, overloaded_app):
        responses = burst(overloaded_app, payload_for(), 4)

        assert statuses(responses) == [200, 429, 429, 429]
        for response in responses:
            if response.status_code == OVERLOADED_STATUS:
                assert response.headers["Retry-After"] == RETRY_AFTER

    def test_overloaded_body_is_a_normalized_error(self, overloaded_app):
        responses = burst(overloaded_app, payload_for(), 4)

        bodies = codes(responses, OVERLOADED_STATUS)
        assert len(bodies) == 3
        for body in bodies:
            assert set(body) == {"error_code", "message"}
            assert body["error_code"] == OVERLOADED_CODE
            assert "lugar de extraccion" in body["message"]

    def test_overload_responds_well_before_the_client_timeout(
        self, overloaded_app
    ):
        started = time.monotonic()
        responses = burst(overloaded_app, payload_for(), 4)
        elapsed = time.monotonic() - started

        assert OVERLOADED_STATUS in statuses(responses)
        assert elapsed < CLIENT_TIMEOUT_SECONDS

    def test_request_waits_for_a_slot_and_then_succeeds(self):
        """Con espera suficiente el 429 no debe aparecer: el trabajo entra."""
        app = build_app(
            max_concurrent=1,
            admission_timeout=10.0,
            queue_depth=64,
            extraction_seconds=0.4,
        )

        responses = burst(app, payload_for(), 2)

        assert statuses(responses) == [200, 200]
        for response in responses:
            assert "Retry-After" not in response.headers

    def test_service_recovers_after_the_burst_drains(self, overloaded_app):
        burst(overloaded_app, payload_for(), 4)

        with TestClient(overloaded_app) as client:
            recovered = client.post(API_URL, **payload_for())

        assert recovered.status_code == 200
