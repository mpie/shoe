#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${CERTBOT_EMAIL:-}"

if [[ -z "${DOMAIN}" ]]; then
  echo "Usage: sudo bash scripts/enable-ssl.sh anouk.googeng.com"
  echo
  echo "Optioneel met email:"
  echo "  sudo CERTBOT_EMAIL='jij@googeng.com' bash scripts/enable-ssl.sh anouk.googeng.com"
  exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run dit script met sudo."
  exit 1
fi

echo "==> Certbot installeren"
apt-get update
apt-get install -y certbot python3-certbot-nginx

echo "==> Nginx config check"
nginx -t

echo "==> Certificaat aanvragen voor ${DOMAIN}"
if [[ -n "${EMAIL}" ]]; then
  certbot --nginx \
    -d "${DOMAIN}" \
    --non-interactive \
    --agree-tos \
    --email "${EMAIL}" \
    --redirect
else
  certbot --nginx \
    -d "${DOMAIN}" \
    --redirect
fi

echo "==> Renewal check"
systemctl list-timers | grep certbot || true
certbot renew --dry-run

echo
echo "SSL staat aan voor: https://${DOMAIN}"
