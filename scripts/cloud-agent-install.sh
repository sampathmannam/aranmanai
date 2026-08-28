#!/usr/bin/env bash
# Idempotent Cloud Agent install: venv, deps, dev .env, DB init.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d venv ]; then
  python3 -m venv venv
fi

./venv/bin/pip install --upgrade pip setuptools wheel
./venv/bin/pip install -e ".[dev,ml]"

if [ ! -f .env ]; then
  cp .env.example .env
fi

./venv/bin/python scripts/init_db.py
