#!/usr/bin/env bash
# Save last N channel messages to msg.txt (default 5).
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIMIT="${1:-5}"
OUT="${2:-msg.txt}"

if [[ ! -d "${APP_DIR}/venv" ]]; then
  echo "Run ./login.sh or ./deploy_ec2.sh first to create venv." >&2
  exit 1
fi

"${APP_DIR}/venv/bin/python" "${APP_DIR}/check_channel.py" --limit "${LIMIT}" --output "${OUT}"
echo "View with: cat ${OUT}"
