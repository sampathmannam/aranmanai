FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsqlcipher-dev \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY pyproject.toml ./

ENV PYTHONPATH=/app/src
ENV ARANMANAI_ENVIRONMENT=production
EXPOSE 8080
EXPOSE 8501

# Default: run the API. Override CMD to run the Streamlit frontend.
CMD ["uvicorn", "aranmanai.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
