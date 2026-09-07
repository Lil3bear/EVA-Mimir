#!/bin/bash
# RSI 本地回归：按 pack 跑子集 → 自动生成 rsi-report.md
#
# 用法：
#   BENCHMARK_TOKEN=... ./scripts/rsi_local.sh web          # web 维度
#   BENCHMARK_TOKEN=... ./scripts/rsi_local.sh pentest 180  # 自定义超时（分钟）
#
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PACK="${1:?用法: $0 <pack> [timeout_min]  例: ./scripts/rsi_local.sh web 120}"
TIMEOUT_MIN="${2:-}"

cd "$PROJECT_DIR"

# 解析 pack → SOLVER_ONLY_CODES（prefix-only pack 走 SOLVER_PREFIX_FILTER）
CODES=""
PREFIX=""
if python3 -c "import solver.rsi" 2>/dev/null; then
  CODES=$(python3 -m solver.rsi codes "$PACK" 2>/dev/null || true)
  PREFIX=$(python3 - <<'PY' "$PACK"
import sys
from solver.runtime.settings import load_settings
from solver.rsi.packs import pack_prefix_filter
print(pack_prefix_filter(sys.argv[1], load_settings()) or "")
PY
)
fi

export SOLVER_RSI_PACK="$PACK"
if [ -n "$CODES" ]; then
  export SOLVER_ONLY_CODES="$CODES"
  echo "[RSI] pack=$PACK codes=$CODES"
elif [ -n "$PREFIX" ]; then
  export SOLVER_PREFIX_FILTER="$PREFIX"
  echo "[RSI] pack=$PACK prefix_filter=$PREFIX"
else
  echo "[RSI] 未知 pack: $PACK（见 python3 -m solver.rsi list-packs）" >&2
  exit 1
fi

if [ -z "$TIMEOUT_MIN" ]; then
  TIMEOUT_MIN=$(python3 - <<'PY'
import json
from pathlib import Path
for name in ("settings.local.json", "settings.json"):
    p = Path(name)
    if p.is_file():
        rsi = json.loads(p.read_text()).get("rsi") or {}
        print(rsi.get("local_timeout_minutes", 120))
        break
else:
    print(120)
PY
)
fi
export SOLVER_TOTAL_TIMEOUT="$TIMEOUT_MIN"
echo "[RSI] SOLVER_TOTAL_TIMEOUT=${TIMEOUT_MIN}min"

# 回归 pack 题数少时串行启动，避免平台 3 实例槽位被并行 start 占满。
if [ -n "$CODES" ]; then
  CODE_COUNT=$(echo "$CODES" | tr ',' '\n' | grep -c . || true)
  if [ "${CODE_COUNT:-0}" -le 8 ]; then
    export SOLVER_MAX_PARALLEL="${SOLVER_MAX_PARALLEL:-1}"
    echo "[RSI] SOLVER_MAX_PARALLEL=${SOLVER_MAX_PARALLEL} (small pack)"
  fi
fi

"$PROJECT_DIR/scripts/local_run.sh"

echo ""
echo "[RSI] 分析工作区..."
python3 -m solver.rsi analyze --workspace "$PROJECT_DIR/workspace" --pack "$PACK" || true
echo "[RSI] 查看: cat workspace/rsi-report.md"
