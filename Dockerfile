# syntax=docker/dockerfile:1

# ============================================================
# Stage 1: builder — solo deps de producción (venv reproducible)
#
# El gate de calidad (ruff, mypy, pytest --cov) vive en la CI
# (.github/workflows/ci.yml), NO en el build: ``docker compose up
# --build`` debe ser reproducible y no fallar por tests.
# ============================================================
FROM python:3.12-slim AS builder

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /uvx /usr/local/bin/

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project

# ============================================================
# Stage 2: runtime — imagen minima, sin tooling de desarrollo
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

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; from core.config import get_settings; urllib.request.urlopen(f'http://localhost:{get_settings().port}/api/v1/health')"]

# Port binding: HOST/PORT/UVICORN_WORKERS se leen del entorno via Settings
CMD ["python", "main.py"]
