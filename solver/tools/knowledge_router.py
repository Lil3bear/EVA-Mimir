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
    "HugeGraph": ("web", "product-playbooks.md"),
    "ComfyUI-Manager": ("web", "product-playbooks.md"),
    "Apache OFBiz": ("web", "java-exploitation.md"),
    "1Panel": ("web", "known-product-exploit.md"),
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


def lookup(output: str, context: str = "") -> str:
    """根据响应与请求上下文匹配中间件，返回确定性条目。"""
    sheet = _load_cheatsheet()
    middleware = sheet.get("middleware", {}) if isinstance(sheet, dict) else {}
    if not middleware:
        return ""

    out_lower = (output or "").lower()
    combined_lower = f"{out_lower} {(context or '').lower()}"
    detected = _fingerprint_products(output, context)
    hits: list[tuple[str, dict]] = []
    for product, entry in middleware.items():
        if not isinstance(entry, dict):
            continue
        match = entry.get("match") or {}
        body_any = [str(v).lower() for v in match.get("body_any", [])]
        path_any = [str(v).lower() for v in match.get("path_any", [])]
        # Ports are only weak hints.  Never route a CVE/playbook from
        # ``:8443``/``:10086`` alone; a response or endpoint fingerprint must
        # corroborate it, otherwise arbitrary services on common ports are
        # misclassified as OFBiz/1Panel.
        matched = (
            product in detected
            or product.lower() in out_lower
            or any(value in out_lower for value in body_any)
            or any(value in combined_lower for value in path_any)
        )
        if matched:
            hits.append((product, entry))

    if not hits:
        return ""

    lines = ["📌 [本地确定性 CVE 条目]（无需联网搜索，先用 quick_check 验证）"]
    for product, e in hits[:3]:
        lines.append(f"### {product}")
        cves = e.get("cves") or []
        if cves:
            lines.append(f"- CVE: {', '.join(str(c) for c in cves)}")
        quick = e.get("quick_check")
        if quick:
            lines.append(f"- 验证命令: {quick}")
        verify = e.get("verify") or []
        if verify:
            lines.append(f"- 判定: {', '.join(str(v) for v in verify)}")
        query = e.get("search_query")
        if query:
            lines.append(f"- 补充搜索: security_search(\"{query}\")")
        route = _PRODUCT_ROUTES.get(product)
        if route:
            lines.append(
                f'- 下一步必须加载: skill_load(name="{route[0]}", resource="{route[1]}")'
            )
    return "\n".join(lines) + "\n"
