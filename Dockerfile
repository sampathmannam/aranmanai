# Aranmanai v0.1.0 - production Dockerfile
# Single-stage Python 3.11 image. Runs as non-root. SQLCipher system lib.
FROM python:3.11-slim AS base

LABEL org.opencontainers.image.title="Aranmanai" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.source="https://github.com/sampathmannam/aranmanai" \
      org.opencontainers.image.description="District conviction-rate management platform"

# System deps: build-essential for sqlcipher3 wheel, curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsqlcipher-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd --create-home --shell /bin/bash aranmanai
WORKDIR /app
RUN chown -R aranmanai:aranmanai /app
USER aranmanai

# Python deps
COPY --chown=aranmanai:aranmanai requirements.txt .
RUN pip install --no-cache-dir --upgrade pip wheel && \
    pip install --no-cache-dir -r requirements.txt

# App
COPY --chown=aranmanai:aranmanai src ./src
COPY --chown=aranmanai:aranmanai scripts ./scripts
COPY --chown=aranmanai:aranmanai pyproject.toml ./

# Data dir (SQLCipher DB, ChromaDB, mocks, backups)
RUN mkdir -p data models && chown -R aranmanai:aranmanai data models

# Env defaults (override with -e or .env file)
ENV ENVIRONMENT=production \
    LOG_LEVEL=INFO \
    DATA_DIR=/app/data \
    DB_PATH=/app/data/aranmanai.db \
    CHROMA_DIR=/app/data/chroma \
    MODELS_DIR=/app/models \
    BACKUPS_DIR=/app/data/backups

EXPOSE 8080

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

# Run as aranmanai user, no auto-reload in production
CMD ["uvicorn", "src.aranmanai.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
