#!/bin/bash
set -e
SOURCE="$(cd "$(dirname "$0")" && pwd)"
cd "$SOURCE"
APP_DIR="${MIMIR_APP_DIR:-$HOME/.local/share/mimir-pi/app}"
if [ "$SOURCE" != "$APP_DIR" ]; then
  echo "正在复制到稳定目录：$APP_DIR"
  mkdir -p "$(dirname "$APP_DIR")"
  rm -rf "$APP_DIR"
  cp -R "$SOURCE" "$APP_DIR"
  exec "$APP_DIR/install.command"
fi
NODE_BIN="$(command -v node || true)"
if [ -z "$NODE_BIN" ]; then
  NODE_BIN="/Applications/DeepSeek Harness.app/Contents/MacOS/DeepSeek Harness"
  export ELECTRON_RUN_AS_NODE=1
fi
exec "$NODE_BIN" scripts/install-dsh.mjs
