"""命令行入口（仅使用标准库）。

示例
----
# 生成易读版与核对报告（输出到终端）
python3 -m easyread.cli rewrite data/decision_sample.json

# 只看抽取到的结构化事实
python3 -m easyread.cli extract data/decision_sample.json

# 矛盾排查（不生成易读版）
python3 -m easyread.cli inspect data/contradiction_sample.json

# 完整版本流转：建草稿 → 送达 → 更正后重建草稿 → 追问检索
python3 -m easyread.cli store build   CASE-1 data/decision_sample.json --store .workdir
python3 -m easyread.cli store serve   CASE-1 --store .workdir
python3 -m easyread.cli store trace   CASE-1 <served_id> 期限 --store .workdir
"""

from __future__ import annotations

import argparse
import json
import sys

from .errors import ContradictionError
from .pipeline import inspect_only, load_case_file, run
from .store import BlockedBundle, CaseStore


def _print_json(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _cmd_extract(args) -> int:
    _, records = load_case_file(args.case_file)
    sheet, issues = inspect_only(records)
    _print_json({"facts": sheet.to_dict(), "contradictions": [i.to_dict() for i in issues]})
    return 0


def _cmd_inspect(args) -> int:
    _, records = load_case_file(args.case_file)
    sheet, issues = inspect_only(records)
    if issues:
        print("发现以下矛盾，已阻断易读版生成，请交还经办人：", file=sys.stderr)
        for issue in issues:
            print(f"- {issue}", file=sys.stderr)
        _print_json({"contradictions": [i.to_dict() for i in issues]})
        return 2
    print("未发现矛盾。抽取到的事实：", file=sys.stderr)
    _print_json(sheet.to_dict())
    return 0


def _cmd_rewrite(args) -> int:
    case_id, records = load_case_file(args.case_file)
    result = run(records, case_id=case_id)
    if not result.ok:
        print("正式文本存在矛盾，未生成易读版：", file=sys.stderr)
        for issue in result.issues:
            print(f"- {issue}", file=sys.stderr)
        _print_json(result.to_dict())
        return 2
    print(result.document.plain_text())
    print()
    print(result.report.plain_text())
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(result.to_dict(), handle, ensure_ascii=False, indent=2)
    return 0 if result.report.passed else 1


def _cmd_store(args) -> int:
    store = CaseStore(args.store)
    if args.store_action == "build":
        case_id, records = load_case_file(args.case_file)
        case_id = args.case_id or case_id
        bundle = store.try_build(case_id, records)
        if isinstance(bundle, BlockedBundle):
            print("草稿被阻断：正式文本存在矛盾，需经办人处理。", file=sys.stderr)
            _print_json(bundle.to_dict())
            return 2
        print(bundle.document.plain_text())
        print()
        print(bundle.report.plain_text())
        print(f"\n草稿版本 v{bundle.version} 已保存：{store._draft_path(case_id)}")
        return 0 if bundle.report.passed else 1
    if args.store_action == "serve":
        snapshot = store.serve(args.case_id)
        print(f"已生成只读送达快照 {snapshot.served_id}，内容已冻结。")
        print(f"快照文件：{store._snapshot_path(args.case_id, snapshot.served_id)}")
        return 0
    if args.store_action == "list":
        served = store.list_served(args.case_id)
        if not served:
            print("该案件暂无送达快照。")
        for snapshot in served:
            print(f"{snapshot.served_id}  送达时间 {snapshot.served_at}  正文哈希 {snapshot.doc_hash[:12]}")
        return 0
    if args.store_action == "trace":
        hits = store.trace_sentence(args.case_id, args.served_id, args.keyword)
        if not hits:
            print(f"快照 {args.served_id} 中未检索到包含「{args.keyword}」的句子。", file=sys.stderr)
            return 1
        _print_json(hits)
        return 0
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="easyread", description="补助决定书易读改写与权利保真工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p_extract = sub.add_parser("extract", help="抽取结构化事实并输出 JSON")
    p_extract.add_argument("case_file")
    p_extract.set_defaults(func=_cmd_extract)

    p_inspect = sub.add_parser("inspect", help="矛盾排查（不生成易读版）")
    p_inspect.add_argument("case_file")
    p_inspect.set_defaults(func=_cmd_inspect)

    p_rewrite = sub.add_parser("rewrite", help="生成易读版并执行核对")
    p_rewrite.add_argument("case_file")
    p_rewrite.add_argument("--json-out", help="把完整结构化结果写入指定 JSON 文件")
    p_rewrite.set_defaults(func=_cmd_rewrite)

    p_store = sub.add_parser("store", help="草稿/送达版本流转")
    store_sub = p_store.add_subparsers(dest="store_action", required=True)

    p_build = store_sub.add_parser("build", help="生成或重建草稿")
    p_build.add_argument("case_id")
    p_build.add_argument("case_file")
    p_build.add_argument("--store", required=True)
    p_build.set_defaults(func=_cmd_store)

    p_serve = store_sub.add_parser("serve", help="把当前草稿冻结为送达快照")
    p_serve.add_argument("case_id")
    p_serve.add_argument("--store", required=True)
    p_serve.set_defaults(func=_cmd_store)

    p_list = store_sub.add_parser("list", help="列出送达快照")
    p_list.add_argument("case_id")
    p_list.add_argument("--store", required=True)
    p_list.set_defaults(func=_cmd_store)

    p_trace = store_sub.add_parser("trace", help="在送达快照中检索追问句子的正式依据")
    p_trace.add_argument("case_id")
    p_trace.add_argument("served_id")
    p_trace.add_argument("keyword")
    p_trace.add_argument("--store", required=True)
    p_trace.set_defaults(func=_cmd_store)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ContradictionError as exc:
        print("处理被阻断：正式文本存在矛盾，需交还经办人。", file=sys.stderr)
        for issue in exc.issues:
            print(f"- {issue}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"文件不存在：{exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
