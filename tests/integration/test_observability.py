"""ISSUE-014: request_id, una línea JSON por request y métricas.

Criterios de aceptación cubiertos:

- el ``X-Request-ID`` del cliente vuelve en la respuesta (correlación);
- si no viene, se genera un ``uuid4.hex``;
- el ``request_id`` aparece en la línea JSON (formateador);
- UNA línea por request con ``status`` y ``duration_ms``;
- el ``error_code`` llega a la línea cuando el response es un error;
- ``GET /metrics`` expone las siete familias en texto Prometheus
  parseable, y los contadores suben tras una tanda;
- ningún log contiene el contenido del PDF ni rutas absolutas.
"""

import json
import logging
import os

import pytest
from fastapi.testclient import TestClient

import main
from api.metrics import METRICS
from tests.fixtures.pdf_factory import pdf_with_text

API_URL = "/extract"
PDF_CONTENT_TYPE = "application/pdf"

FAMILIES = [
    "extract_requests_total",
    "extract_duration_seconds",
    "extractions_in_flight",
    "admission_wait_seconds",
    "admission_rejections_total",
    "pages_processed_total",
    "bytes_read_total",
]


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Una sola app para todo el módulo: es stateless."""
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def _reset_metrics():
    """Aislamiento: cada test arranca con contadores en cero."""
    METRICS.reset()


def _completed_records(caplog):
    return [r for r in caplog.records if r.getMessage() == "request completed"]


def _metric_value(text: str, prefix: str) -> int:
    for line in text.splitlines():
        if line.startswith(prefix):
            return int(line.split(" ", 1)[1])
    raise AssertionError(f"métrica no encontrada: {prefix!r}")


def _post_pdf(client, text: str = "hola"):
    return client.post(
        API_URL,
        content=pdf_with_text(text),
        headers={"content-type": PDF_CONTENT_TYPE},
    )


class TestRequestId:
    def test_client_supplied_request_id_is_echoed(self, client):
        response = _post_pdf(client)
        response = client.post(
            API_URL,
            content=pdf_with_text("x"),
            headers={
                "content-type": PDF_CONTENT_TYPE,
                "X-Request-ID": "k6-correlacion-1",
            },
        )

        assert response.status_code == 200
        assert response.headers["x-request-id"] == "k6-correlacion-1"

    def test_missing_request_id_generates_a_uuid4_hex(self, client):
        response = _post_pdf(client)

        value = response.headers["x-request-id"]
        assert len(value) == 32
        int(value, 16)

    def test_metrics_requests_also_carry_a_request_id(self, client):
        response = client.get("/metrics")

        assert response.status_code == 200
        assert len(response.headers["x-request-id"]) == 32


class TestLogLine:
    def test_one_json_line_per_request(self, client, caplog):
        with caplog.at_level(logging.INFO):
            response = _post_pdf(client)

        assert response.status_code == 200
        records = _completed_records(caplog)
        assert len(records) == 1
        assert records[0].status == 200
        assert records[0].duration_ms >= 0
        assert records[0].error_code is None

    def test_error_code_is_logged_on_error(self, client, caplog):
        with caplog.at_level(logging.INFO):
            response = client.post(
                API_URL,
                content=b"not a pdf",
                headers={"content-type": PDF_CONTENT_TYPE},
            )

        assert response.status_code == 415
        records = _completed_records(caplog)
        assert records[-1].status == 415
        assert records[-1].error_code == "NOT_A_PDF"

    def test_logs_never_contain_pdf_content_or_server_paths(self, client, caplog):
        secret_text = "contenido ultra secreto del pdf"

        with caplog.at_level(logging.INFO):
            _post_pdf(client, secret_text)

        captured = caplog.text
        assert secret_text not in captured
        assert os.getcwd() not in captured

    def test_json_formatter_injects_request_id_from_context(self):
        from core.logging import JsonLogFormatter, request_id_var

        record = logging.LogRecord(
            "pdf_extractext.test", logging.INFO, "f.py", 1, "request completed", (), None
        )
        token = request_id_var.set("correlacion-77")
        try:
            line = JsonLogFormatter().format(record)
        finally:
            request_id_var.reset(token)

        payload = json.loads(line)
        assert payload["request_id"] == "correlacion-77"
        assert payload["msg"] == "request completed"
        assert {"ts", "level", "msg", "replica", "pid"} <= set(payload)

    def test_json_formatter_omits_none_optional_fields(self):
        from core.logging import JsonLogFormatter

        record = logging.LogRecord(
            "pdf_extractext.test", logging.INFO, "f.py", 1, "ok", (), None
        )
        payload = json.loads(JsonLogFormatter().format(record))

        assert "error_code" not in payload
        assert "request_id" not in payload


class TestMetricsEndpoint:
    def test_metrics_exposes_all_families(self, client):
        response = client.get("/metrics")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        lines = response.text.splitlines()
        for family in FAMILIES:
            assert any(line.startswith(f"# HELP {family}") for line in lines)

    def test_metrics_text_is_prometheus_parseable(self, client):
        text = client.get("/metrics").text

        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            name, value = line.rsplit(" ", 1)
            assert name, line
            try:
                float(value)
            except ValueError:
                pytest.fail(f"valor no numérico en la línea {line!r}")

    def test_counters_rise_and_gauge_returns_to_zero(self, client):
        pdf = pdf_with_text("contadores")
        expected_bytes = len(pdf)

        for _ in range(3):
            response = client.post(
                API_URL,
                content=pdf,
                headers={"content-type": PDF_CONTENT_TYPE},
            )
            assert response.status_code == 200

        text = client.get("/metrics").text
        assert _metric_value(text, 'extract_requests_total{status="200"}') == 3
        assert _metric_value(text, "bytes_read_total") == 3 * expected_bytes
        assert _metric_value(text, "pages_processed_total") == 3
        assert _metric_value(text, "extract_duration_seconds_count") == 3
        assert _metric_value(text, "extractions_in_flight") == 0

    def test_error_responses_are_counted_by_status(self, client):
        response = client.post(
            API_URL,
            content=b"not a pdf",
            headers={"content-type": PDF_CONTENT_TYPE},
        )
        assert response.status_code == 415

        text = client.get("/metrics").text
        assert _metric_value(text, 'extract_requests_total{status="415"}') == 1
        assert _metric_value(text, "extractions_in_flight") == 0


class TestMetricsUnit:
    def test_rejection_kind_mapping(self):
        METRICS.reset()
        METRICS.record_rejection("OVERLOADED")
        METRICS.record_rejection("QUEUE_SATURATED")
        METRICS.record_rejection("NOT_A_PDF")

        text = METRICS.render()
        assert 'admission_rejections_total{kind="overloaded"} 1' in text
        assert 'admission_rejections_total{kind="queue_saturated"} 1' in text
        assert 'admission_rejections_total{kind="not_a_pdf"}' not in text

    def test_admission_wait_histogram_observes(self):
        METRICS.reset()
        METRICS.record_admission_wait(0.3)
        METRICS.record_admission_wait(1.5)

        lines = METRICS.render().splitlines()
        assert 'admission_wait_seconds_bucket{le="0.5"} 1' in lines
        assert 'admission_wait_seconds_bucket{le="+Inf"} 2' in lines
        assert any(line.startswith("admission_wait_seconds_sum ") for line in lines)