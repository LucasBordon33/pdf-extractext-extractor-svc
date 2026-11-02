"""Servicio de dominio: extracción de documentos con pool y deadline.

Responsabilidades (una sola, orquestación):

1. Validación defensiva de tamaño (``FileTooLargeError``).
2. Admisión acotada (``ADMISSION_TIMEOUT_SECONDS``): la petición espera
   por un lugar de extracción y, si no lo consigue a tiempo, se
   rechaza con ``OverloadedError`` (429). El budget de admisión tiene
   que quedar por debajo del timeout del cliente (ADR-TP-7), así el
   cliente oye un 429 en vez de expirar.
3. Delegación del trabajo pesado al ``ExtractionPool`` inyectado —
   nunca inline en el hilo del request.
4. Deadline (``EXTRACT_TIMEOUT_SECONDS``): si el resultado no llega,
   se cancela el futuro y se lanza ``ExtractionTimeoutError``.

Dominio puro: sin FastAPI, sin pdfium, sin asyncio del loop HTTP, sin
variables de entorno — todos los valores llegan inyectados.
"""

import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from math import ceil

from core.exceptions import (
    ExtractionTimeoutError,
    FileTooLargeError,
    OverloadedError,
)
from domain.models.extraction_result import ExtractionResult
from domain.ports.extraction_pool import ExtractionPool
from domain.ports.text_extractor import PdfToMarkdown

_BYTES_PER_MB = 1024 * 1024
_RETRY_AFTER_OVERLOADED = 1


class DocumentService:

    def __init__(
        self,
        extractor: PdfToMarkdown,
        pool: ExtractionPool,
        *,
        max_upload_size_mb: int,
        extract_timeout_seconds: float,
        max_concurrent_extractions: int,
        admission_timeout_seconds: float,
        admission_observer: Callable[[float], None] | None = None,
    ) -> None:
        self._extractor = extractor
        self._pool = pool
        self._max_upload_bytes = max_upload_size_mb * _BYTES_PER_MB
        self._timeout_seconds = extract_timeout_seconds
        self._admission_timeout_seconds = admission_timeout_seconds
        self._admission = threading.Semaphore(max_concurrent_extractions)
        self._admission_observer = admission_observer

    def extract(self, content: bytes, filename: str) -> ExtractionResult:
        self._ensure_size(content, filename)
        self._admit(filename)
        try:
            future = self._pool.submit(
                lambda: self._extractor.extract(content, filename)
            )
            return self._await_result(future, filename)
        finally:
            self._admission.release()

    def can_accept_work(self) -> bool:
        if self._admission.acquire(blocking=False):
            self._admission.release()
            return True
        return False

    def _admit(self, filename: str) -> None:
        started = time.monotonic()
        acquired = self._admission.acquire(timeout=self._admission_timeout_seconds)
        if self._admission_observer is not None:
            self._admission_observer(time.monotonic() - started)
        if acquired:
            return
        raise OverloadedError(
            f"no se logro un lugar de extraccion para '{filename}' en"
            f" {self._admission_timeout_seconds} segundos",
            retry_after_seconds=_RETRY_AFTER_OVERLOADED,
        )

    def _ensure_size(self, content: bytes, filename: str) -> None:
        if len(content) > self._max_upload_bytes:
            raise FileTooLargeError(
                f"el archivo '{filename}' supera el maximo de"
                f" {self._max_upload_bytes // _BYTES_PER_MB} MB"
            )

    def _await_result(
        self, future: Future[ExtractionResult], filename: str
    ) -> ExtractionResult:
        try:
            return future.result(timeout=self._timeout_seconds)
        except FutureTimeoutError as error:
            future.cancel()
            raise ExtractionTimeoutError(
                f"la extraccion de '{filename}' supero el deadline de"
                f" {self._timeout_seconds} segundos",
                retry_after_seconds=ceil(self._timeout_seconds),
            ) from error
