#!/usr/bin/env bash
# Run the full local dev stack: Cloudflare Worker (serves /api and /assets) +
# Vite dev server (serves the React UI with hot reload). One command, Ctrl-C
# stops both.
set -euo pipefail

# Run from the repo root regardless of where it was invoked from.
cd "$(dirname "$0")"

# Python Workers (Pyodide) require Node 22; Node 24+ dropped the wasm flag.
if [ -d /opt/homebrew/opt/node@22/bin ]; then
  export PATH="/opt/homebrew/opt/node@22/bin:$PATH"
fi

# One-time frontend setup.
if [ ! -d webui/node_modules ]; then
  echo ">> Installing webui dependencies..."
  (cd webui && npm install)
fi
if [ ! -d webui/dist ]; then
  echo ">> Building webui/dist (wrangler needs the assets dir to exist)..."
  (cd webui && npm run build)
fi

if [ ! -f wrangler.local.jsonc ]; then
  echo "!! wrangler.local.jsonc not found." >&2
  echo "   Create it from wrangler.jsonc with your D1 database_id filled in:" >&2
  echo "   sed 's/\"database_id\": \"\"/\"database_id\": \"<id>\"/' wrangler.jsonc > wrangler.local.jsonc" >&2
  exit 1
fi

# Start the Worker in the background (serves /api/board, /health, /assets/*).
npx wrangler dev --port 8787 --local --config wrangler.local.jsonc &
WRANGLER_PID=$!
cleanup() {
  kill "$WRANGLER_PID" 2>/dev/null || true
  wait "$WRANGLER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Wait until the Worker is ready before starting Vite, so the first /api/board
# request from the UI succeeds.
echo ">> Waiting for Worker on http://localhost:8787 ..."
for _ in $(seq 1 90); do
  if curl -sf http://localhost:8787/health >/dev/null 2>&1; then
    echo ">> Worker ready."
    break
  fi
  sleep 1
done

# Start Vite in the foreground. The EXIT/INT/TERM trap kills the Worker on exit.
cd webui
PATH="$PWD/node_modules/.bin:$PATH" vite &
VITE_PID=$!
cleanup() {
  kill "$VITE_PID" "$WRANGLER_PID" 2>/dev/null || true
  wait "$VITE_PID" "$WRANGLER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
wait "$VITE_PID"