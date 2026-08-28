#!/usr/bin/env bash
# Per-boot runtime init: bootstrap gitignored state after checkout, then ensure DB.
set -euo pipefail

cd "$(dirname "$0")/.."

# venv/, data/, and .env are gitignored — a fresh checkout after a build
# will not include them even when install ran during the build snapshot.
if [ ! -d venv ]; then
  ./scripts/cloud-agent-install.sh
else
  if [ ! -f .env ]; then
    cp .env.example .env
  fi
  if [ ! -f data/aranmanai.db ]; then
    ./venv/bin/python scripts/init_db.py
  fi
fi

echo "Aranmanai runtime ready (DB at data/aranmanai.db)"
