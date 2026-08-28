FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
        libsqlcipher-dev \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

USER ubuntu
