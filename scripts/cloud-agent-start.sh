#!/usr/bin/env bash
# Per-boot runtime init: ensure dev config and database exist.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp .env.example .env
fi

if [ ! -f data/aranmanai.db ]; then
  ./venv/bin/python scripts/init_db.py
fi

echo "Aranmanai runtime ready (DB at data/aranmanai.db)"
