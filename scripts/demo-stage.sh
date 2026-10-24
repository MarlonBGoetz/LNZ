#!/usr/bin/env bash
# Launch the LNZ stage preview in Chrome for Testing / Chromium.
#
# Branded Chrome 137+ ignores --load-extension, so this script looks for a
# Chromium-based test build. Override with:
#   CHROME_FOR_TESTING=/path/to/Chromium
#   LNZ_DEMO_PROFILE=/path/to/profile   (keeps PIN/config between runs)
#   LNZ_CDP_PORT=9222 LNZ_WINDOW_SIZE=1512,949
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f extension/dist/content.js ]]; then
  npm run build:ext
fi

# The unpacked-extension ID is SHA-256(path), first 16 bytes mapped to a-p.
EXT_ID="$(node -e '
const path = require("path");
const crypto = require("crypto");
const p = path.resolve("extension/dist");
const h = crypto.createHash("sha256").update(p).digest().subarray(0, 16);
process.stdout.write([...h].map((b) => String.fromCharCode(97 + (b >> 4)) + String.fromCharCode(97 + (b & 15))).join(""));
')"

PROFILE="${LNZ_DEMO_PROFILE:-$ROOT/.chrome-demo}"
PORT="${LNZ_CDP_PORT:-9222}"
WINDOW="${LNZ_WINDOW_SIZE:-1512,949}"
if [[ "${LNZ_STAGE:-tiktok}" == "x" ]]; then
  STAGE="http://localhost:5174/stage/x.html?platform=x"
else
  STAGE="http://localhost:5174/stage/tiktok.html"
fi

CHROME="${CHROME_FOR_TESTING:-}"
if [[ -z "$CHROME" ]]; then
  shopt -s nullglob
  for candidate in \
    "$HOME/Library/Caches/ms-playwright"/chromium-*/chrome-mac*/"Google Chrome for Testing.app"/Contents/MacOS/"Google Chrome for Testing" \
    "$HOME/Library/Caches/ms-playwright"/chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium \
    "/Applications/Chromium.app/Contents/MacOS/Chromium" \
    "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"; do
    if [[ -x "$candidate" ]]; then CHROME="$candidate"; break; fi
  done
fi

if [[ -z "$CHROME" || ! -x "$CHROME" ]]; then
  cat >&2 <<'EOF'
No Chrome for Testing / Chromium binary found.

Install one, or set CHROME_FOR_TESTING to its executable, for example:
  CHROME_FOR_TESTING="/path/to/Chromium" ./scripts/demo-stage.sh

For daily Chrome, load extension/dist manually at chrome://extensions.
EOF
  exit 1
fi

mkdir -p "$PROFILE"
echo "Stage:     $STAGE"
echo "Profile:   $PROFILE"
echo "Dashboard: http://localhost:5174  (run: npm run dev:analytics)"
echo

exec "$CHROME" \
  --user-data-dir="$PROFILE" \
  --load-extension="$ROOT/extension/dist" \
  --disable-extensions-except="$ROOT/extension/dist" \
  --no-first-run \
  --no-default-browser-check \
  --no-sandbox \
  --disable-gpu \
  --disable-dev-shm-usage \
  --remote-debugging-port="$PORT" \
  --window-size="$WINDOW" \
  "$STAGE"
