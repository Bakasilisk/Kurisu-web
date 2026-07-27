#!/usr/bin/env bash
# Downloads third-party frontend assets into app/static/vendor/ so the
# frontend never depends on a CDN at runtime.
set -euo pipefail
VENDOR="$(cd "$(dirname "$0")/.." && pwd)/app/static/vendor"
mkdir -p "$VENDOR"

fetch() {
  local url="$1" out="$2"
  if command -v curl >/dev/null; then
    curl -fsSL "$url" -o "$out"
  elif command -v wget >/dev/null; then
    wget -qO "$out" "$url"
  else
    echo "Need curl or wget to fetch vendor assets" >&2
    exit 1
  fi
}

VERSION="4.4.4"
fetch "https://cdn.jsdelivr.net/npm/chart.js@${VERSION}/dist/chart.umd.min.js" \
  "$VENDOR/chart.umd.min.js"
echo "Vendored Chart.js ${VERSION} -> $VENDOR/chart.umd.min.js"

# Inter Variable, latin subset, weights 100-900. Referenced by the
# @font-face at the top of app/static/css/style.css.
fetch "https://cdn.jsdelivr.net/npm/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2" \
  "$VENDOR/inter-var.woff2"
echo "Vendored Inter Variable -> $VENDOR/inter-var.woff2"
