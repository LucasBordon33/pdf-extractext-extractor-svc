"""Logging estructurado del módulo (stdlib, sin dependencias extra).

Elección justificada: los eventos de discovery (registro, desregistro,
health, discovery, errores de conexión) son de bajo volumen y cada
microservicio ya configura su propio logging. `structlog` añadiría una
dependencia transversal a los cuatro servicios sin beneficio medible en
este escenario (KISS/YAGNI); `JsonFormatter` cubre la necesidad de logs
estructurados (una línea JSON por evento) y la migración a structlog,
si algún día se justifica, no cambia ningún call-site porque el módulo
usa la API estándar de `logging`.

Los eventos llevan contexto en `extra` (`event`, `service_id`,
`service`, `error`, ...): con `JsonFormatter` aparecen como campos del
JSON; con el formatter por defecto, como pares clave=valor.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

LOGGER_NAME = "service_discovery"

_BASE_ATTRS = frozenset(
    logging.LogRecord(
        name="", level=0, pathname="", lineno=0, msg="", args=None, exc_info=None
    ).__dict__
)


def get_logger() -> logging.Logger:
    """Logger del módulo (nombre estable para filtros por servicio)."""
    return logging.getLogger(LOGGER_NAME)


class _ExtrasFormatter(logging.Formatter):
    """Formatter de texto que añade los `extra={...}` del record.

    Sin esto, los eventos estructurados (event, service_id, error, ...)
    serían invisibles en modo texto: el mensaje solo describe qué pasó,
    los extras dicen a quién y por qué.
    """

    def format(self, record: logging.LogRecord) -> str:
        # Los extras se leen ANTES de super().format(): el formatter base
        # agrega `message`/`asctime` al record y aparecerían duplicados.
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _BASE_ATTRS and not key.startswith("_")
        }
        message = super().format(record)
        if not extras:
            return message
        rendered = ", ".join(f"{key}={value}" for key, value in extras.items())
        return f"{message} [{rendered}]"


class JsonFormatter(logging.Formatter):
    """Serializa cada record como una línea JSON incluyendo sus extras.

    No llama a `super().format()`: el formatter base mutaría el record
    (message/asctime) y contaminaría el payload.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _BASE_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", *, json_output: bool = False) -> None:
    """Configura el logger del módulo; idempotente.

    Siempre añade un handler propio al logger `service_discovery` y deja
    de propagar: el root logger de uvicorn no tiene handler, así que sin
    esto los eventos INFO (registro/desregistro/descubrimiento) se
    pierden y solo aparecerían WARNING+ vía el handler de último
    recurso, sin contexto.

    - `json_output=False` (default): texto `timestamp | LEVEL | mensaje
      [extras]` en stderr, visible en `docker logs`.
    - `json_output=True`: una línea JSON por evento (`JsonFormatter`).
    """
    logger = get_logger()
    logger.setLevel(level.upper())
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_ExtrasFormatter("%(asctime)s | %(levelname)-8s | %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False
