#!/usr/bin/env bash
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
exec ./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
