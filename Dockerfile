# Backend API image for Margin.
FROM python:3.12-slim

# Prevent .pyc files and enable unbuffered logs for containerized environments.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=10 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.9.17 /uv /uvx /bin/

WORKDIR /app

# Install locked dependencies before copying the full source to maximize layer caching.
COPY pyproject.toml uv.lock README.md ./
COPY src/margin/__init__.py ./src/margin/__init__.py
RUN uv sync --frozen --no-dev --extra data --no-install-project

COPY src ./src
COPY scripts ./scripts
COPY alembic ./alembic
COPY alembic.ini ./
RUN uv sync --frozen --no-dev --extra data

# Run as a non-root user and prepare persistent directories for audit/snapshots.
RUN useradd --create-home --uid 10001 margin \
    && mkdir -p .margin/audit .margin/snapshots \
    && chown -R margin:margin /app

USER margin

EXPOSE 8000

CMD ["uvicorn", "margin.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
