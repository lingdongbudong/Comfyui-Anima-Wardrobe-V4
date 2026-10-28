# -*- coding: utf-8 -*-
"""v3.1.0 → v3.2.0 工作流迁移。

改了什么
--------
`AnimaV4RandomPrompt` 末尾追加了一个控件 `big_breasts`（巨乳开关），
控件数 **11 → 12**。

为什么必须迁移
--------------
ComfyUI 存盘时按顺序把控件值写进 `widgets_values` 数组。控件数变了而数组没跟着
补，打开老工作流就会出现**后面所有控件整体错位**（权重表被读到外貌对齐位上）。

这次新控件仍加在**末尾**，所以严格说老数组只是"少一项"、不会错位 —— 但项目铁律
是「动过控件个数就必须跑迁移脚本」，理由见 v301 脚本的说明（布尔控件尤其容易
被前端按 `undefined` 处理；且以后插在中间时这套脚本已就位）。

设计要点
--------
· **幂等**：长度已正确就跳过，重复跑结果一致。
· **能补多版**：从 10 项（v3.0.0）或 11 项（v3.1.0）都能一次补到 12 项。
· **只补不删**：比控件数长时按当前控件数截断（末尾多出来的是 ComfyUI 写的
  DOM widget 占位，属已知行为）。
· **不动其他节点**：只碰 AnimaV4RandomPrompt，其余节点逐字节保留。
· **默认不覆盖原件**：加 `--inplace` 才就地改，否则旁边写一份 `.v320.json`。

用法：
    python tools/fix_workflows_v302.py --dry          # 只看会改什么
    python tools/fix_workflows_v302.py                # 写副本
    python tools/fix_workflows_v302.py --inplace      # 就地升级（先备份 .bak-v310）
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

WF_DIRS = [
    "./workflows（按需改成你的工作流目录）",
    "./workflows（按需改成你的工作流目录）",
]

NODE_TYPE = "AnimaV4RandomPrompt"
V320_COUNT = 12

# 追加控件的默认值：**下标 → 默认值**（下标 = 它在控件数组里的位置）。
# 这样从任意旧长度都能正确补齐：
#   10 项（v3.0.0）→ 补下标 10、11 → ["", False]
#   11 项（v3.1.0）→ 补下标 11     → [False]
# ⚠️ 顺序必须与 nodes.py 的 INPUT_TYPES 声明顺序一致。
NEW_WIDGET_DEFAULTS = {
    10: "",       # selected_roles
    11: False,    # big_breasts
}


def pad(wv, count=V320_COUNT):
    """把控件数组补/截到 count 项。"""
    out = list(wv[:count])
    for i in range(len(out), count):
        out.append(NEW_WIDGET_DEFAULTS.get(i, ""))
    return out


def fix_one(path, dry=False, inplace=False):
    """返回 (状态, 说明)。状态 ∈ unchanged / fixed / skipped。"""
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    try:
        d = json.loads(raw)
    except Exception as exc:
        return "skipped", f"不是合法 JSON：{exc}"
    nodes = d.get("nodes")
    if not isinstance(nodes, list):
        return "skipped", "没有 nodes 数组"

    targets = [n for n in nodes if n.get("type") == NODE_TYPE]
    if not targets:
        return "unchanged", "不含本插件节点"

    changed = []
    for n in targets:
        wv = n.get("widgets_values")
        if not isinstance(wv, list):
            continue
        nid = n.get("id")
        if len(wv) == V320_COUNT:
            continue
        if len(wv) > V320_COUNT:
            n["widgets_values"] = wv[:V320_COUNT]
            changed.append(f"节点 {nid}：截断 {len(wv)} → {V320_COUNT}"
                           "（去掉 DOM 占位）")
            continue
        old = len(wv)
        n["widgets_values"] = pad(wv)
        added = [NEW_WIDGET_DEFAULTS.get(i, "") for i in range(old, V320_COUNT)]
        changed.append(f"节点 {nid}：{old} → {V320_COUNT}，补 {added!r}")

    if not changed:
        return "unchanged", "控件数组长度已正确"

    if dry:
        return "fixed", "；".join(changed) + "（--dry，未写盘）"

    if inplace:
        bak = path + ".bak-v310"
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        out = path
    else:
        out = os.path.splitext(path)[0] + ".v320.json"

    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return "fixed", "；".join(changed) + f"  → {os.path.basename(out)}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--inplace", action="store_true")
    ap.add_argument("--dir", action="append", default=[])
    args = ap.parse_args()

    dirs = args.dir or WF_DIRS
    files = []
    for d in dirs:
        if os.path.isdir(d):
            files.extend(sorted(glob.glob(os.path.join(d, "*.json"))))
    print(f"扫描 {len(files)} 个工作流 · 目标节点 {NODE_TYPE}"
          f"（旧版 → {V320_COUNT} 个控件）\n")

    stats = {"unchanged": 0, "fixed": 0, "skipped": 0}
    for f in files:
        try:
            st, msg = fix_one(f, dry=args.dry, inplace=args.inplace)
        except Exception as exc:
            st, msg = "skipped", f"异常 {exc}"
        stats[st] = stats.get(st, 0) + 1
        if st != "skipped" or "JSON" not in msg:
            print(f"  [{st:9s}] {os.path.basename(f)} —— {msg}")

    print(f"\n汇总：需修 {stats['fixed']} · 已正确 {stats['unchanged']}"
          f" · 跳过 {stats['skipped']}")
    if args.dry:
        print("--dry：没有写任何文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
