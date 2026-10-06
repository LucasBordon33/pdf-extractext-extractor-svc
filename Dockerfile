# syntax=docker/dockerfile:1

# ============================================================
# Stage 1: builder — solo deps de producción, SOLO wheels.
#
# --no-build equivale a `pip --only-binary :all:`: si pypdfium2
# (o cualquier dep) no trajera wheel precompilado para la plataforma,
# el build FALLA acá en vez de compilar desde fuente (lo que dispararía
# el tiempo de build y el tamaño de la imagen).
# Verificación manual: pip download --only-binary :all: pypdfium2
#
# El gate de calidad (ruff, mypy, pytest --cov) vive en la CI
# (.github/workflows/ci.yml, ISSUE-020), NO en el build de la imagen.
# ============================================================
FROM python:3.12-slim AS builder

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /uvx /usr/local/bin/

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --no-build

# ============================================================
# Stage 2: runtime — imagen mínima, sin tooling de desarrollo
# (sin pytest/ruff/mypy), usuario no-root.
# ============================================================
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN useradd --system --create-home --shell /usr/sbin/nologin appuser

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser main.py ./
COPY --chown=appuser:appuser api ./api/
COPY --chown=appuser:appuser core ./core/
COPY --chown=appuser:appuser domain ./domain/
COPY --chown=appuser:appuser adapters ./adapters/
COPY --chown=appuser:appuser scripts/start.sh /app/scripts/start.sh

RUN chmod +x /app/scripts/start.sh

USER appuser

# Documentación del puerto; el real lo define la env PORT (ISSUE-010)
EXPOSE 8000

# Readiness (no liveness): una réplica saturada NO debe considerarse sana.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get('PORT', '8000')}/api/v1/ready', timeout=4)"]

# HOST/PORT/UVICORN_WORKERS se leen del entorno en start.sh (ISSUE-010)
ENTRYPOINT ["/app/scripts/start.sh"]
CMD ["uvicorn", "main:app"]
