"""Challenge classification and scheduling policy."""

from dataclasses import dataclass

from solver.ctfplatform.tsecbench_client import Challenge


_CODE_PREFIX_TO_TYPE = {
    "a-": ("→ Web 漏洞", "web"),
    "b-": ("→ 多阶段渗透（多 flag）", "pentest"),
    "c-": ("→ 综合/杂项", "web"),
    "d-": ("→ 云安全", "cloud"),
    "e1": ("→ 渗透测试", "pentest"),
    "e2": ("→ 沙箱逃逸/漏洞利用", "pwn"),
    "e3": ("→ 检测对抗", "evasion"),
    "f1": ("→ 二进制服务", "pwn"),
    "f2": ("→ 固件/逆向", "reverse"),
}
_HTTP_PORTS = {"80", "443", "8000", "8080", "3000", "5000", "7860", "8443", "8888"}
# 端口 → 产品候选（弱信号：供 Solver 优先验证，不是断言）。
# 平台不返回题目标题，只有端口可作第一线索；命中后必须先 curl 指纹验证。
_PORT_PRODUCT_HINTS = {
    "8188": "ComfyUI / ComfyUI-Manager（先 curl 首页或 /api/manager 验证，命中加载 web/product-playbooks.md）",
    "3000": "Dify / Next.js（先 curl 首页看 data-public-api-prefix/Next.js 特征，命中加载 web/product-playbooks.md）",
    "7860": "Gradio（先 curl 首页看 gr-/gradio/queue 特征，命中加载 web/product-playbooks.md）",
    "8443": "Apache OFBiz（先 curl /webtools/ 或首页验证，命中加载 web/java-exploitation.md）",
    "8080": "HugeGraph / 通用 Web（先 curl /gremlin 或 /graphs 验证，命中加载 web/graph-db.md）",
    "10086": "1Panel（先 curl /api/v1/auth/login 验证，命中加载 web/product-playbooks.md）",
}
_DIFFICULTY_COST = {"easy": 1.0, "medium": 2.0, "hard": 3.5, "difficult": 3.5}


@dataclass(frozen=True)
class ChallengeProfile:
    type_name: str
    primary_skill: str
    candidate_skills: tuple[str, ...] = ()
    protocol_hint: str = "unknown"
    product_hint: str = ""


def _type_cost(code: str) -> float:
    code = code.lower()
    if code.startswith(("a-", "c-", "g-")):
        return 1.0
    if code.startswith("d-"):
        return 1.4
    if code.startswith("b-"):
        return 1.8
    if code.startswith(("e2", "e3")):
        return 2.2
    if code.startswith("e1"):
        return 2.5
    if code.startswith(("f1", "f2")):
        return 2.8
    return 1.5


# Whole families that reliably burn a worker slot for a long time.  They are
# tiered *behind* every web/misc challenge so the fast, high-yield points are
# banked first and the global deadline only ever truncates this deferred tail
# (proven by run-12717: b-* held all 3 slots for 41 min while a 500-pt a-10
# waited in queue).
_DEFERRED_PREFIXES = ("b-", "e1", "e2", "e3", "f1", "f2")
_DIFFICULTY_RANK = {"easy": 0, "medium": 1, "hard": 2, "difficult": 2}


def _tier(challenge: Challenge) -> int:
    """Lower tier runs first.  Difficulty gates within a family; the whole
    pentest/pwn/reverse family is pushed behind web/misc of the same difficulty.
    """
    rank = _DIFFICULTY_RANK.get(challenge.difficulty.lower(), 1)
    if challenge.unique_code.lower().startswith(_DEFERRED_PREFIXES):
        rank += 3
    return rank


def _roi(challenge: Challenge) -> float:
    remaining = max(1, challenge.flag_count - challenge.correct_flag_count)
    expected = challenge.total_score * (remaining / max(1, challenge.flag_count))
    if challenge.correct_flag_count > 0:
        expected += min(30.0, challenge.total_score * 0.2)
    cost = _DIFFICULTY_COST.get(challenge.difficulty.lower(), 2.0)
    return expected / (cost * _type_cost(challenge.unique_code))


def sort_challenges(challenges: list[Challenge]) -> list[Challenge]:
    """Front-load fast, high-yield points; defer slot-hogging families to the tail.

    Ordering key is ``(tier, -roi, code)``: tier front-loads easy/web wins,
    ROI ranks value within a tier, and the code is a deterministic final
    tiebreak.
    """
    return sorted(
        challenges,
        key=lambda c: (_tier(c), -_roi(c), c.unique_code.lower()),
    )


def infer_challenge_type(
    unique_code: str,
    container_addr: tuple[str, ...] = (),
) -> ChallengeProfile:
    code = unique_code.lower()
    ports = {address.rsplit(":", 1)[-1] for address in container_addr if ":" in address}
    product_hint = next(
        (hint for port, hint in _PORT_PRODUCT_HINTS.items() if port in ports),
        "",
    )
    type_name, primary_skill = next(
        (value for prefix, value in _CODE_PREFIX_TO_TYPE.items() if code.startswith(prefix)),
        ("→ 未知类型", "web"),
    )

    if not container_addr:
        return ChallengeProfile("→ 附件分析", primary_skill, (), "attachment", product_hint)
    if code.startswith("b-"):
        return ChallengeProfile("→ 多阶段渗透（多 flag）", "pentest", ("web",), product_hint=product_hint)
    if len(container_addr) > 1 or ports & {"22", "23"}:
        return ChallengeProfile(
            "→ 多服务渗透",
            "pentest",
            tuple(dict.fromkeys([primary_skill, "web", "pwn"])),
            product_hint=product_hint,
        )
    # c-* is intentionally protocol-agnostic.  A port such as 3000, 8080
    # or 1337 is only a weak hint and must not select Web before the first
    # response fingerprint; keep Web/Pwn/Pentest available to the Solver.
    if code.startswith("c-"):
        return ChallengeProfile(
            "→ 综合服务（先探测协议）",
            "pentest",
            ("web", "pwn"),
            "probe",
            product_hint,
        )
    if ports & _HTTP_PORTS:
        if primary_skill == "web":
            return ChallengeProfile("→ Web 服务", "web", ("pentest",), "http", product_hint)
        return ChallengeProfile(
            type_name,
            primary_skill,
            tuple(dict.fromkeys(["web", "pentest"])),
            "http",
            product_hint,
        )
    if primary_skill == "web":
        return ChallengeProfile("→ 未知协议服务", "pentest", ("web",), product_hint=product_hint)
    return ChallengeProfile("→ 非 HTTP 服务", primary_skill, ("web",), product_hint=product_hint)
