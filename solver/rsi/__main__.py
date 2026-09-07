"""CLI: list packs, resolve codes, analyze workspace, record skill edits."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from solver.runtime.settings import load_settings
from solver.rsi.analyze import analyze_and_emit, analyze_workspace, write_report
from solver.rsi.packs import (
    codes_for_cli,
    list_packs_summary,
    pack_codes,
    resolve_only_codes,
)
from solver.rsi.skill_harness import SkillRefinementLog


def _default_skills_dir() -> str:
    return os.environ.get("CTF_SKILLS_DIR", "skills")


def _default_workspace() -> str:
    return os.environ.get("CTF_WORKSPACE", "workspace")


def cmd_list_packs(args: argparse.Namespace) -> int:
    settings = load_settings()
    for row in list_packs_summary(settings):
        count = row["count"]
        print(f"{row['name']}\t{count}\t{row['description']}")
        if row["codes"]:
            print(f"  codes: {', '.join(row['codes'])}")
        elif row.get("prefix_filter"):
            print(f"  prefix: {row['prefix_filter']}")
    return 0


def cmd_codes(args: argparse.Namespace) -> int:
    settings = load_settings()
    print(codes_for_cli(args.pack, settings))
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    settings = load_settings()
    pack = args.pack or ""
    expected = pack_codes(pack, settings) if pack else None
    if args.expected:
        expected = [c.strip() for c in args.expected.split(",") if c.strip()]

    report = analyze_workspace(
        args.workspace,
        expected_codes=expected,
        pack=pack,
    )
    json_path, md_path = write_report(report, args.workspace)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    print(f"\nWrote {json_path} and {md_path}", file=sys.stderr)
    return 0 if report.pass_regression or not expected else 1


def cmd_record(args: argparse.Namespace) -> int:
    log = SkillRefinementLog(args.skills_dir)
    files = [f.strip() for f in args.files.split(",") if f.strip()]
    event = log.record_edit(
        pack=args.pack,
        reason=args.reason,
        files=files,
        run_id=args.run_id,
        evidence_codes=[c.strip() for c in args.evidence.split(",") if c.strip()],
        layer=args.layer,
    )
    print(json.dumps(event, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EVA-Mimir RSI local loop")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list-packs", help="List regression packs")
    p_list.set_defaults(func=cmd_list_packs)

    p_codes = sub.add_parser("codes", help="Print comma-separated codes for a pack")
    p_codes.add_argument("pack")
    p_codes.set_defaults(func=cmd_codes)

    p_analyze = sub.add_parser("analyze", help="Analyze workspace after a run")
    p_analyze.add_argument("--workspace", default=_default_workspace())
    p_analyze.add_argument("--pack", default="")
    p_analyze.add_argument("--expected", default="", help="Override expected codes")
    p_analyze.set_defaults(func=cmd_analyze)

    p_record = sub.add_parser("record", help="Record a skill edit in the ledger")
    p_record.add_argument("--pack", required=True)
    p_record.add_argument("--reason", required=True)
    p_record.add_argument("--files", required=True, help="Comma-separated skill paths")
    p_record.add_argument("--skills-dir", default=_default_skills_dir())
    p_record.add_argument("--run-id", default="")
    p_record.add_argument("--evidence", default="", help="Comma-separated challenge codes")
    p_record.add_argument("--layer", default="skill", choices=["skill", "router", "scheduler"])
    p_record.set_defaults(func=cmd_record)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
