#!/bin/bash
# 本地跑分：直接用已加载的 eva-mimir-solver:latest 镜像 docker run，跳过 docker build。
#
# 背景：run.sh 里的 `docker build -f docker/Dockerfile` 需要拉 ubuntu:22.04 基础镜像，
# 本地/离线环境常超时。此脚本绕开 build，直接 docker run。
#
# 用法：和 run.sh 一致，读 .env 的 BENCHMARK_TOKEN / BENCHMARK_BASE_URL / LLM_* / SOLVER_*。
#   ./scripts/local_run.sh

set -eo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SOLVER_IMAGE="${SOLVER_IMAGE:-eva-mimir-solver:latest}"

cd "$PROJECT_DIR"

# 读 .env
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$PROJECT_DIR/.env"
    set +a
fi

TOKEN="${BENCHMARK_TOKEN:-}"
BASE_URL="${BENCHMARK_BASE_URL:-https://tsecbench.zc.tencent.com}"

if [ -z "$TOKEN" ]; then
    echo "请先设置 BENCHMARK_TOKEN（可在 .env 中配置）。" >&2
    exit 1
fi

# 检查镜像存在（若不存在，提示先 docker load agent.tar.gz）
if ! docker image inspect "$SOLVER_IMAGE" >/dev/null 2>&1; then
    echo "镜像 $SOLVER_IMAGE 不存在。请先：" >&2
    echo "  docker load < agent.tar.gz" >&2
    exit 1
fi

# 检查 VPN
echo "[1/3] 检查 VPN..."
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^tsec-vpn$'; then
    VPN_RESP=$(docker exec tsec-vpn sh -c "curl -s --connect-timeout 5 http://10.0.100.58" 2>/dev/null || true)
    if echo "$VPN_RESP" | grep -q '"status":"ok"'; then
        echo "  ✅ VPN 已连接"
    else
        echo "  ❌ VPN 不通，请先 ./vpn.sh <ovpn>"; exit 1
    fi
else
    echo "  ❌ 无 tsec-vpn 容器，请先 ./vpn.sh <ovpn>"; exit 1
fi

# 清理旧容器 + 旧的 retry/空 settings（历史遗留空文件会导致配置加载失败）
echo "[2/3] 清理旧状态..."
docker rm -f eva-mimir-run 2>/dev/null || true
rm -f workspace/.scheduler-retry-ledger.json workspace/settings.json workspace/settings.local.json

# 组装 LLM 环境变量（.env 已 source，这里按 run.sh 的规则显式覆盖镜像 ENV）
LLM_ENV=()
[ -n "${LLM_API_KEY:-}" ] && LLM_ENV+=(-e "LLM_API_KEY=${LLM_API_KEY}")
[ -n "${LLM_BASE_URL:-}" ] && LLM_ENV+=(-e "LLM_BASE_URL=${LLM_BASE_URL}")
[ -n "${LLM_MODEL:-}" ] && LLM_ENV+=(-e "LLM_MODEL=${LLM_MODEL}")
[ -n "${LLM_GATEWAY:-}" ] && LLM_ENV+=(-e "LLM_GATEWAY=${LLM_GATEWAY}")

ONLY_ENV=()
[ -n "${SOLVER_ONLY_CODES:-}" ] && ONLY_ENV+=(-e "SOLVER_ONLY_CODES=${SOLVER_ONLY_CODES}")
[ -n "${SOLVER_PREFIX_FILTER:-}" ] && ONLY_ENV+=(-e "SOLVER_PREFIX_FILTER=${SOLVER_PREFIX_FILTER}")
[ -n "${SOLVER_RSI_PACK:-}" ] && ONLY_ENV+=(-e "SOLVER_RSI_PACK=${SOLVER_RSI_PACK}")

echo "[3/3] 启动评测（镜像 $SOLVER_IMAGE）..."
docker run --rm --network host \
  --name eva-mimir-run \
  -e BENCHMARK_BASE_URL="$BASE_URL" \
  -e BENCHMARK_TOKEN="$TOKEN" \
  -e CTF_WORKSPACE=/workspace \
  -e CTF_SKILLS_DIR=/skills \
  -e SOLVER_MAX_PARALLEL="${SOLVER_MAX_PARALLEL:-3}" \
  -e SOLVER_MAX_RETRY_ROUNDS="${SOLVER_MAX_RETRY_ROUNDS:-5}" \
  -e SOLVER_TOTAL_TIMEOUT="${SOLVER_TOTAL_TIMEOUT:-350}" \
  -e LLM_MAX_CONCURRENCY="${LLM_MAX_CONCURRENCY:-4}" \
  "${LLM_ENV[@]}" \
  "${ONLY_ENV[@]}" \
  -v "$PROJECT_DIR/settings.local.json:/workspace/settings.local.json:ro" \
  -v "$PROJECT_DIR/workspace:/workspace" \
  -v "$PROJECT_DIR/skills:/opt/ctf-agent/skills:ro" \
  -v "$PROJECT_DIR/prompts:/opt/ctf-agent/prompts:ro" \
  -v "$PROJECT_DIR/solver:/opt/ctf-agent/solver:ro" \
  -v "$PROJECT_DIR/shared:/opt/ctf-agent/shared:ro" \
  "$SOLVER_IMAGE"

echo ""
echo "本地跑分结束。查看 workspace/scoreboard.md 或 workspace/rsi-report.md"
