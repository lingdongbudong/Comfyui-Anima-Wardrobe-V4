# -*- coding: utf-8 -*-
"""v3.17.0 / v3.19.0 工作流迁移：控件数 **13 → 15**。

改了什么
--------
`AnimaV4RandomPrompt` 末尾追加了两个控件（都追加在末尾，不改既有顺序）：

    下标 13  breast_size   「胸部大小」六档（v3.17.0，取代 big_breasts 开关）
    下标 14  outfit_style  「服装风格」智配（v3.19.0）

⚠️ 为什么 v3.17.0 当时没补：那一版只动了 `breast_size` 一个控件，
   而 ComfyUI 打开老工作流时缺失的尾部控件会用**默认值**填充（"不指定"），
   表现上"看起来没坏"，于是漏了迁移脚本。v3.19.0 验收时发现
   `fix_workflows_v303.py` 的 NEW_COUNT 还停在 13，顺手补齐 —— 这里一次
   从 10/11/12/13/14 任意长度补到 15。

设计要点（与 v301/v302/v303 完全一致）
------------------------------------
· **幂等**：长度已正确就跳过，重复跑结果一致。
· **只补不删**：比 15 长时按 15 截断（末尾多出来的是 ComfyUI 写的 DOM 占位）。
· **不动其他节点**：只碰 AnimaV4RandomPrompt。
· **默认不覆盖原件**：加 `--inplace` 才就地改，否则旁边写 `.v3190.json`。

用法：
    python tools/fix_workflows_v3190.py --dry
    python tools/fix_workflows_v3190.py --inplace
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
NEW_COUNT = 15

#: 下标 → 默认值。顺序必须与 nodes.py 的 INPUT_TYPES 声明顺序一致。
NEW_WIDGET_DEFAULTS = {
    10: "",          # selected_roles（v3.1.0）
    11: False,       # big_breasts（v3.2.0，已退役但控件位保留）
    12: "",          # role_works（v3.10.0）
    13: "不指定",     # breast_size（v3.17.0）
    14: "随机",       # outfit_style（v3.19.0）
}


def pad(wv, count=NEW_COUNT):
    out = list(wv[:count])
    for i in range(len(out), count):
        out.append(NEW_WIDGET_DEFAULTS.get(i, ""))
    return out


def fix_one(path, dry=False, inplace=False):
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
        if len(wv) == NEW_COUNT:
            continue
        if len(wv) > NEW_COUNT:
            n["widgets_values"] = wv[:NEW_COUNT]
            changed.append(f"节点 {nid}：截断 {len(wv)} → {NEW_COUNT}（去掉 DOM 占位）")
            continue
        old = len(wv)
        n["widgets_values"] = pad(wv)
        added = [NEW_WIDGET_DEFAULTS.get(i, "") for i in range(old, NEW_COUNT)]
        changed.append(f"节点 {nid}：{old} → {NEW_COUNT}，补 {added!r}")

    if not changed:
        return "unchanged", "控件数组长度已正确"

    if dry:
        return "fixed", "；".join(changed) + "（--dry，未写盘）"

    if inplace:
        bak = path + ".bak-v3180"
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        out = path
    else:
        out = os.path.splitext(path)[0] + ".v3190.json"

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
          f"（旧版 → {NEW_COUNT} 个控件）\n")

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
