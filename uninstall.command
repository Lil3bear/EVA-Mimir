#!/bin/bash
set -e
SOURCE="$(cd "$(dirname "$0")" && pwd)"
cd "$SOURCE"
NODE_BIN="$(command -v node || true)"
if [ -z "$NODE_BIN" ]; then
  NODE_BIN="/Applications/DeepSeek Harness.app/Contents/MacOS/DeepSeek Harness"
  export ELECTRON_RUN_AS_NODE=1
fi
exec "$NODE_BIN" scripts/install-dsh.mjs --uninstall
