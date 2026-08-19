"""
端到端测试脚本 — 在 Docker 容器内直接运行 SolverAgent。
flag 提交改为直接打印（不走 Bridge 协议）。

用法：
docker run --rm -it \
  -e LLM_BASE_URL="https://api.deepseek.com" \
  -e LLM_API_KEY="sk-xxx" \
  -e LLM_MODEL="deepseek-chat" \
  -v D:/AgentProjectPractice/EVA-Mimir/tests/e2e_test.py:/tmp/e2e_test.py \
  eva-mimir:latest \
  python3 /tmp/e2e_test.py
"""

import os
import sys
import json

# 设置环境变量
os.environ.setdefault("CTF_WORKSPACE", "/root/workspace")
os.environ.setdefault("CTF_CHALLENGE_ID", "e2e-test")
os.environ.setdefault("CTF_SKILLS_DIR", "/opt/ctf-agent/skills")

# ---- 题目配置（按需修改）----
TARGET_URL = os.environ.get("CTF_TARGET_URL", "http://9084199addc5db064c756a39.http-ctf2.dasctf.com:80")
CHALLENGE_NAME = "[ACTF2020 新生赛] Include"
MAX_ROUNDS = 30

TASK = f"""## CTF 题目

**题目名称**：{CHALLENGE_NAME}
**类型**：Web — 文件包含（LFI）
**难度**：简单（1 分）
**目标地址**：{TARGET_URL}
**题目描述**：感谢 Y1ng 师傅供题。
**提示**：首页有 `<a href="?file=flag.php">tips</a>`，这是文件包含入口。
**Flag 格式**：flag{{...}}

请找到 flag 并用 challenge_submit_flag 工具提交。
"""

# ---- Monkey-patch bridge_tools：不走 stdin/stdout Bridge ----
from solver.tools import bridge_tools

_found_flags = []

def _mock_submit_flag(args):
    flag = args.get("flag", "").strip()
    if not flag:
        return "[错误] flag 不能为空"
    _found_flags.append(flag)
    print(f"\n{'='*60}")
    print(f"  🏁 FLAG 提交: {flag}")
    print(f"{'='*60}\n")
    # 模拟提交成功（让 Agent 停下来）
    return f"[提交结果] flag「{flag}」已提交。请假设正确并停止。"

def _mock_get_state(args):
    return json.dumps({
        "challenge_id": "e2e-test",
        "name": CHALLENGE_NAME,
        "url": TARGET_URL,
        "status": "running",
    }, ensure_ascii=False)

def _mock_get_hint(args):
    return "[提示] 这是一道文件上传题，注意绕过上传限制。"

def _mock_start(args):
    return f"[已启动] {CHALLENGE_NAME} @ {TARGET_URL}"

def _mock_close(args):
    return "[已关闭]"

# 替换 bridge_tools 的执行函数
bridge_tools.submit_flag = _mock_submit_flag
bridge_tools.get_state = _mock_get_state
bridge_tools.get_hint = _mock_get_hint
bridge_tools.start_challenge = _mock_start
bridge_tools.close_challenge = _mock_close

# ---- 替换 _emit 为 stderr 输出（stdout 被 Agent 占用）----
import solver.agent as agent_mod
import solver.main as main_mod

def _stderr_emit(event_type, data=None):
    line = json.dumps({"type": event_type, "data": data}, ensure_ascii=False, default=str)
    print(f"[{event_type}] {json.dumps(data, ensure_ascii=False, default=str)[:200] if data else ''}", file=sys.stderr)

agent_mod._emit = _stderr_emit
main_mod._emit = _stderr_emit

# ---- 运行 ----
def main():
    print(f"{'='*60}", file=sys.stderr)
    print(f"  EVA-Mimir 端到端测试", file=sys.stderr)
    print(f"  题目: {CHALLENGE_NAME}", file=sys.stderr)
    print(f"  目标: {TARGET_URL}", file=sys.stderr)
    print(f"  模型: {os.environ.get('LLM_MODEL', 'deepseek-chat')}", file=sys.stderr)
    print(f"  最大轮次: {MAX_ROUNDS}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    settings = {
        "llm": {
            "base_url": os.environ.get("LLM_BASE_URL", ""),
            "api_key": os.environ.get("LLM_API_KEY", ""),
            "default_model": os.environ.get("LLM_MODEL", "deepseek-chat"),
            "observer_model": os.environ.get("LLM_MODEL", "deepseek-chat"),
        },
        "solver": {
            "max_rounds": MAX_ROUNDS,
            "observer_every_rounds": 6,
        },
    }

    from solver.agent import SolverAgent
    agent = SolverAgent(
        task=TASK,
        settings=settings,
        skills_dir="/opt/ctf-agent/skills",
    )

    try:
        agent.run()
    except KeyboardInterrupt:
        print("\n[中断] 用户取消", file=sys.stderr)
    except Exception as e:
        import traceback
        print(f"\n[异常] {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)

    # 输出结果
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  测试结束", file=sys.stderr)
    print(f"  总轮次: {agent.round}", file=sys.stderr)
    if _found_flags:
        print(f"  提交的 flags:", file=sys.stderr)
        for f in _found_flags:
            print(f"    🏁 {f}", file=sys.stderr)
    else:
        print(f"  ❌ 未找到 flag", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)


if __name__ == "__main__":
    main()
