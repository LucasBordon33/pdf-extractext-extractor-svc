"""Logging estructurado JSON a stdout (Twelve-Factor XI, ISSUE-014).

Nunca escribe a archivo: el destino es siempre ``sys.stdout`` para que
el runner de contenedor capture la línea. La configuración es
idempotente: recargar el módulo no duplica handlers (el gate de CI
importa la app repetidamente en el mismo proceso).

Un campo se considera opcional y se omite de la línea si es ``None``:
``request_id`` (vive en el ``ContextVar`` y lo inyecta el middleware),
``duration_ms``, ``status`` y ``error_code``. El orden de campos es el
del TP: ``ts, level, msg, request_id, duration_ms, status, error_code,
replica, pid``.
"""

import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar(
    "pdf_extractext_request_id", default=None
)

_REPLICA_ID = os.environ.get("HOSTNAME") or "unknown"
_PID = os.getpid()
_CONFIGURE_SENTINEL = "_pdf_extractext_logging_configured"
_OPTIONAL_FIELDS = ("duration_ms", "status", "error_code")


class JsonLogFormatter(logging.Formatter):
    """Serializa cada registro como un objeto JSON en una sola línea.

    Los campos opcionales se leen del propio ``LogRecord`` (los escribe
    el emisor con ``extra=``) o del ``ContextVar`` de ``request_id``.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or request_id_var.get()
        if request_id is not None:
            payload["request_id"] = request_id
        for field in _OPTIONAL_FIELDS:
            value = record.__dict__.get(field)
            if value is not None:
                payload[field] = value
        payload["replica"] = _REPLICA_ID
        payload["pid"] = _PID
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Configura el root logger para emitir a stdout; no-op si ya se hizo.

    ``fmt="json"`` usa ``JsonLogFormatter``; ``"text"`` mantiene el
    formato clásico para desarrollo local sin jq.
    """
    root = logging.getLogger()
    if getattr(root, _CONFIGURE_SENTINEL, False):
        return
    root.setLevel(level.upper())
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    if fmt == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
    root.addHandler(handler)
    setattr(root, _CONFIGURE_SENTINEL, True)


def get_logger(name: str) -> logging.Logger:
    """Logger de aplicación bajo el namespace ``pdf_extractext.*``."""
    return logging.getLogger(f"pdf_extractext.{name}")