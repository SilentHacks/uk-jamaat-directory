FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && adduser --disabled-password --gecos "" appuser

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic

RUN python -m pip install -U pip \
    && python -m pip install .

RUN python -m playwright install chromium --with-deps

# Celery beat persists its schedule under /data (named volume in production).
# Create it owned by appuser so the volume initialises writable for the non-root user.
RUN mkdir -p /data && chown appuser:appuser /data

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://localhost:8000/v1/health || exit 1

CMD ["uvicorn", "uk_jamaat_directory.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
