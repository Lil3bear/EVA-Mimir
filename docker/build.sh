#!/bin/bash
# Docker 镜像构建 + 体积验证脚本
# 在项目根目录执行：bash docker/build.sh

set -e

IMAGE_NAME="eva-mimir-solver"
MAX_SIZE_MB=1024  # 1GB 限制

echo "============================================"
echo "  EVA-Mimir Docker 镜像构建"
echo "============================================"

# 确保 fastcoll-src 目录存在（即使为空也不影响构建）
mkdir -p docker/fastcoll-src

# 构建
echo ""
echo "[1/4] 开始构建..."
docker build -t ${IMAGE_NAME}:latest -f docker/Dockerfile . 2>&1 | tail -20

# 检查体积
echo ""
echo "[2/4] 检查镜像体积..."
SIZE_BYTES=$(docker image inspect ${IMAGE_NAME}:latest --format='{{.Size}}')
SIZE_MB=$((SIZE_BYTES / 1024 / 1024))
echo "  镜像大小: ${SIZE_MB} MB"

if [ ${SIZE_MB} -gt ${MAX_SIZE_MB} ]; then
    echo "  ❌ 超过 ${MAX_SIZE_MB}MB 限制！需要瘦身。"
    echo ""
    echo "  各层体积分析："
    docker history ${IMAGE_NAME}:latest --format "table {{.Size}}\t{{.CreatedBy}}" | head -20
    exit 1
else
    echo "  ✅ 体积合格 (${SIZE_MB}MB < ${MAX_SIZE_MB}MB)"
fi

# 基本功能验证
echo ""
echo "[3/4] 基本功能验证..."

# 检查 Python 能导入关键模块
docker run --rm ${IMAGE_NAME}:latest python3 -c "
import openai; print('✓ openai')
import pwn; print('✓ pwntools')
import Crypto; print('✓ pycryptodome')
import requests; print('✓ requests')
try:
    import z3; print('✓ z3-solver')
except: print('⚠ z3-solver (optional)')
try:
    import gmpy2; print('✓ gmpy2')
except: print('⚠ gmpy2 (optional)')
"

# 检查关键工具存在
docker run --rm ${IMAGE_NAME}:latest bash -c "
which curl && echo '✓ curl'
which sqlmap && echo '✓ sqlmap'
which gcc && echo '✓ gcc'
which fastcoll && echo '✓ fastcoll'
which php && echo '✓ php-cli'
which jq && echo '✓ jq'
python3 -c 'from solver.main import main; print(\"✓ solver.main importable\")'
"

# 压缩包大小
echo ""
echo "[4/4] 导出 + 压缩..."
docker save ${IMAGE_NAME}:latest | gzip > agent.tar.gz
GZ_SIZE_MB=$(du -m agent.tar.gz | cut -f1)
echo "  agent.tar.gz: ${GZ_SIZE_MB} MB"

if [ ${GZ_SIZE_MB} -gt ${MAX_SIZE_MB} ]; then
    echo "  ❌ 压缩后仍超过 ${MAX_SIZE_MB}MB"
else
    echo "  ✅ 压缩后合格 (${GZ_SIZE_MB}MB)"
fi

echo ""
echo "============================================"
echo "  构建完成！"
echo "  镜像: ${IMAGE_NAME}:latest (${SIZE_MB}MB)"
echo "  压缩: agent.tar.gz (${GZ_SIZE_MB}MB)"
echo "============================================"
