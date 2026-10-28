# -*- coding: utf-8 -*-
"""v3.0.0 → v3.1.0 工作流迁移。

改了什么
--------
`AnimaV4RandomPrompt` 追加了一个控件 `selected_roles`（面板角色浏览器点选的角色），
控件数从 **10 → 11**。

为什么必须迁移
--------------
ComfyUI 存盘时把控件值按顺序写进 `widgets_values` 数组。
控件数变了而数组没跟着补，打开老工作流就会出现
**后面所有控件整体错位**（权重表读到外貌对齐位上，简直是灾难）。

这次新增的控件在**末尾**，所以严格来说老数组只是"少一项"，
不会错位 —— 但项目铁律是「动过控件个数就必须跑迁移脚本」，
理由有二：
  ① 末尾少一项也可能被前端按 `undefined` 处理，布尔控件尤其容易翻车；
  ② 以后万一有人把新控件插在中间，这套脚本已经就位，不用临时补。

设计要点
--------
· **幂等**：已经补过的（数组长度已对）原样跳过，重复跑结果一致。
· **只补不删**：数组比控件数长时（前端会多写十几个 DOM widget 占位），
  按当前控件数截断，多出来的占位丢掉 —— 这是 ComfyUI 的已知行为。
· **不动其他节点**：只碰 AnimaV4RandomPrompt，其余节点逐字节保留。
· **默认不覆盖原件**：加 `--inplace` 才就地改，否则旁边写一份 .v310.json。

用法：
    python tools/fix_workflows_v301.py --dry          # 只看会改什么
    python tools/fix_workflows_v301.py                # 写副本
    python tools/fix_workflows_v301.py --inplace      # 就地升级（会先备份 .bak-v300）
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)

WF_DIRS = [
    "./workflows（按需改成你的工作流目录）",
    "./workflows（按需改成你的工作流目录）",
]

NODE_TYPE = "AnimaV4RandomPrompt"
V300_COUNT = 10
V310_COUNT = 11


def defaults_for(count):
    """新控件的默认值。只关心第 11 项（selected_roles）——空串。"""
    return [""] * max(0, count - V300_COUNT)


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
        if len(wv) == V310_COUNT:
            continue
        # ⚠️ 存盘时 ComfyUI 会在末尾多写若干 DOM widget 占位，
        #    所以"比控件数长"是正常的，按当前控件数截断即可。
        if len(wv) > V310_COUNT:
            n["widgets_values"] = wv[:V310_COUNT]
            changed.append(f"节点 {nid}：截断 {len(wv)} → {V310_COUNT}（去掉 DOM 占位）")
            continue
        if len(wv) == V300_COUNT:
            n["widgets_values"] = wv + defaults_for(V310_COUNT)
            changed.append(f"节点 {nid}：补 selected_roles = \"\"")
            continue
        # 更短：老到无法判断是哪一版，按当前控件数补齐尾部空值
        pad = V310_COUNT - len(wv)
        n["widgets_values"] = wv + [""] * pad
        changed.append(f"节点 {nid}：长度 {len(wv)} 异常，尾部补 {pad} 项")

    if not changed:
        return "unchanged", "控件数组长度已正确"

    if dry:
        return "fixed", "；".join(changed) + "（--dry，未写盘）"

    if inplace:
        bak = path + ".bak-v300"
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        out = path
    else:
        out = os.path.splitext(path)[0] + ".v310.json"

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
          f"（{V300_COUNT} → {V310_COUNT} 个控件）\n")

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
