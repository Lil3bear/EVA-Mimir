#!/usr/bin/env python3
"""Safety guard for the old attack-chain harvester.

The benchmark forbids packaging challenge-specific historical answers or
solving methods.  The former implementation wrote per-code writeups into the
Skills image, so it is intentionally disabled.  Add only abstract, challenge-
agnostic lessons to ``skills/experiences/references/case-notes.md`` by hand.
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "已禁用：评测规则禁止将题号、答案、地址、凭据或历史攻击链写入镜像。\n"
        "请人工提炼与题目无关的通用验证原则，写入 skills/experiences/references/case-notes.md。",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
