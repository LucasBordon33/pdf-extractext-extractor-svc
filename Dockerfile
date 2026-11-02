
FROM python:3.12-slim AS builder

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /uvx /usr/local/bin/

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --no-build

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

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get('PORT', '8000')}/api/v1/ready', timeout=4)"]

ENTRYPOINT ["/app/scripts/start.sh"]
CMD ["uvicorn", "main:app"]
