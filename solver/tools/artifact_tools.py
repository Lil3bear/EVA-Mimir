from __future__ import annotations

from solver.runtime.artifacts import ArtifactBus
from solver.runtime.state_events import StateEventLog
from solver.runtime.contracts import load_contract
from solver.worker_context import ctx as _ctx


ARTIFACT_LIST_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "artifact_list",
        "description": "读取 Observer 已批准的本题结构化证据，不会显示其他 Solver 的待审核内容。",
        "parameters": {"type": "object", "properties": {}},
    },
}

ARTIFACT_PUBLISH_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "artifact_publish",
        "description": (
            "发布一条结构化证据给 Observer 审核。只发布当前题目上已验证的单条事实，"
            "不要发布整段思考、猜测或原始 Memory。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "artifact_type": {"type": "string", "description": "如 foothold, credential, host, service, flag_stage"},
                "value": {"type": "string"},
                "proof_ref": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "metadata": {"type": "object"},
            },
            "required": ["artifact_type", "value"],
        },
    },
}


def _challenge_dir():
    return _ctx.challenge_dir


def artifact_list(args: dict) -> str:
    items = ArtifactBus(_challenge_dir()).list(status="approved", limit=50)
    if not items:
        return "[Artifact] 暂无已批准共享证据"
    return "\n".join(
        f"- {item.get('artifact_id')} {item.get('artifact_type')}: {item.get('value')} "
        f"(confidence={item.get('confidence')}, proof={item.get('proof_ref', '')})"
        for item in items
    )


def artifact_publish(args: dict) -> str:
    artifact_type = str(args.get("artifact_type", "fact")).strip()
    value = str(args.get("value", "")).strip()
    if not value:
        return "[错误] artifact value 不能为空"
    contract = load_contract(_ctx.attempt_dir)
    artifact = ArtifactBus(_challenge_dir()).publish(
        artifact_type=artifact_type,
        value=value,
        producer_attempt=_ctx.attempt_id,
        proof_ref=str(args.get("proof_ref", "")),
        confidence=float(args.get("confidence", 0.5)),
        contract_id=contract.contract_id if contract else "",
        metadata=args.get("metadata") if isinstance(args.get("metadata"), dict) else {},
    )
    try:
        StateEventLog(_challenge_dir()).append(
            "artifact_published",
            {"artifact_id": artifact["artifact_id"], "artifact_type": artifact_type},
            attempt_id=_ctx.attempt_id,
            run_id=getattr(_ctx, "run_id", ""),
        )
    except Exception:
        pass
    return f"[Artifact] 已提交待审核 {artifact['artifact_id']}：{artifact_type}（其他 Solver 尚不可见）"
