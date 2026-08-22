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
_DIFFICULTY_COST = {"easy": 1.0, "medium": 2.0, "hard": 3.5, "difficult": 3.5}


@dataclass(frozen=True)
class ChallengeProfile:
    type_name: str
    primary_skill: str
    candidate_skills: tuple[str, ...] = ()
    protocol_hint: str = "unknown"


def sort_challenges(challenges: list[Challenge]) -> list[Challenge]:
    def type_cost(code: str) -> float:
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

    def score(challenge: Challenge) -> float:
        remaining = max(1, challenge.flag_count - challenge.correct_flag_count)
        expected = challenge.total_score * (remaining / max(1, challenge.flag_count))
        if challenge.correct_flag_count > 0:
            expected += min(30.0, challenge.total_score * 0.2)
        cost = _DIFFICULTY_COST.get(challenge.difficulty.lower(), 2.0)
        return expected / (cost * type_cost(challenge.unique_code))

    return sorted(challenges, key=score, reverse=True)


def infer_challenge_type(
    unique_code: str,
    container_addr: tuple[str, ...] = (),
) -> ChallengeProfile:
    code = unique_code.lower()
    ports = {address.rsplit(":", 1)[-1] for address in container_addr if ":" in address}
    type_name, primary_skill = next(
        (value for prefix, value in _CODE_PREFIX_TO_TYPE.items() if code.startswith(prefix)),
        ("→ 未知类型", "web"),
    )

    if not container_addr:
        return ChallengeProfile("→ 附件分析", primary_skill, (), "attachment")
    if code.startswith("b-"):
        return ChallengeProfile("→ 多阶段渗透（多 flag）", "pentest", ("web",))
    if len(container_addr) > 1 or ports & {"22", "23"}:
        return ChallengeProfile(
            "→ 多服务渗透",
            "pentest",
            tuple(dict.fromkeys([primary_skill, "web", "pwn"])),
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
        )
    if ports & _HTTP_PORTS:
        if primary_skill == "web":
            return ChallengeProfile("→ Web 服务", "web", ("pentest",), "http")
        return ChallengeProfile(
            type_name,
            primary_skill,
            tuple(dict.fromkeys(["web", "pentest"])),
            "http",
        )
    if primary_skill == "web":
        return ChallengeProfile("→ 未知协议服务", "pentest", ("web",))
    return ChallengeProfile("→ 非 HTTP 服务", primary_skill, ("web",))
