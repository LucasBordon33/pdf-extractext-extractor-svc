"""Métricas de texto Prometheus, sin dependencia externa (ISSUE-014).

Contadores, gauges e histogramas en memoria, con locks, y renderizador
a texto Prometheus. No se usa ``prometheus_client`` para no engordar la
imagen: el subset que el TP pide es pequeño y estable.

Las siete familias del ISSUE-014:

- ``extract_requests_total{status}``
- ``extract_duration_seconds`` (buckets 0.5/1/2/5/10/25)
- ``extractions_in_flight`` (gauge)
- ``admission_wait_seconds`` (histograma)
- ``admission_rejections_total{kind}`` (overloaded | queue_saturated)
- ``pages_processed_total``
- ``bytes_read_total``
"""

import threading
from collections.abc import Iterable

REJECTION_KINDS = {
    "OVERLOADED": "overloaded",
    "QUEUE_SATURATED": "queue_saturated",
}

_EXTRACT_DURATION_BUCKETS = (0.5, 1, 2, 5, 10, 25)
_ADMISSION_WAIT_BUCKETS = (0.1, 0.25, 0.5, 1, 2, 5, 10)


class Counter:
    """Contador con soporte de labels (dict inmutado como clave)."""

    def __init__(self, name: str, help_text: str) -> None:
        self._name = name
        self._help = help_text
        self._lock = threading.Lock()
        self._samples: dict[frozenset[tuple[str, str]], int] = {}

    def inc(self, amount: int = 1, labels: dict[str, str] | None = None) -> None:
        key = frozenset((labels or {}).items())
        with self._lock:
            self._samples[key] = self._samples.get(key, 0) + amount

    def render(self) -> list[str]:
        lines = [
            f"# HELP {self._name} {self._help}",
            f"# TYPE {self._name} counter",
        ]
        for labels, value in sorted(self._samples.items()):
            suffix = ""
            if labels:
                pairs = ",".join(f'{k}="{v}"' for k, v in sorted(labels))
                suffix = "{" + pairs + "}"
            lines.append(f"{self._name}{suffix} {value}")
        return lines


class Gauge:
    """Valor que puede subir y bajar (p. ej. extracciones en vuelo)."""

    def __init__(self, name: str, help_text: str) -> None:
        self._name = name
        self._help = help_text
        self._lock = threading.Lock()
        self._value = 0

    def inc(self, amount: int = 1) -> None:
        with self._lock:
            self._value += amount

    def dec(self, amount: int = 1) -> None:
        with self._lock:
            self._value -= amount

    def render(self) -> list[str]:
        return [
            f"# HELP {self._name} {self._help}",
            f"# TYPE {self._name} gauge",
            f"{self._name} {self._value}",
        ]


class Histogram:
    """Histograma Prometheus: buckets acumulativos + sum + count."""

    def __init__(
        self, name: str, help_text: str, buckets: Iterable[float]
    ) -> None:
        self._name = name
        self._help = help_text
        self._limits = tuple(sorted(buckets))
        self._lock = threading.Lock()
        self._counts = [0] * len(self._limits)
        self._count = 0
        self._sum = 0.0

    def observe(self, value: float) -> None:
        with self._lock:
            self._count += 1
            self._sum += value
            for index, limit in enumerate(self._limits):
                if value <= limit:
                    self._counts[index] += 1

    def render(self) -> list[str]:
        lines = [
            f"# HELP {self._name} {self._help}",
            f"# TYPE {self._name} histogram",
        ]
        cumulative = 0
        for limit, count in zip(self._limits, self._counts, strict=True):
            cumulative += count
            lines.append(f'{self._name}_bucket{{le="{limit:g}"}} {cumulative}')
        lines.append(f'{self._name}_bucket{{le="+Inf"}} {self._count}')
        lines.append(f"{self._name}_sum {self._sum:g}")
        lines.append(f"{self._name}_count {self._count}")
        return lines


class Metrics:
    """Singleton con las siete familias y los helpers para alimentarlas.

    ``reset()`` restaura el estado a cero (aislamiento en tests); en
    producción el objeto nunca se reinicia.
    """

    def __init__(self) -> None:
        self.extract_requests_total = Counter(
            "extract_requests_total",
            "Requests de extraccion completados por status HTTP.",
        )
        self.extract_duration_seconds = Histogram(
            "extract_duration_seconds",
            "Duracion del request de extraccion completo (segundos).",
            _EXTRACT_DURATION_BUCKETS,
        )
        self.extractions_in_flight = Gauge(
            "extractions_in_flight",
            "Extracciones en vuelo en este instante.",
        )
        self.admission_wait_seconds = Histogram(
            "admission_wait_seconds",
            "Segundos esperando por un lugar de extraccion.",
            _ADMISSION_WAIT_BUCKETS,
        )
        self.admission_rejections_total = Counter(
            "admission_rejections_total",
            "Rechazos de admision por clase (overloaded | queue_saturated).",
        )
        self.pages_processed_total = Counter(
            "pages_processed_total",
            "Paginas aportadas al resultado de extraccion.",
        )
        self.bytes_read_total = Counter(
            "bytes_read_total",
            "Bytes de PDF que llegaron a la extraccion.",
        )

    @property
    def _all(self) -> tuple[Counter | Gauge | Histogram, ...]:
        return (
            self.extract_requests_total,
            self.extract_duration_seconds,
            self.extractions_in_flight,
            self.admission_wait_seconds,
            self.admission_rejections_total,
            self.pages_processed_total,
            self.bytes_read_total,
        )

    def reset(self) -> None:
        """Devuelve todos los contadores a su estado inicial."""
        self.__init__()

    def render(self) -> str:
        """Todo el texto Prometheus para ``GET /metrics``."""
        lines: list[str] = []
        for metric in self._all:
            lines.extend(metric.render())
        return "\n".join(lines) + "\n"

    def record_extract(self, status_code: int, duration_s: float) -> None:
        self.extract_requests_total.inc(labels={"status": str(status_code)})
        self.extract_duration_seconds.observe(duration_s)

    def record_rejection(self, error_code: str) -> None:
        """Anota 429/503 en ``admission_rejections_total`` si corresponde."""
        kind = REJECTION_KINDS.get(error_code)
        if kind is not None:
            self.admission_rejections_total.inc(labels={"kind": kind})

    def record_admission_wait(self, wait_s: float) -> None:
        self.admission_wait_seconds.observe(wait_s)

    def record_pages(self, page_count: int) -> None:
        self.pages_processed_total.inc(page_count)

    def record_bytes(self, byte_count: int) -> None:
        self.bytes_read_total.inc(byte_count)


METRICS = Metrics()