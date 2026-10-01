"""Dobles de prueba compartidos entre archivos de tests."""

from collections.abc import Callable
from concurrent.futures import Future

from domain.models.extraction_result import ExtractionResult
from domain.ports.extraction_pool import ExtractionPool


class ImmediateExtractionPool(ExtractionPool):
    """Pool doble: ejecuta el trabajo inline y completa el futuro."""

    def submit(
        self, work: Callable[[], ExtractionResult]
    ) -> Future[ExtractionResult]:
        future: Future[ExtractionResult] = Future()
        try:
            future.set_result(work())
        except Exception as error:
            future.set_exception(error)
        return future


def make_document_service(
    extractor,
    pool: ExtractionPool | None = None,
    *,
    max_upload_size_mb: int = 12,
    extract_timeout_seconds: float = 25.0,
):
    """Construye un DocumentService con defaults de prueba."""
    from domain.services.document_service import DocumentService

    return DocumentService(
        extractor,
        pool if pool is not None else ImmediateExtractionPool(),
        max_upload_size_mb=max_upload_size_mb,
        extract_timeout_seconds=extract_timeout_seconds,
    )
