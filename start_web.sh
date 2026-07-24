#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  echo "No .env found. Copy .env.example to .env and set LLMAPI_KEY."
  exit 1
fi
set -a
source .env
set +a
pip install -q -r web/requirements.txt openai
exec python -m web.run --host "${JUSTASK_HOST:-127.0.0.1}" --port "${JUSTASK_PORT:-8000}"
