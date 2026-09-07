#!/bin/bash
# EVA-Mimir 一键启动脚本
# 用法：BENCHMARK_TOKEN=... ./run.sh [PREFIX_FILTER]

set -eo pipefail

PREFIX_FILTER="${1:-}"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

# rsi_local.sh 等脚本会先 export 题号/ pack；.env 里若有同名变量不能覆盖它们。
_PRESERVE_ONLY_CODES="${SOLVER_ONLY_CODES:-}"
_PRESERVE_RSI_PACK="${SOLVER_RSI_PACK:-}"
_PRESERVE_PREFIX_FILTER="${SOLVER_PREFIX_FILTER:-}"
_PRESERVE_TOTAL_TIMEOUT="${SOLVER_TOTAL_TIMEOUT:-}"
_PRESERVE_MAX_PARALLEL="${SOLVER_MAX_PARALLEL:-}"

# 从项目内 .env 读取 Tsecbench 配置（不提交到版本库）
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$PROJECT_DIR/.env"
    set +a
fi

if [ -n "$_PRESERVE_ONLY_CODES" ]; then export SOLVER_ONLY_CODES="$_PRESERVE_ONLY_CODES"; fi
if [ -n "$_PRESERVE_RSI_PACK" ]; then export SOLVER_RSI_PACK="$_PRESERVE_RSI_PACK"; fi
if [ -n "$_PRESERVE_PREFIX_FILTER" ]; then export SOLVER_PREFIX_FILTER="$_PRESERVE_PREFIX_FILTER"; fi
if [ -n "$_PRESERVE_TOTAL_TIMEOUT" ]; then export SOLVER_TOTAL_TIMEOUT="$_PRESERVE_TOTAL_TIMEOUT"; fi
if [ -n "$_PRESERVE_MAX_PARALLEL" ]; then export SOLVER_MAX_PARALLEL="$_PRESERVE_MAX_PARALLEL"; fi

TOKEN="${BENCHMARK_TOKEN:-}"
BASE_URL="${BENCHMARK_BASE_URL:-https://tsecbench.zc.tencent.com}"
SOLVER_IMAGE="${SOLVER_IMAGE:-eva-mimir-solver:latest}"
SOLVER_PLATFORM="${SOLVER_PLATFORM:-linux/amd64}"

if [ -z "$TOKEN" ]; then
    echo "请先设置 BENCHMARK_TOKEN（可在项目根目录 .env 中配置）。" >&2
    exit 1
fi

if [ ! -f "$PROJECT_DIR/settings.local.json" ] && [ ! -f "$PROJECT_DIR/settings.json" ]; then
    echo "未找到 settings.local.json/settings.json，将仅使用运行时环境变量。"
fi

echo "============================================"
echo "  EVA-Mimir 一键启动"
echo "  Token: ${TOKEN:0:8}..."
if [ -n "$PREFIX_FILTER" ]; then
    echo "  前缀过滤: $PREFIX_FILTER (只跑此类题目)"
fi
echo "  $(date)"
echo "============================================"

# ---- 检查 VPN ----
echo ""
echo "[1/4] 检查 VPN..."
# VPN 以 --network host 运行在 docker 的 Linux VM 网络命名空间中，
# 因此不能直接用宿主机 macOS 的 curl 检测，需在 host 网络命名空间内检测。
VPN_RESP=""
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^tsec-vpn$'; then
    VPN_RESP=$(docker exec tsec-vpn sh -c "curl -s --connect-timeout 5 http://10.0.100.58" 2>/dev/null || true)
fi
if echo "$VPN_RESP" | grep -q '"status":"ok"'; then
    echo "  ✅ VPN 已连接"
else
    echo "  ❌ VPN 不通，请先运行 ./vpn.sh 连接 OpenVPN"
    echo "     响应: $VPN_RESP"
    exit 1
fi

# ---- 检查 Docker ----
echo "[2/4] 检查 Docker..."
if ! docker ps &>/dev/null; then
    echo "  ❌ Docker 未运行，请启动 Docker Desktop"
    exit 1
fi
echo "  ✅ Docker 运行中"

# ---- 每次走 Docker 缓存构建，确保依赖和镜像内代码不漂移 ----
echo "[3/4] 构建镜像..."
cd "$PROJECT_DIR"
BUILD_ARGS=(--platform "$SOLVER_PLATFORM")
case "$SOLVER_PLATFORM" in
    *arm64*|*aarch64*) BUILD_ARGS+=(--build-arg APT_MIRROR=http://ports.ubuntu.com/ubuntu-ports/) ;;
esac
if [ "${FORCE_BUILD:-0}" = "1" ]; then
    BUILD_ARGS+=(--no-cache)
fi
docker build "${BUILD_ARGS[@]}" -t "$SOLVER_IMAGE" -f docker/Dockerfile . 2>&1 | tail -3
echo "  ✅ 镜像已同步（${SOLVER_PLATFORM}）"

# ---- 清理旧容器 ----
docker rm -f eva-mimir-run 2>/dev/null || true

# ---- 启动 ----
echo "[4/4] 启动解题..."
echo ""
PREFIX_ENV=()
if [ -n "$PREFIX_FILTER" ]; then
    PREFIX_ENV=(-e "SOLVER_PREFIX_FILTER=$PREFIX_FILTER")
fi
ONLY_CODES_ENV=()
if [ -n "${SOLVER_ONLY_CODES:-}" ]; then
    ONLY_CODES_ENV=(-e "SOLVER_ONLY_CODES=$SOLVER_ONLY_CODES")
fi
RSI_PACK_ENV=()
if [ -n "${SOLVER_RSI_PACK:-}" ]; then
    RSI_PACK_ENV=(-e "SOLVER_RSI_PACK=$SOLVER_RSI_PACK")
fi
SETTINGS_MOUNT=()
if [ -f "$PROJECT_DIR/settings.json" ]; then
    SETTINGS_MOUNT+=(-v "$PROJECT_DIR/settings.json:/workspace/settings.json:ro")
fi
if [ -f "$PROJECT_DIR/settings.local.json" ]; then
    SETTINGS_MOUNT+=(-v "$PROJECT_DIR/settings.local.json:/workspace/settings.local.json:ro")
fi

# LLM 环境变量：仅在显式设置时覆盖镜像 ENV 默认；否则用镜像内置配置。
LLM_ENV_ARGS=()
if [ -n "${LLM_BASE_URL:-}" ]; then LLM_ENV_ARGS+=(-e "LLM_BASE_URL=${LLM_BASE_URL}"); fi
if [ -n "${LLM_API_KEY:-}" ]; then LLM_ENV_ARGS+=(-e "LLM_API_KEY=${LLM_API_KEY}"); fi
if [ -n "${LLM_MODEL:-}" ]; then LLM_ENV_ARGS+=(-e "LLM_MODEL=${LLM_MODEL}"); fi
if [ -n "${LLM_PRO_MODEL:-}" ]; then LLM_ENV_ARGS+=(-e "LLM_PRO_MODEL=${LLM_PRO_MODEL}"); fi
if [ -n "${LLM_GATEWAY:-}" ]; then LLM_ENV_ARGS+=(-e "LLM_GATEWAY=${LLM_GATEWAY}"); fi

docker run --rm --network host \
  --name eva-mimir-run \
  -e BENCHMARK_BASE_URL="$BASE_URL" \
  -e BENCHMARK_TOKEN="$TOKEN" \
  -e CTF_WORKSPACE=/workspace \
  -e CTF_SKILLS_DIR=/skills \
  -e SOLVER_MAX_PARALLEL="${SOLVER_MAX_PARALLEL:-3}" \
  -e SOLVER_MAX_RETRY_ROUNDS="${SOLVER_MAX_RETRY_ROUNDS:-5}" \
  -e SOLVER_TOTAL_TIMEOUT="${SOLVER_TOTAL_TIMEOUT:-360}" \
  -e SOLVER_BENCHMARK_MINUTES="${SOLVER_BENCHMARK_MINUTES:-360}" \
  -e LLM_MAX_CONCURRENCY="${LLM_MAX_CONCURRENCY:-4}" \
  "${LLM_ENV_ARGS[@]}" \
  "${PREFIX_ENV[@]}" \
  "${ONLY_CODES_ENV[@]}" \
  "${RSI_PACK_ENV[@]}" \
  "${SETTINGS_MOUNT[@]}" \
  -v "$PROJECT_DIR/workspace:/workspace" \
  -v "$PROJECT_DIR/skills:/opt/ctf-agent/skills:ro" \
  -v "$PROJECT_DIR/prompts:/opt/ctf-agent/prompts:ro" \
  -v "$PROJECT_DIR/solver:/opt/ctf-agent/solver:ro" \
  -v "$PROJECT_DIR/shared:/opt/ctf-agent/shared:ro" \
  "$SOLVER_IMAGE"

echo ""
echo "============================================"
echo "  运行结束"
echo "  查看结果: cat workspace/scoreboard.md"
echo "============================================"
