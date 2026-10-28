# -*- coding: utf-8 -*-
"""把 Anima-Wardrobe 的 NSFW 判定表**逐字切片**成本插件自己的模块。

为什么不是手抄：
    「同一件事两套口径」是这个项目历史上踩过两次的坑（见造型台
    wardrobe_rules.py 里 grade_explicitness / _nsfw_core 的注释）。
    手抄一份必然漂移，所以这里用 AST 取节点、按源码行号切片，
    连行内注释一起搬过来，做到逐字节一致。

为什么不是「直接 import 造型台」：
    V3 的定位是**自包含**插件 —— 可以单独分享 / 上架 Registry，
    不能依赖另一个插件是否安装。所以：搬运 + 对拍，而不是引用。

对拍：tests/check_nsfw_parity.py 会重新跑一次本脚本并逐字节 diff。
      造型台改了表而这里没同步 → 测试立刻红。

用法：
    python tools/sync_nsfw_tables.py            # 重新生成
    python tools/sync_nsfw_tables.py --check    # 只对拍不写盘
"""
import argparse
import ast
import hashlib
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HERE)

# 源：造型台的规则层（唯一真源）
WARDROBE_RULES = os.path.normpath(os.path.join(
    PLUGIN_ROOT, "..", "Comfyui-Anima-Wardrobe", "wardrobe_rules.py"))

# 目标：本插件自己的 NSFW 模块
TARGET = os.path.join(PLUGIN_ROOT, "anima_v4_nsfw.py")

# ── 要切片的东西（按名字取顶层 Assign / FunctionDef / ClassDef）──
WANTED = [
    # 等级词汇表
    "LEVELS", "LEVEL_RANK", "TARGET_NUM", "LEVEL_CHOICES", "LEVEL_ZH", "LEVEL_ALIAS",
    # 五级标度
    "NSFW_SCALE", "NSFW_MAX", "NSFW_NUM", "NSFW_LABEL", "NSFW_KEY_OF_NUM", "NUM_OF",
    # 三级判定表
    "EXPLICIT_TAGS", "EXPLICIT_EXCEPTIONS", "EXPLICIT_PATTERNS", "SUGGESTIVE_TAGS",
    "ESCALATE_MIN", "ESCALATE_TAGS",
    # 内容分类表
    "NSFW_TABLES", "HARDCORE_CATEGORIES", "EXTREME_CATEGORIES", "CATEGORY_ORDER",
    # 槽位分类用到的辅助表（_has 依赖它）
    "EXACT_ONLY",
    # 函数
    "_has", "_explicit_hits", "_suggestive_hits", "_normalize_tags",
    "_nsfw_core", "grade_explicitness", "resolve_level", "level_label",
    "_nsfw_categories", "grade_nsfw", "format_nsfw", "strip_nsfw",
]

HEADER = '''# -*- coding: utf-8 -*-
"""ANIMA-Wardrobe-V3 · NSFW 判定层（**自动生成，请勿手改**）

来源 : {src_rel}
生成 : tools/sync_nsfw_tables.py
源哈希: {src_hash}

本文件是 Anima-Wardrobe 判定表的**逐字切片**，不是重写。
改判定表只能改造型台那一边，然后重跑：

    python tools/sync_nsfw_tables.py

再跑对拍确认两边没分家：

    python tests/check_nsfw_parity.py

⚠️ 唯一真源是造型台的 wardrobe_rules.py。任何「只在 V3 这边加一条」
   的做法都会让两个插件对同一句话给出不同档位 —— 那正是历史上
   「sfw 档抽出 suggestive 内容」这个 bug 的根因。
"""
# 切片过来的函数只依赖 re（造型台那边还有 json/os/random，本层用不到，
# 刻意不引 —— 少一个 import 就少一个「V3 和造型台依赖不同」的可能）。
import re
'''


def _slice_source(src_text):
    tree = ast.parse(src_text)
    found = {}
    for node in tree.body:
        name = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Name):
                name = t.id
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            name = node.name
        if name and name in WANTED and name not in found:
            found[name] = node

    missing = [n for n in WANTED if n not in found]
    if missing:
        raise SystemExit(
            "以下名字在造型台规则层里找不到，源文件结构可能已变：\n  "
            + "\n  ".join(missing))

    lines = src_text.splitlines()
    chunks = {}
    for name, node in found.items():
        decos = getattr(node, "decorator_list", None) or []
        start = (decos[0].lineno - 1) if decos else (node.lineno - 1)
        end = node.end_lineno
        # 往上吃掉紧贴的注释块（切片的可读性全靠它）
        while start > 0 and lines[start - 1].lstrip().startswith("#"):
            start -= 1
        chunks[name] = (node.lineno, "\n".join(lines[start:end]).rstrip())
    return chunks


def build():
    with open(WARDROBE_RULES, "r", encoding="utf-8") as fh:
        src_text = fh.read()
    src_hash = hashlib.sha256(src_text.encode("utf-8")).hexdigest()
    chunks = _slice_source(src_text)

    # 按源码行号排序 —— 让生成结果与源文件的阅读顺序一致，
    # 也使 diff 稳定（同名项重排会让 review 变成灾难）。
    body = []
    seen = set()
    for name in WANTED:
        if name in seen:
            continue
        seen.add(name)
        body.append((chunks[name][0], chunks[name][1]))

    # 二次排序：同名项可能在 WANTED 里位于不同段落，这里统一按源文件顺序输出
    ordered = [txt for _ln, txt in sorted(body, key=lambda x: x[0])]

    header = HEADER.format(
        src_rel="custom_nodes/Comfyui-Anima-Wardrobe/wardrobe_rules.py",
        src_hash=src_hash)
    return header + "\n\n" + "\n\n\n".join(ordered) + "\n", src_hash


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只对拍不写盘")
    args = ap.parse_args()

    if not os.path.exists(WARDROBE_RULES):
        print(f"[sync_nsfw_tables] 找不到源文件：{WARDROBE_RULES}")
        return 2

    text, src_hash = build()

    if args.check:
        if not os.path.exists(TARGET):
            print(f"[sync_nsfw_tables] --check 失败：{TARGET} 不存在")
            return 1
        with open(TARGET, "r", encoding="utf-8") as fh:
            old = fh.read()
        # 头部里的生成时间/哈希会变，只比对正文
        def body_of(t):
            i = t.find('"""', t.find('"""') + 3)
            return t[i + 3:].strip()
        if body_of(old) != body_of(text):
            print("[sync_nsfw_tables] --check 失败：V3 的判定表与造型台已漂移")
            return 1
        print(f"[sync_nsfw_tables] --check 通过（源 sha256 {src_hash[:16]}…）")
        return 0

    with open(TARGET, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(f"[sync_nsfw_tables] 已写出 {TARGET}")
    print(f"  源 {os.path.basename(WARDROBE_RULES)} · sha256 {src_hash[:16]}…"
          f" · {len(text.splitlines())} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
