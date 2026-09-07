"""确定性知识路由器。

bash 输出里识别到中间件指纹后，直接从 cve-cheatsheet.json 注入对应条目，
不再要求模型调用 security_search 回忆（DeepSeek 非联网结果可能不准）。

只注入、不自动执行攻击命令。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_CACHE: dict | None = None
_CACHE_ROOT = ""

_PRODUCT_ROUTES = {
    "Gradio": ("web", "product-playbooks.md"),
    "Dify": ("web", "product-playbooks.md"),
    "HugeGraph": ("web", "graph-db.md"),
    "ComfyUI-Manager": ("web", "product-playbooks.md"),
    "Apache OFBiz": ("web", "java-exploitation.md"),
    "1Panel": ("web", "product-playbooks.md"),
    "GeoServer": ("web", "known-product-exploit.md"),
}


def _load_cheatsheet() -> dict:
    global _CACHE, _CACHE_ROOT
    root = os.environ.get("CTF_SKILLS_DIR", "/skills")
    if _CACHE is None or _CACHE_ROOT != root:
        path = Path(root) / "cve-cheatsheet.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            _CACHE = data if isinstance(data, dict) else {}
        except Exception:
            _CACHE = {}
        _CACHE_ROOT = root
    return _CACHE


def _fingerprint_products(output: str, context: str) -> set[str]:
    """Recognize products from response markers plus the requested endpoint."""
    out = (output or "").lower()
    ctx = (context or "").lower()
    combined = f"{out} {ctx}"
    products: set[str] = set()

    if "gradio" in out or (":7860" in combined and any(x in combined for x in ("gr-", "/queue/", "/file="))):
        products.add("Gradio")
    dify_markers = ("dify", "data-public-api-prefix", "self_hosted")
    dify_path_markers = ("/console/", "/apps/", "/api/console")
    if "dify" in combined or any(x in combined for x in dify_markers[1:]):
        products.add("Dify")
    elif ":3000" in combined and "next.js" in combined and any(
        x in combined for x in dify_path_markers
    ):
        # Port+Next.js alone is a generic app; require a Dify-shaped route.
        products.add("Dify")
    if "hugegraph" in combined or any(x in combined for x in ("gremlin-groovy", "hugegraph-server")):
        products.add("HugeGraph")
    if "comfyui" in combined or (":8188" in combined and "/api/manager" in combined):
        products.add("ComfyUI-Manager")
    if "ofbiz" in combined or (":8443" in combined and "/webtools/" in combined):
        products.add("Apache OFBiz")
    return products


def _looks_like_web(output_lower: str) -> bool:
    """Whether output resembles a real web/api *response* (not a refused/error).

    Strip curl -v / -sv client-side lines first: otherwise a dead port that
    RST after ``GET / HTTP/1.1`` still matches ``http/1.`` and fires Gradio
    weak hints forever (run c-08).
    """
    if not output_lower:
        return False
    server_lines: list[str] = []
    for line in output_lower.splitlines():
        stripped = line.lstrip()
        # curl -v prefixes: * progress, > request, < response headers
        if stripped.startswith(("*", ">")):
            continue
        if stripped.startswith("<"):
            server_lines.append(stripped[1:].lstrip())
            continue
        server_lines.append(line)
    body = "\n".join(server_lines).strip()
    if not body:
        return False
    markers = (
        "<html", "<!doctype", "<body", "<head", "<div", "<script", "<title",
        "http/1.", "http/2", "content-type", "{", "www",
    )
    return any(m in body for m in markers)


def lookup(output: str, context: str = "") -> str:
    """根据响应与请求上下文匹配中间件，返回确定性条目。

    Strong matches (product word / body / path fingerprint) return a CVE
    entry.  A port-only match is treated as a weak hint: it only tells the
    Solver which product to verify next, without handing it a CVE, so common
    ports (8443/3000/8080) no longer misclassify arbitrary services.
    """
    sheet = _load_cheatsheet()
    middleware = sheet.get("middleware", {}) if isinstance(sheet, dict) else {}
    if not middleware:
        return ""

    out_lower = (output or "").lower()
    combined_lower = f"{out_lower} {(context or '').lower()}"
    detected = _fingerprint_products(output, context)
    hits: list[tuple[str, dict]] = []
    weak_hits: list[tuple[str, dict]] = []
    for product, entry in middleware.items():
        if not isinstance(entry, dict):
            continue
        match = entry.get("match") or {}
        body_any = [str(v).lower() for v in match.get("body_any", [])]
        path_any = [str(v).lower() for v in match.get("path_any", [])]
        ports = [str(v) for v in match.get("ports", [])]
        matched = (
            product in detected
            or product.lower() in out_lower
            or any(value in out_lower for value in body_any)
            or any(value in combined_lower for value in path_any)
        )
        if matched:
            hits.append((product, entry))
        elif (
            ports
            and any(f":{port}" in combined_lower for port in ports)
            and _looks_like_web(out_lower)
        ):
            weak_hits.append((product, entry))

    if not hits and not weak_hits:
        return ""

    lines: list[str] = []
    if hits:
        # 顺序即优先级：本地 skill 里已有可直接复用的 payload，评测无外网，
        # 所以 skill_load 是首选动作；quick_check 只是指纹参考（实例可能不同，
        # 404/空响应不代表漏洞不存在）；不再注入 security_search —— 离线它只会
        # 返回"无可靠本地知识"并把模型带偏（见 run c-03：反复搜 + 下载 scanner 超时）。
        lines.append("📌 [本地利用条目]（本地 skill 已含可用 payload，评测无外网，别搜/别下载外部脚本）")
        for product, e in hits[:3]:
            lines.append(f"### {product}")
            cves = e.get("cves") or []
            if cves:
                lines.append(f"- CVE: {', '.join(str(c) for c in cves)}")
            route = _PRODUCT_ROUTES.get(product)
            if route:
                lines.append(
                    f'- ⭐首选: skill_load(name="{route[0]}", resource="{route[1]}") '
                    f"→ 回看并逐字复制其中 payload，别凭记忆重写"
                )
            quick = e.get("quick_check")
            if quick:
                lines.append(f"- 指纹参考（实例可能不同，非命中判据）: {quick}")
            verify = e.get("verify") or []
            if verify:
                lines.append(f"- 命中判据: {', '.join(str(v) for v in verify)}")
    if weak_hits:
        lines.append("🔎 [端口弱信号] 仅凭端口不足以判定，请先验证产品指纹再查 CVE：")
        for product, e in weak_hits[:3]:
            quick = (e.get("quick_check") or "curl 目标首页/常见路径")
            lines.append(f"- {product}：{quick}")
            route = _PRODUCT_ROUTES.get(product)
            if route:
                lines.append(
                    f'  指纹命中后加载: skill_load(name="{route[0]}", resource="{route[1]}")'
                )
    return "\n".join(lines) + "\n"
