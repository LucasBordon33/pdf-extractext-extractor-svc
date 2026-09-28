"""Handlers globales de excepciones de la API.

Unico lugar donde las excepciones (de validacion, de dominio o
inesperadas) se traducen a respuestas HTTP con cuerpo ``ErrorResponse``.
El dominio no participa: solo expone ``error_code`` y ``status_http``.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.v1.schemas import ErrorResponse
from core.exceptions import DocumentExtractionError

_INTERNAL_ERROR_MESSAGE = "ocurrio un error interno inesperado"


def register_exception_handlers(app: FastAPI) -> None:
    """Registra todos los handlers de error en la app."""

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error_code="VALIDATION_ERROR",
                message=_first_validation_message(exc),
            ).model_dump(),
        )

    @app.exception_handler(DocumentExtractionError)
    async def _handle_domain_error(
        request: Request, exc: DocumentExtractionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_http,
            content=ErrorResponse(
                error_code=exc.error_code, message=str(exc)
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # Nunca filtrar detalles internos (stack, datos) al cliente.
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error_code="INTERNAL_ERROR",
                message=_INTERNAL_ERROR_MESSAGE,
            ).model_dump(),
        )


def _first_validation_message(exc: RequestValidationError) -> str:
    """Resume el primer error de validacion con su campo."""
    if not exc.errors():
        return "payload invalido"
    first = exc.errors()[0]
    location = ".".join(str(part) for part in first.get("loc", []))
    detail = first.get("msg", "valor invalido")
    return f"campo '{location}': {detail}"
