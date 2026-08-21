#!/usr/bin/env python3
"""从 run 日志中收割攻击链，沉淀进跨 run 种子库。

用法：
    python3 harvest_attack_chains.py run_log_xxx.log [更多日志...]
    python3 harvest_attack_chains.py --workspace workspace/   # 从本地工作区收割

工作原理：
    每次成功解题后，scheduler 会向 stdout 发 `attack_chain` 事件
    （flag 与 IP 已在发送前剥离）。本脚本扫描日志中的这些事件，
    合并进 skills/experiences/references/attack-chains.json。
    该文件随 Docker 镜像打包，下次比赛时同题号题目会被精确注入
    「本题历史解法」，把"曾经解出过"变成"稳定重放"。

    --workspace 模式直接扫描本地工作区目录（workspace/<题号>/）
    中的 ideas/memory/执行日志，用于从历史 run 残留中手动沉淀。

只沉淀方法，不沉淀答案（flag），合规且对实例轮换鲁棒。
"""

import json
import sys
from pathlib import Path

SEED_PATH = Path(__file__).parent / "skills" / "experiences" / "references" / "attack-chains.json"


def load_seed() -> dict:
    if SEED_PATH.exists():
        try:
            data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"version": 1, "by_code": {}, "chains": {}}


def harvest(log_paths: list[str]) -> dict:
    """从日志中提取 attack_chain 事件：{code: entry}。"""
    found: dict[str, dict] = {}
    for log_path in log_paths:
        path = Path(log_path)
        if not path.is_file():
            print(f"[跳过] 文件不存在：{log_path}", file=sys.stderr)
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line.startswith("{") or "attack_chain" not in line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("type") != "attack_chain":
                continue
            data = msg.get("data") or {}
            code = str(data.get("code", "")).strip()
            summary = str(data.get("summary", "")).strip()
            if not code or not summary:
                continue
            entry = {
                "code": code,
                "prefix": data.get("prefix") or (code.split("-")[0] + "-" if "-" in code else code[:2]),
                "summary": summary,
                "time": float(data.get("time") or 0),
            }
            # 同一题保留最新的记录
            if code not in found or entry["time"] >= found[code]["time"]:
                found[code] = entry
    return found


def _writeups_from_solver_history(child: Path) -> list[str]:
    """从旧版 .solver-history.jsonl（无执行日志的历史 run）提取成功提交的 writeup。"""
    hist = child / ".solver-history.jsonl"
    if not hist.exists():
        return []
    args_by_call: dict[str, dict] = {}
    correct_calls: set[str] = set()
    for line in hist.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                if fn.get("name") == "challenge_submit_flag":
                    try:
                        args_by_call[str(tc.get("id"))] = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        pass
        elif msg.get("role") == "tool":
            if "提交正确" in str(msg.get("content", "")):
                correct_calls.add(str(msg.get("tool_call_id")))
    writeups = []
    for call_id in correct_calls:
        writeup = str(args_by_call.get(call_id, {}).get("writeup", "")).strip()
        if writeup and writeup != "auto-submit from tool output":
            writeups.append(writeup[:200])
    return list(dict.fromkeys(writeups))


def harvest_workspace(ws_dir: str) -> dict:
    """从本地工作区收割：只收实际提交成功过 flag 的题目（有正确提交记录）。"""
    from solver.ctfplatform.scheduler import (
        _extract_chain_from_workspace,
        _extract_successful_writeups,
        _sanitize_chain_text,
    )

    found: dict[str, dict] = {}
    base = Path(ws_dir)
    if not base.is_dir():
        print(f"[跳过] 目录不存在：{ws_dir}", file=sys.stderr)
        return found
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        code = child.name
        # 成功证据：执行日志（新版）或 solver-history（旧版）中的正确提交
        writeups = _extract_successful_writeups(child) or _writeups_from_solver_history(child)
        if not writeups:
            continue  # 没有成功提交记录的不收（无法确认真解出了）
        chain = _extract_chain_from_workspace(child)
        if not chain:
            chain = "writeup: " + " | ".join(writeups[:2])
        found[code] = {
            "code": code,
            "prefix": code.split("-")[0] + "-" if "-" in code else code[:2],
            "summary": _sanitize_chain_text(chain),
            "time": child.stat().st_mtime,
        }
    return found


def merge(seed: dict, found: dict[str, dict]) -> tuple[int, int]:
    by_code = seed.setdefault("by_code", {})
    chains = seed.setdefault("chains", {})
    added = updated = 0
    for code, entry in sorted(found.items()):
        old = by_code.get(code)
        if old and old.get("summary") == entry["summary"]:
            continue
        if old:
            updated += 1
        else:
            added += 1
        by_code[code] = entry
        # 同步维护 prefix 索引（每类最多 3 条，供同类题 fallback 注入）
        prefix_chains = chains.setdefault(entry["prefix"], [])
        prefix_chains[:] = [c for c in prefix_chains if c.get("code") != code]
        prefix_chains.append(entry)
        prefix_chains[:] = prefix_chains[-3:]
    return added, updated


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    seed = load_seed()
    if args[0] == "--workspace":
        if len(args) < 2:
            print("--workspace 需要指定工作区目录", file=sys.stderr)
            return 1
        found = harvest_workspace(args[1])
    else:
        found = harvest(args)
    if not found:
        print("未在日志中找到 attack_chain 事件。")
        return 0
    added, updated = merge(seed, found)
    SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEED_PATH.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已沉淀 {len(found)} 条攻击链（新增 {added}，更新 {updated}）→ {SEED_PATH}")
    for code in sorted(found):
        print(f"  {code}: {found[code]['summary'][:80]}")
    print("\n下次打包镜像（docker build）后，这些解法将在同题号题目中自动注入。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
