#!/usr/bin/env bash
set -euo pipefail

APP_NAME="anouk"
APP_DIR="/var/www/anouk"
APP_USER="www-data"
APP_GROUP="www-data"
SERVICE_NAME="anouk-monitor"
PORT="8017"
DOMAIN="${1:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BASIC_AUTH_USER="${BASIC_AUTH_USER:-anouk}"
BASIC_AUTH_PASSWORD="${BASIC_AUTH_PASSWORD:-}"
HTPASSWD_FILE="/etc/nginx/.htpasswd-${APP_NAME}"

if [[ -z "${DOMAIN}" ]]; then
  echo "Usage: sudo bash scripts/setup-ubuntu.sh monitor.example.com"
  echo
  echo "Run dit vanaf de projectroot nadat je project in ${APP_DIR} staat."
  exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run dit script met sudo."
  exit 1
fi

if [[ ! -d "${APP_DIR}" ]]; then
  echo "Projectmap bestaat niet: ${APP_DIR}"
  echo "Zet de projectbestanden eerst in ${APP_DIR}."
  exit 1
fi

cd "${APP_DIR}"

echo "==> System packages installeren"
apt-get update
apt-get install -y \
  apache2-utils \
  curl \
  nginx \
  openssl \
  python3 \
  python3-pip \
  python3-venv

PYTHON_VERSION="$("${PYTHON_BIN}" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"

if ! "${PYTHON_BIN}" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
then
  echo "Scrapling 0.4.8 vereist Python 3.10+. Gevonden: ${PYTHON_VERSION}."
  echo "Installeer Python 3.10+ of draai met: sudo PYTHON_BIN=/pad/naar/python3.12 bash scripts/setup-ubuntu.sh ${DOMAIN}"
  exit 1
fi

echo "==> Python virtualenv maken"
"${PYTHON_BIN}" -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

echo "==> Scrapling browser assets installeren"
"${APP_DIR}/.venv/bin/scrapling" install

echo "==> Rechten zetten"
chown -R "${APP_USER}:${APP_GROUP}" "${APP_DIR}"

if [[ -z "${BASIC_AUTH_PASSWORD}" ]]; then
  BASIC_AUTH_PASSWORD="$(openssl rand -base64 24 | tr -d '\n')"
  GENERATED_PASSWORD="1"
else
  GENERATED_PASSWORD="0"
fi

echo "==> Basic Auth voor Nginx instellen"
htpasswd -bc "${HTPASSWD_FILE}" "${BASIC_AUTH_USER}" "${BASIC_AUTH_PASSWORD}" >/dev/null
chown root:www-data "${HTPASSWD_FILE}"
chmod 640 "${HTPASSWD_FILE}"

echo "==> systemd service schrijven"
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<SERVICE
[Unit]
Description=Solebox Scrapling Monitor
After=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}
Environment=PYTHONUNBUFFERED=1
Environment=SOLVE_CLOUDFLARE=0
ExecStart=${APP_DIR}/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port ${PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

echo "==> Nginx site schrijven"
cat > "/etc/nginx/sites-available/${APP_NAME}" <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    client_max_body_size 10M;

    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "no-referrer" always;
    add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;

    location / {
        auth_basic "Anouk monitor";
        auth_basic_user_file ${HTPASSWD_FILE};

        proxy_pass http://127.0.0.1:${PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
NGINX

ln -sfn "/etc/nginx/sites-available/${APP_NAME}" "/etc/nginx/sites-enabled/${APP_NAME}"
nginx -t

echo "==> Services starten"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"
systemctl reload nginx

echo
echo "Klaar. Open: http://${DOMAIN}"
echo "Login gebruiker: ${BASIC_AUTH_USER}"
if [[ "${GENERATED_PASSWORD}" == "1" ]]; then
  echo "Login wachtwoord: ${BASIC_AUTH_PASSWORD}"
  echo "Bewaar dit wachtwoord nu. Het wordt niet opnieuw getoond."
else
  echo "Login wachtwoord: gebruikt uit BASIC_AUTH_PASSWORD."
fi
echo
echo "Handige checks:"
echo "  systemctl status ${SERVICE_NAME}"
echo "  journalctl -u ${SERVICE_NAME} -f"
echo "  nginx -t"
echo
echo "Voor HTTPS, na DNS:"
echo "  apt-get install -y certbot python3-certbot-nginx"
echo "  certbot --nginx -d ${DOMAIN}"
