#!/bin/bash
# 网络看门狗：检测「虎跃加速器」(utun4) 假死并自动断开，恢复 en0 直连路由。
# 仅在 utun4 为默认路由且公网 API 确实不可达时才断开，避免误伤正常连接。
set -u

LOG="/Users/mz/Code/EVA-Mimir/watchdog.log"
API="https://tsecbench.zc.tencent.com/openapi/v1/challenges"
TOKEN="138ccc5d-94e2-4594-b0dd-3805ca6599da"

while true; do
    IFACE="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')"
    if [ "$IFACE" = "utun4" ]; then
        if ! curl -sS -m 8 -o /dev/null "$API" -H "BENCHMARK_TOKEN: $TOKEN" 2>/dev/null; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] utun4 假死(API超时)，断开虎跃加速器" >> "$LOG"
            scutil --nc stop "虎跃加速器" 2>/dev/null
            sleep 5
        fi
    fi
    sleep 30
done
