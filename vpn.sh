#!/bin/bash
# EVA-Mimir Tsecbench VPN 接入脚本
#
# 在 colima/docker 环境下，OpenVPN 以 --network host 方式运行在 Linux VM
# 网络命名空间中，Solver 容器同样以 --network host 运行，从而共享 VPN 路由。
# OpenVPN 自动加路由时会因 gateway 解析问题失败（Network is unreachable），
# 因此这里在连接成功后手动补齐路由。
#
# 用法：
#   ./vpn.sh                          # 使用默认 ovpn 文件
#   ./vpn.sh /path/to/config.ovpn     # 指定 ovpn 文件

set -euo pipefail

OVPN_FILE="${1:-/Users/mz/Downloads/task_IJvW1n1x7FsX_vpn_config.ovpn}"
CONTAINER_NAME="tsec-vpn"
IMAGE_NAME="eva-openvpn-client"
VPN_CHECK_URL="http://10.0.100.58"

if [ ! -f "$OVPN_FILE" ]; then
    echo "❌ VPN 配置文件不存在: $OVPN_FILE" >&2
    exit 1
fi

echo "============================================"
echo "  EVA-Mimir VPN 接入"
echo "  配置文件: $OVPN_FILE"
echo "============================================"

echo ""
echo "[1/4] 清理旧 VPN 容器..."
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

echo "[2/4] 启动 OpenVPN 容器（host 网络模式）..."
docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    --network host \
    --cap-add NET_ADMIN \
    --device /dev/net/tun \
    -v "$OVPN_FILE:/vpn/client.ovpn:ro" \
    "$IMAGE_NAME:latest" \
    --config /vpn/client.ovpn --verb 3

echo "[3/4] 等待 VPN 建立..."
CONNECTED=0
for _ in $(seq 1 40); do
    if docker logs "$CONTAINER_NAME" 2>&1 | grep -q "Initialization Sequence Completed"; then
        CONNECTED=1
        break
    fi
    sleep 2
done

if [ "$CONNECTED" -ne 1 ]; then
    echo "  ❌ VPN 连接失败，最近日志："
    docker logs "$CONTAINER_NAME" 2>&1 | tail -25 || true
    exit 1
fi
echo "  ✅ VPN 已连接"

echo "[4/4] 修复路由并验证..."
# 找到 VPN 的 tun 接口（服务端推送 10.254.0.0/24 网段）
TUN_IF="$(docker exec "$CONTAINER_NAME" sh -c "ip -o addr show | awk '/10\\.254\\.0\\./{print \$2; exit}'" 2>/dev/null | tr -d '\r')"
if [ -z "$TUN_IF" ]; then
    TUN_IF="tun0"
fi
echo "  tun 接口: $TUN_IF"

# 手动补齐服务端推送的路由（点对点 tun 接口无需 gateway）
docker exec "$CONTAINER_NAME" sh -c "
ip route replace 10.254.0.0/24 dev '$TUN_IF'
ip route replace 10.0.128.0/18 dev '$TUN_IF'
ip route replace 10.0.100.58/32 dev '$TUN_IF'
ip route replace 10.0.100.135/32 dev '$TUN_IF'
"

# 验证平台 VPN 检测端点
VPN_RESP="$(docker exec "$CONTAINER_NAME" sh -c "curl -s --connect-timeout 5 '$VPN_CHECK_URL'" 2>/dev/null || true)"
if echo "$VPN_RESP" | grep -q '"status":"ok"'; then
    echo "  ✅ VPN 检测通过: $VPN_RESP"
else
    echo "  ❌ VPN 检测失败，响应: $VPN_RESP"
    exit 1
fi

echo ""
echo "============================================"
echo "  VPN 已就绪，可运行: ./run.sh"
echo "============================================"
