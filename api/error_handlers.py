"""Handlers globales de excepciones de la API.

Unico lugar donde las excepciones (de validacion, de dominio o
built-in) se traducen a respuestas HTTP con cuerpo ``ErrorResponse``.
El dominio no participa: solo expone ``error_code`` y ``status_http``.

Mapeo global:

- RequestValidationError / ValueError → 422
- DocumentExtractionError (y subclases) → el status declarado por el
  dominio, más el header ``Retry-After`` si la excepción lo define
- RuntimeError → 400
- MemoryError → 413
- Exception → 500 (mensaje generico, sin filtrar internos)
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.extract.schemas import ErrorResponse
from core.exceptions import DocumentExtractionError

_INTERNAL_ERROR_MESSAGE = "ocurrio un error interno inesperado"

_BUILTIN_HANDLERS: dict[type[Exception], tuple[int, str]] = {
    ValueError: (422, "VALUE_ERROR"),
    RuntimeError: (400, "RUNTIME_ERROR"),
    MemoryError: (413, "MEMORY_ERROR"),
}


def register_exception_handlers(app: FastAPI) -> None:
    """Registra todos los handlers de error en la app."""
    app.add_exception_handler(
        RequestValidationError, _validation_error_handler
    )
    app.add_exception_handler(DocumentExtractionError, _domain_error_handler)
    for exc_type, (status_code, error_code) in _BUILTIN_HANDLERS.items():
        app.add_exception_handler(
            exc_type, _builtin_error_handler(status_code, error_code)
        )
    app.add_exception_handler(Exception, _unexpected_error_handler)


def _error_response(
    status_code: int, error_code: str, message: str
) -> JSONResponse:
    # exclude_none: "retry_after_seconds" solo aparece cuando corresponde
    # (429/503); en el resto la forma wire queda {error_code, message}.
    body = ErrorResponse(error_code=error_code, message=message).model_dump(
        exclude_none=True
    )
    return JSONResponse(status_code=status_code, content=body)


def _validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _error_response(422, "VALIDATION_ERROR", _first_validation_message(exc))


def _domain_error_handler(
    request: Request, exc: DocumentExtractionError
) -> JSONResponse:
    response = _error_response(exc.status_http, exc.error_code, str(exc))
    # 429/503 le dicen al cliente cuando reintentar; el resto no lleva header.
    if exc.retry_after_seconds is not None:
        response.headers["Retry-After"] = str(exc.retry_after_seconds)
    return response


def _builtin_error_handler(status_code: int, error_code: str):
    """Fabrica de handlers para excepciones built-in mapeadas."""

    def handler(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(status_code, error_code, str(exc))

    return handler


def _unexpected_error_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    # Nunca filtrar detalles internos (stack, datos) al cliente.
    return _error_response(500, "INTERNAL_ERROR", _INTERNAL_ERROR_MESSAGE)


def _first_validation_message(exc: RequestValidationError) -> str:
    """Resume el primer error de validacion con su campo."""
    if not exc.errors():
        return "payload invalido"
    first = exc.errors()[0]
    location = ".".join(str(part) for part in first.get("loc", []))
    detail = first.get("msg", "valor invalido")
    return f"campo '{location}': {detail}"
