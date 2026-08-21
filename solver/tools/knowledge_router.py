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

_PRODUCT_ROUTES = {
    "Gradio": ("web", "product-playbooks.md"),
    "Dify": ("web", "product-playbooks.md"),
    "HugeGraph": ("web", "product-playbooks.md"),
    "ComfyUI-Manager": ("web", "product-playbooks.md"),
    "Apache OFBiz": ("web", "java-exploitation.md"),
}


def _load_cheatsheet() -> dict:
    global _CACHE
    if _CACHE is None:
        root = os.environ.get("CTF_SKILLS_DIR", "/skills")
        path = Path(root) / "cve-cheatsheet.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            _CACHE = data if isinstance(data, dict) else {}
        except Exception:
            _CACHE = {}
    return _CACHE


def _fingerprint_products(output: str, context: str) -> set[str]:
    """Recognize products from response markers plus the requested endpoint."""
    out = (output or "").lower()
    ctx = (context or "").lower()
    products: set[str] = set()

    if "gradio" in out or (":7860" in ctx and any(x in out for x in ("gr-", "/queue/", "config"))):
        products.add("Gradio")
    if (":3000" in ctx or "dify" in out) and any(
        x in out for x in ("dify", "data-public-api-prefix", "self_hosted")
    ):
        products.add("Dify")
    if "hugegraph" in out or any(x in out for x in ("gremlin-groovy", "hugegraph-server")):
        products.add("HugeGraph")
    if "comfyui" in out or (":8188" in ctx and "/api/manager" in out):
        products.add("ComfyUI-Manager")
    if "ofbiz" in out or (":8443" in ctx and "/webtools/" in out):
        products.add("Apache OFBiz")
    return products


def lookup(output: str, context: str = "") -> str:
    """根据响应与请求上下文匹配中间件，返回确定性条目。"""
    sheet = _load_cheatsheet()
    middleware = sheet.get("middleware", {}) if isinstance(sheet, dict) else {}
    if not middleware:
        return ""

    out_lower = (output or "").lower()
    detected = _fingerprint_products(output, context)
    hits: list[tuple[str, dict]] = []
    for product, entry in middleware.items():
        if not isinstance(entry, dict):
            continue
        if product.lower() in out_lower or product in detected:
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
