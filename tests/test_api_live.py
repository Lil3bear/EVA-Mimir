"""
Tsecbench API 连通性测试
依次验证：list_challenges → start → hint → close
"""
import sys
import os
import io

# 修复 Windows GBK 终端无法输出 emoji/中文符号的问题
if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") not in ("utf8", "utf16"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 项目根目录加入 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from solver.ctfplatform.tsecbench_client import (
    TsecbenchClient,
    TsecbenchError,
    VpnCheckError,
    InvalidState,
    ChallengeNotFound,
    ResourceUnavailable,
    DuplicateSubmit,
)


BASE_URL = "https://tsecbench.zc.tencent.com"
TOKEN = os.environ.get("BENCHMARK_TOKEN", "").strip()


def main():
    print("=" * 60)
    print("  Tsecbench API 连通性测试")
    print("=" * 60)

    if not TOKEN:
        print("  请先设置 BENCHMARK_TOKEN，本测试不再从代码读取密钥。")
        return

    client = TsecbenchClient(
        base_url=os.environ.get("BENCHMARK_BASE_URL", BASE_URL),
        token=TOKEN,
        timeout=30.0,
    )

    # ─── Step 0: VPN 检测 ───
    print("\n[Step 0] VPN 检测...")
    try:
        vpn = client.check_vpn()
        print(f"  ✅ VPN 正常 | IP: {vpn.client_ip} | 时间: {vpn.time}")
    except VpnCheckError as e:
        print(f"  ⚠️ VPN 检测失败（不阻塞后续测试）: {e}")
    except Exception as e:
        print(f"  ⚠️ VPN 检测异常: {e}")

    # ─── Step 1: 列出题目 ───
    print("\n[Step 1] 获取题目列表...")
    try:
        challenges = client.list_challenges()
        print(f"  ✅ 获取成功，共 {len(challenges)} 道题目")

        completed = sum(1 for c in challenges if c.is_completed)
        running = sum(1 for c in challenges if c.container_status == "available")
        print(f"  已完成: {completed} | 运行中: {running} | 未完成: {len(challenges) - completed}")

        # 按难度分组统计
        diff_counts = {}
        for c in challenges:
            d = c.difficulty.lower()
            diff_counts[d] = diff_counts.get(d, 0) + 1
        print(f"  难度分布: {diff_counts}")

        # 显示前 10 题
        print(f"\n  {'编号':<35} {'难度':<10} {'分值':<8} {'flag':<10} {'状态':<12} {'容器'}")
        print(f"  {'-'*35} {'-'*10} {'-'*8} {'-'*10} {'-'*12} {'-'*20}")
        for c in challenges[:10]:
            flag_str = f"{c.correct_flag_count}/{c.flag_count}"
            status = "✅完成" if c.is_completed else "🔲未完成"
            container = c.container_status
            print(f"  {c.unique_code:<35} {c.difficulty:<10} {c.total_score:<8} {flag_str:<10} {status:<12} {container}")
        if len(challenges) > 10:
            print(f"  ... 还有 {len(challenges) - 10} 道题")

        # 计算总分
        total_possible = sum(c.total_score for c in challenges)
        total_earned = sum(c.total_score for c in challenges if c.is_completed)
        print(f"\n  总可得分: {total_possible} | 已得分: {total_earned}")

    except TsecbenchError as e:
        print(f"  ❌ 失败: [{e.code}] {e.message}")
        if e.code == "task_not_found":
            print("     → Token 无效或任务不存在，后续测试无法进行")
            client.close()
            return
        if e.code == "invalid_state":
            print("     → 任务已结束（超时或手动停止）")
            client.close()
            return
        challenges = []
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        import traceback; traceback.print_exc()
        challenges = []

    if not challenges:
        print("\n  没有题目可测试，退出")
        client.close()
        return

    if os.environ.get("TSECBENCH_LIFECYCLE_TEST") != "1":
        print("\n  只读连通性测试通过。")
        print("  如需测试 start/close，设置 TSECBENCH_LIFECYCLE_TEST=1。")
        client.close()
        return

    # 选一道未完成的 easy 题做后续测试
    test_challenge = None
    for c in challenges:
        if not c.is_completed and c.difficulty.lower() == "easy":
            test_challenge = c
            break
    if test_challenge is None:
        # 没有 easy 题，选任意未完成的
        for c in challenges:
            if not c.is_completed:
                test_challenge = c
                break
    if test_challenge is None:
        print("\n  所有题目已完成，跳过 start/hint/close 测试")
        client.close()
        return

    code = test_challenge.unique_code
    print(f"\n  选择测试题目: {code} ({test_challenge.difficulty}, {test_challenge.total_score}分)")

    # ─── Step 2: 启动题目容器 ───
    print(f"\n[Step 2] 启动题目容器: {code}...")
    started = False
    container_addr = []
    try:
        result = client.start_challenge(code)
        container_addr = result.container_addr
        print(f"  ✅ 启动成功")
        print(f"  容器地址: {', '.join(container_addr) if container_addr else '（无）'}")
        started = True
    except InvalidState as e:
        print(f"  ⚠️ 无法启动: {e.message}")
        print("     → 可能是活跃题目数已达上限（最多 3 题），或任务已结束")
    except ResourceUnavailable as e:
        print(f"  ⚠️ 资源不可用: {e.message}")
    except TsecbenchError as e:
        print(f"  ❌ 失败: [{e.code}] {e.message}")
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        import traceback; traceback.print_exc()

    # ─── Step 3: 获取提示（可选，会扣分，这里只在已启动时测试） ───
    if started and os.environ.get("TSECBENCH_HINT_TEST") == "1":
        print(f"\n[Step 3] 获取提示: {code}...")
        print(f"  ⚠️ 注意: 获取提示会导致后续提交扣分，这里仅做接口测试")
        try:
            hint_result = client.get_hint(code)
            if hint_result.hint:
                # 截断显示，避免泄露太多
                hint_preview = hint_result.hint[:100] + ("..." if len(hint_result.hint) > 100 else "")
                print(f"  ✅ 提示内容: {hint_preview}")
            else:
                print(f"  ✅ 接口正常，但该题无提示（hint=null）")
        except InvalidState as e:
            print(f"  ⚠️ {e.message}（可能该题已通关）")
        except TsecbenchError as e:
            print(f"  ❌ 失败: [{e.code}] {e.message}")
        except Exception as e:
            print(f"  ❌ 异常: {e}")

    # ─── Step 4: 关闭题目容器 ───
    if started:
        print(f"\n[Step 4] 关闭题目容器: {code}...")
        try:
            close_result = client.close_challenge(code)
            print(f"  ✅ 关闭{'成功' if close_result.closed else '失败'}")
        except TsecbenchError as e:
            print(f"  ❌ 失败: [{e.code}] {e.message}")
        except Exception as e:
            print(f"  ❌ 异常: {e}")

    # ─── Step 5: 再次列出题目，确认状态恢复 ───
    if started:
        print(f"\n[Step 5] 再次获取题目列表，确认容器已关闭...")
        try:
            challenges2 = client.list_challenges()
            target = next((c for c in challenges2 if c.unique_code == code), None)
            if target:
                print(f"  容器状态: {target.container_status}")
                print(f"  容器地址: {target.container_addr or '（空）'}")
                if target.container_status in ("stopped", "stop_pending"):
                    print(f"  ✅ 容器已正常关闭/关闭中")
                else:
                    print(f"  ⚠️ 容器状态: {target.container_status}（可能需要等待）")
        except Exception as e:
            print(f"  ❌ 异常: {e}")

    client.close()

    print("\n" + "=" * 60)
    print("  连通性测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
