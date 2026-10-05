#!/usr/bin/env bash
# Quick checks when the dashboard won't load.
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_PORT="$(grep -E '^WEB_PORT=' "${APP_DIR}/.env" 2>/dev/null | cut -d= -f2- | tr -d '\r' || true)"
WEB_PORT="${WEB_PORT:-8080}"

echo "=== alphaabed systemd ==="
sudo systemctl status alphaabed --no-pager || true
echo
echo "=== last 40 log lines ==="
sudo journalctl -u alphaabed -n 40 --no-pager || true
echo
echo "=== listening ports (80 / ${WEB_PORT}) ==="
sudo ss -tlnp | grep -E ':80 |:'"${WEB_PORT}"' ' || echo "(nothing listening on 80 or ${WEB_PORT})"
echo
echo "=== curl localhost:${WEB_PORT}/health ==="
curl -sS -m 3 "http://127.0.0.1:${WEB_PORT}/health" || echo "FAILED"
echo
echo "=== manual uvicorn test (5s) ==="
if [[ -x "${APP_DIR}/venv/bin/uvicorn" ]]; then
  timeout 5 "${APP_DIR}/venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8765 &
  sleep 2
  curl -sS "http://127.0.0.1:8765/health" || echo "manual start failed"
  wait 2>/dev/null || true
else
  echo "venv/uvicorn missing — run ./deploy_ec2.sh"
fi
