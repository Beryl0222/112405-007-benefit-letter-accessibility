#!/usr/bin/env python3
"""端到端演练（合成文本，不对应真实人员或机构）。

覆盖四个业务场景：

1. 正常决定书（含更正记录）生成易读版并通过五维度核对；
2. 互相矛盾的决定书被阻断，问题交还经办人，不产生易读版；
3. 草稿 → 送达快照 → 送达后再次更正：快照冻结、草稿更新；
4. 申请人追问时，按关键词在送达快照中追溯当时句子及正式依据位置。

运行：
    python3 -I demo.py
"""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyread.pipeline import load_case_file, run
from easyread.store import BlockedBundle, CaseStore


def separator(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def main() -> int:
    # 场景一：正常决定书 + 更正
    separator("场景一：正常决定书（含更正 R7）生成易读版并自检")
    case_id, records = load_case_file(ROOT / "data" / "decision_sample.json")
    result = run(records, case_id=case_id)
    assert result.ok
    print(result.document.plain_text())
    print()
    print(result.report.plain_text())

    # 场景二：矛盾阻断
    separator("场景二：矛盾决定书被阻断，问题交还经办人")
    bad_case_id, bad_records = load_case_file(ROOT / "data" / "contradiction_sample.json")
    bad_result = run(bad_records, case_id=bad_case_id)
    assert not bad_result.ok and bad_result.document is None
    print("流水线未生成易读版，需经办人处理的矛盾：")
    for issue in bad_result.issues:
        print(f"- {issue}")

    # 场景三 + 四：版本留存与追问追溯
    separator("场景三：草稿 → 送达 → 送达后更正（快照冻结、草稿更新）")
    with tempfile.TemporaryDirectory() as tmp:
        store = CaseStore(tmp)
        draft_v1 = store.build_draft("benefit-demo-1", records)
        print(f"草稿 v{draft_v1.version} 已生成，补交期限表述：", end="")
        print([s.text for s in draft_v1.document.sentences if "补交材料的期限" in s.text][0])

        snapshot = store.serve("benefit-demo-1")
        print(f"送达快照 {snapshot.served_id} 已冻结（文件只读，正文哈希 {snapshot.doc_hash[:12]}…）")

        # 送达后决定书又更正：重建草稿，快照不动
        further_correction = records + [
            type(records[0])(
                "R8",
                "更正：R3 的期限为二十个工作日，其他内容不变。",
                "correction",
            )
        ]
        draft_v2 = store.build_draft("benefit-demo-1", further_correction)
        print(f"草稿 v{draft_v2.version} 已反映新更正，新表述：", end="")
        print([s.text for s in draft_v2.document.sentences if "补交材料的期限" in s.text][0])

        frozen = store.load_served("benefit-demo-1", snapshot.served_id)
        frozen_sentence = [
            s.text for s in frozen.document.sentences if "补交材料的期限" in s.text
        ][0]
        print(f"已送达快照仍保留当时内容：{frozen_sentence}")

        separator("场景四：申请人追问「期限」，追溯送达版本的正式依据")
        hits = store.trace_sentence("benefit-demo-1", snapshot.served_id, "期限")
        for hit in hits:
            print(f"【{hit['section']}】{hit['text']}")
            for evidence in hit["evidence"]:
                print(f"    依据 {evidence['locator']}：{evidence['official_text']}")

    print("\n全部演练场景完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
