#!/usr/bin/env bash
# Deploy AlphaAbed on Amazon Linux 2023 / Amazon Linux 2 as a systemd daemon.
# Usage (on EC2 after git clone):
#   cp .env.example .env && nano .env
#   ./deploy_ec2.sh

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="alphaabed"
SERVICE_USER="${SERVICE_USER:-$(whoami)}"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

log() { echo "[deploy] $*"; }
die() { echo "[deploy] ERROR: $*" >&2; exit 1; }

if [[ "$(id -u)" -eq 0 ]]; then
  SUDO=""
else
  SUDO="sudo"
fi

if [[ -f /etc/os-release ]]; then
  # shellcheck source=/dev/null
  source /etc/os-release
  if [[ "${ID:-}" != "amzn" && "${ID_LIKE:-}" != *"amzn"* && "${ID:-}" != "amazon" ]]; then
    log "Warning: this script targets Amazon Linux; detected ID=${ID:-unknown}"
  fi
fi

log "App directory: ${APP_DIR}"

[[ -f "${APP_DIR}/.env" ]] || die "Create ${APP_DIR}/.env first (cp .env.example .env)."

if ! grep -qE '^API_ID=' "${APP_DIR}/.env" || ! grep -qE '^API_HASH=' "${APP_DIR}/.env" || ! grep -qE '^CHANNEL=' "${APP_DIR}/.env"; then
  die ".env must set API_ID, API_HASH, and CHANNEL."
fi

log "Installing system packages (python3, git)..."
if command -v dnf >/dev/null 2>&1; then
  $SUDO dnf install -y python3 python3-pip git
elif command -v yum >/dev/null 2>&1; then
  $SUDO yum install -y python3 python3-pip git
else
  die "Neither dnf nor yum found."
fi

log "Creating virtualenv and installing Python dependencies..."
python3 -m venv "${APP_DIR}/venv"
"${APP_DIR}/venv/bin/pip" install --upgrade pip
"${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

if ! grep -qE '^SESSION_STRING=.+' "${APP_DIR}/.env" && [[ ! -f "${APP_DIR}/telegram_session.session" ]]; then
  die "No Telegram session. Run: chmod +x login.sh && ./login.sh — paste SESSION_STRING into .env, then re-run deploy."
fi

log "Allow binding to port 80 (cap_net_bind_service on venv python)..."
PYBIN="$("${APP_DIR}/venv/bin/python" -c 'import sys; print(sys.executable)')"
if [[ -n "${PYBIN}" && -f "${PYBIN}" ]]; then
  $SUDO setcap 'cap_net_bind_service=+ep' "${PYBIN}" 2>/dev/null || \
    log "Note: setcap failed — open port 80 in security group; you may need sudo / nginx proxy."
fi

WEB_PORT="$(grep -E '^WEB_PORT=' "${APP_DIR}/.env" 2>/dev/null | cut -d= -f2- | tr -d '\r' || true)"
WEB_PORT="${WEB_PORT:-8080}"
log "Web dashboard port: ${WEB_PORT} (set WEB_PORT=80 in .env for port 80)"

log "Installing systemd unit (${UNIT_PATH})..."
TMP_UNIT="$(mktemp)"
sed \
  -e "s|__SERVICE_USER__|${SERVICE_USER}|g" \
  -e "s|__APP_DIR__|${APP_DIR}|g" \
  -e "s|__WEB_PORT__|${WEB_PORT}|g" \
  "${APP_DIR}/deploy/alphaabed.service" > "${TMP_UNIT}"
$SUDO cp "${TMP_UNIT}" "${UNIT_PATH}"
rm -f "${TMP_UNIT}"

$SUDO chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}"

log "Enabling and starting ${SERVICE_NAME}..."
$SUDO systemctl daemon-reload
$SUDO systemctl enable "${SERVICE_NAME}"
$SUDO systemctl restart "${SERVICE_NAME}"

log "Done. Status:"
$SUDO systemctl --no-pager status "${SERVICE_NAME}" || true

sleep 4
if curl -sf -m 10 "http://127.0.0.1:${WEB_PORT}/health" >/dev/null; then
  PUB="$(curl -sf -m 2 http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo YOUR_EC2_IP)"
  log "Dashboard OK: http://${PUB}:${WEB_PORT}/"
  log "Open EC2 security group: inbound TCP ${WEB_PORT}"
else
  die "Service did not respond on port ${WEB_PORT}. Run: chmod +x diagnose.sh && ./diagnose.sh"
fi
log "Logs: sudo journalctl -u ${SERVICE_NAME} -f"
