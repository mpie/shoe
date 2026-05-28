#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3.11}"
APP_NAME="SoleboxMonitor"
ICONSET="assets/${APP_NAME}.iconset"
ICON_ICNS="assets/${APP_NAME}.icns"

cd "$(dirname "$0")/.."

echo "==> Build venv maken"
rm -rf .build-venv build dist "${APP_NAME}.spec"
"${PYTHON_BIN}" -m venv .build-venv
.build-venv/bin/python -m pip install --upgrade pip
.build-venv/bin/pip install -r requirements.txt -r requirements-build.txt

echo "==> App icon maken"
rm -rf "${ICONSET}" "${ICON_ICNS}"
.build-venv/bin/python scripts/make_icon.py --iconset "${ICONSET}"
iconutil -c icns "${ICONSET}" -o "${ICON_ICNS}"

ICON_ARGS=()
if [[ -f "${ICON_ICNS}" ]]; then
  ICON_ARGS=(--icon "${ICON_ICNS}")
fi

echo "==> macOS app bouwen"
.build-venv/bin/pyinstaller \
  --noconfirm \
  --windowed \
  --name "${APP_NAME}" \
  "${ICON_ARGS[@]}" \
  --add-data "static:static" \
  --collect-all scrapling \
  --collect-all browserforge \
  --collect-all apify_fingerprint_datapoints \
  --collect-all playwright \
  --collect-all patchright \
  desktop_launcher.py

echo
echo "Klaar: dist/${APP_NAME}.app"
echo
echo "Unsigned app openen op eigen Mac:"
echo "  xattr -dr com.apple.quarantine \"dist/${APP_NAME}.app\""
echo "  open \"dist/${APP_NAME}.app\""
echo
echo "Als Playwright Chromium nog mist op een doelmachine:"
echo "  python3.11 -m pip install playwright==1.59.0"
echo "  python3.11 -m playwright install chromium"
