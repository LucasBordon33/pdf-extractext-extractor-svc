# syntax=docker/dockerfile:1

# ============================================================
# Stage 1: builder — deps + tooling de TDD + gate de tests
# ============================================================
FROM python:3.12-slim AS builder

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /uvx /usr/local/bin/

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --all-extras --no-install-project

COPY . .
RUN .venv/bin/pytest -q

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
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"]

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
