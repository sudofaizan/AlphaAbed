#!/usr/bin/env bash
# Interactive Telegram login (Amazon Linux has python3, not python).
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${APP_DIR}"

[[ -f "${APP_DIR}/.env" ]] || {
  echo "Create .env first: cp .env.example .env && nano .env" >&2
  exit 1
}

if ! command -v python3 >/dev/null 2>&1; then
  echo "Installing python3..."
  if command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3 python3-pip
  elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y python3 python3-pip
  else
    echo "python3 not found. Install it with your package manager." >&2
    exit 1
  fi
fi

if [[ ! -d "${APP_DIR}/venv" ]]; then
  echo "Creating virtualenv..."
  python3 -m venv "${APP_DIR}/venv"
  "${APP_DIR}/venv/bin/pip" install --upgrade pip
  "${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
fi

exec "${APP_DIR}/venv/bin/python" "${APP_DIR}/login_session.py"
