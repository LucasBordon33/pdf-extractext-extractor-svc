"""Middlewares ASGI de observabilidad (ISSUE-014).

``RequestContextMiddleware`` (el más externo): propaga o genera el
``X-Request-ID``, lo publica en el contexto y emite UNA línea JSON por
request con ``status`` y ``duration_ms``. ``TimingMiddleware`` (el más
interno): solo alimenta las métricas de extracción.

Ninguno bufferiza el body en el camino feliz (R11/no-disk): el body se
acumula únicamente cuando el status es >= 400, y solo para leer el
``error_code`` del ``ErrorResponse``.
"""

import json
import time
import uuid
from typing import Any

from api.metrics import METRICS
from core.logging import get_logger, request_id_var

logger = get_logger("api.middleware")

_EXTRACT_PATHS = {"/extract", "/api/v1/extract"}
_REQUEST_ID_HEADER = b"x-request-id"
_ERROR_STATUS_FROM = 400


class TimingMiddleware:
    """Registra status y duración de cada request de extracción."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("path") not in _EXTRACT_PATHS:
            await self.app(scope, receive, send)
            return
        started = time.monotonic()
        status = 500

        async def _send_with_status(message: dict[str, Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, _send_with_status)
        finally:
            METRICS.record_extract(status, time.monotonic() - started)


class RequestContextMiddleware:
    """Request_id en contexto + una línea JSON por request.

    El ``X-Request-ID`` del cliente se honra (correlación con k6/Vegeta);
    si no viene, se genera un ``uuid4``. La línea de log se emite siempre
    (éxito o error), con ``status`` y, cuando el response es un error,
    el ``error_code`` extraído del ``ErrorResponse``.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = _resolve_request_id(scope)
        token = request_id_var.set(request_id)
        started = time.monotonic()
        status = 500
        error_code = None
        capture_body = False
        body_parts: list[bytes] = []

        async def _send(message: dict[str, Any]) -> None:
            nonlocal status, error_code, capture_body
            message_type = message["type"]
            if message_type == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append(
                    (_REQUEST_ID_HEADER, request_id.encode("ascii"))
                )
                capture_body = status >= _ERROR_STATUS_FROM
                if capture_body:
                    body_parts.clear()
            elif message_type == "http.response.body" and capture_body:
                body_parts.append(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            if capture_body:
                error_code = _extract_error_code(body_parts)
            duration_ms = (time.monotonic() - started) * 1000
            logger.info(
                "request completed",
                extra={
                    "status": status,
                    "duration_ms": duration_ms,
                    "error_code": error_code,
                },
            )
            request_id_var.reset(token)


def _resolve_request_id(scope: dict[str, Any]) -> str:
    for name, value in scope.get("headers") or []:
        if name == _REQUEST_ID_HEADER:
            return value.decode("latin-1")
    return uuid.uuid4().hex


def _extract_error_code(body_parts: list[bytes]) -> str | None:
    if not body_parts:
        return None
    try:
        payload = json.loads(b"".join(body_parts))
    except (ValueError, UnicodeDecodeError):
        return None
    if isinstance(payload, dict):
        code = payload.get("error_code")
        if isinstance(code, str):
            return code
    return None