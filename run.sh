#!/bin/bash
# CTF Agent 一键启动脚本
# 用法：./run.sh <BENCHMARK_TOKEN>
# 示例：./run.sh 6f395a9a-bd2b-4f54-8516-b12fcf31b6f7

set -e

TOKEN="${1:?请提供 BENCHMARK_TOKEN，用法：./run.sh <TOKEN>}"
BASE_URL="https://tsecbench.zc.tencent.com"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================"
echo "  CTF Agent 一键启动"
echo "  Token: ${TOKEN:0:8}..."
echo "  $(date)"
echo "============================================"

# ---- 检查 VPN ----
echo ""
echo "[1/4] 检查 VPN..."
VPN_RESP=$(curl -s --connect-timeout 5 http://10.0.100.58 2>&1 || true)
if echo "$VPN_RESP" | grep -q '"status":"ok"'; then
    echo "  ✅ VPN 已连接"
else
    echo "  ❌ VPN 不通，请先连接 OpenVPN"
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

# ---- 构建镜像（仅当镜像不存在或强制构建时） ----
echo "[3/4] 构建镜像..."
cd "$PROJECT_DIR"
if [ "${FORCE_BUILD:-0}" = "1" ] || ! docker inspect ctf-agent-solver:latest &>/dev/null; then
    docker build -t ctf-agent-solver:latest -f docker/Dockerfile . 2>&1 | tail -3
    echo "  ✅ 镜像构建完成"
else
    echo "  ✅ 镜像已存在，跳过构建（FORCE_BUILD=1 可强制重建）"
fi

# ---- 清理旧容器 ----
docker rm -f ctf-agent-run 2>/dev/null || true

# ---- 启动 ----
echo "[4/4] 启动解题..."
echo ""
docker run --rm --network host \
  --name ctf-agent-run \
  -e BENCHMARK_BASE_URL="$BASE_URL" \
  -e BENCHMARK_TOKEN="$TOKEN" \
  -e CTF_WORKSPACE=/workspace \
  -e CTF_SKILLS_DIR=/skills \
  -e SOLVER_MAX_PARALLEL=3 \
  -e SOLVER_MAX_RETRY_ROUNDS=5 \
  -e SOLVER_TOTAL_TIMEOUT=350 \
  -v "$PROJECT_DIR/settings.local.json:/workspace/settings.local.json:ro" \
  -v "$PROJECT_DIR/workspace:/workspace" \
  -v "$PROJECT_DIR/skills:/opt/ctf-agent/skills:ro" \
  -v "$PROJECT_DIR/prompts:/opt/ctf-agent/prompts:ro" \
  -v "$PROJECT_DIR/solver:/opt/ctf-agent/solver:ro" \
  -v "$PROJECT_DIR/shared:/opt/ctf-agent/shared:ro" \
  ctf-agent-solver:latest

echo ""
echo "============================================"
echo "  运行结束"
echo "  查看结果: cat workspace/scoreboard.md"
echo "============================================"