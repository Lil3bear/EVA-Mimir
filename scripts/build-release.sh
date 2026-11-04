#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(node -p "require('$ROOT/package.json').version")"
NAME="mimir-pi-$VERSION"
STAGE="$ROOT/release/$NAME"
rm -rf "$STAGE"
mkdir -p "$STAGE"

cd "$ROOT"
npm run build
cp -R dist server pi skills "$STAGE/"
mkdir -p "$STAGE/dsh" "$STAGE/scripts"
cp -R dsh/mimir "$STAGE/dsh/"
cp scripts/install-dsh.mjs "$STAGE/scripts/"
cp install.command uninstall.command "$STAGE/"
chmod +x "$STAGE/install.command" "$STAGE/uninstall.command" "$STAGE/scripts/install-dsh.mjs"

node - "$ROOT" "$STAGE" <<'NODE'
const fs = require("fs");
const root = process.argv[2], stage = process.argv[3];
const source = JSON.parse(fs.readFileSync(root + "/package.json", "utf8"));
const keep = ["express", "multer", "adm-zip", "@retorquere/bibtex-parser", "pdfjs-dist", "zod"];
const pkg = {name: "mimir-pi", version: source.version, private: true, type: "module",
  dependencies: Object.fromEntries(keep.map(k => [k, source.dependencies[k]]))};
fs.writeFileSync(stage + "/package.json", JSON.stringify(pkg, null, 2) + "\n");
NODE

cat > "$STAGE/README-INSTALL.md" <<'MD'
# mimir-pi 轻量安装

1. 先安装并打开一次 DeepSeek Harness（需要它的模型凭据）。
2. 解压本目录，双击 `install.command`。
3. 完全退出并重新打开 DeepSeek Harness。
4. 在 DSH 输入 `/mimir`。

LaTeX 是可选的：没有 `pdflatex` 仍可编辑、审稿、翻译；编译 PDF 需要 MacTeX。
论文数据在 `~/.local/share/mimir-pi`，卸载不会删除。
卸载：双击 `uninstall.command`。
MD

cd "$STAGE"
npm install --omit=dev --ignore-scripts --no-audit --no-fund >/tmp/mimir-release-install.log 2>&1
cd "$ROOT/release"
tar -czf "$NAME-macos.tar.gz" "$NAME"
echo "release/$NAME-macos.tar.gz"
du -sh "$NAME" "$NAME-macos.tar.gz"
