# Backend API image for Margin.
FROM python:3.12-slim

# Prevent .pyc files and enable unbuffered logs for containerized environments.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=10

WORKDIR /app

# Install dependencies before copying the full source to maximize layer caching.
COPY pyproject.toml README.md ./
COPY src/margin/__init__.py ./src/margin/__init__.py
RUN pip install -e ".[data]"

COPY src ./src
COPY scripts ./scripts
COPY alembic ./alembic
COPY alembic.ini ./

# Run as a non-root user and prepare persistent directories for audit/snapshots.
RUN useradd --create-home --uid 10001 margin \
    && mkdir -p .margin/audit .margin/snapshots \
    && chown -R margin:margin /app

USER margin

EXPOSE 8000

CMD ["uvicorn", "margin.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
