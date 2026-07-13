#!/usr/bin/env bash
# Downloads the Chart.js UMD bundle into app/static/vendor/ so the frontend
# never depends on a CDN at runtime.
set -euo pipefail
VERSION="4.4.4"
URL="https://cdn.jsdelivr.net/npm/chart.js@${VERSION}/dist/chart.umd.min.js"
OUT="$(cd "$(dirname "$0")/.." && pwd)/app/static/vendor/chart.umd.min.js"
mkdir -p "$(dirname "$OUT")"
if command -v curl >/dev/null; then
  curl -fsSL "$URL" -o "$OUT"
elif command -v wget >/dev/null; then
  wget -qO "$OUT" "$URL"
else
  echo "Need curl or wget to fetch Chart.js" >&2
  exit 1
fi
echo "Vendored Chart.js ${VERSION} -> $OUT"
