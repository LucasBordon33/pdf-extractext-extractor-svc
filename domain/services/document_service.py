"""Servicio de dominio: extracción de documentos con pool y deadline.

Responsabilidades (una sola, orquestación):

1. Validación defensiva de tamaño (``FileTooLargeError``).
2. Delegación del trabajo pesado al ``ExtractionPool`` inyectado —
   nunca inline en el hilo del request.
3. Deadline (``EXTRACT_TIMEOUT_SECONDS``): si el resultado no llega,
   se cancela el futuro y se lanza ``ExtractionTimeoutError``; el slot
   del semáforo lo libera el pool en ``finally``.

Dominio puro: sin FastAPI, sin pdfium, sin asyncio del loop HTTP, sin
variables de entorno — todos los valores llegan inyectados.
"""

from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from math import ceil

from core.exceptions import ExtractionTimeoutError, FileTooLargeError
from domain.models.extraction_result import ExtractionResult
from domain.ports.extraction_pool import ExtractionPool
from domain.ports.text_extractor import PdfToMarkdown

_BYTES_PER_MB = 1024 * 1024


class DocumentService:
    """Orquesta la extracción con validación, pool y deadline."""

    def __init__(
        self,
        extractor: PdfToMarkdown,
        pool: ExtractionPool,
        *,
        max_upload_size_mb: int,
        extract_timeout_seconds: float,
    ) -> None:
        self._extractor = extractor
        self._pool = pool
        self._max_upload_bytes = max_upload_size_mb * _BYTES_PER_MB
        self._timeout_seconds = extract_timeout_seconds

    def extract(self, content: bytes, filename: str) -> ExtractionResult:
        """Devuelve el resultado enriquecido de la extracción.

        :raises FileTooLargeError: el contenido supera el máximo.
        :raises ExtractionTimeoutError: venció el deadline interno.
        :raises CorruptFileError: el contenido no puede procesarse.
        :raises EmptyExtractionError: no se obtuvo texto válido.
        """
        self._ensure_size(content, filename)
        future = self._pool.submit(
            lambda: self._extractor.extract(content, filename)
        )
        return self._await_result(future, filename)

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
            # El semáforo se libera en el pool (finally del trabajo):
            # cancelar aquí no puede dejar slots tomados.
            future.cancel()
            raise ExtractionTimeoutError(
                f"la extraccion de '{filename}' supero el deadline de"
                f" {self._timeout_seconds} segundos",
                retry_after_seconds=ceil(self._timeout_seconds),
            ) from error
