# -*- coding: utf-8 -*-
"""对拍：V3 的 NSFW 判定表 vs 造型台（Anima-Wardrobe）的真源。

为什么要这条测试：
    V3 的 anima_v4_nsfw.py 是从造型台 wardrobe_rules.py **逐字切片**来的。
    切片意味着"复制"，而复制必然漂移。这条测试就是防漂移的那道闸：
    造型台改了表而 V3 没重新同步 → 立刻红。

    一旦两边分家，同一个提示词在两个插件里会给出不同档位 ——
    那正是历史上「sfw 档抽出 suggestive 内容」这个 bug 的根因。

跑法：python tests/check_nsfw_parity.py
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _boot  # noqa: E402

PLUGIN = os.path.dirname(HERE)
WARDROBE = os.path.normpath(os.path.join(
    PLUGIN, "..", "Comfyui-Anima-Wardrobe", "wardrobe_rules.py"))
V3_NSFW = os.path.join(PLUGIN, "anima_v4_nsfw.py")

# 必须逐字一致的东西。函数体也要对 —— 只对常量不对函数，
# 等于放任"表一样但判定逻辑不一样"这种更隐蔽的分家。
MUST_MATCH = [
    "LEVELS", "LEVEL_RANK", "TARGET_NUM", "LEVEL_CHOICES", "LEVEL_ZH",
    "LEVEL_ALIAS", "NSFW_SCALE", "NSFW_MAX", "NSFW_NUM", "NSFW_LABEL",
    "NSFW_KEY_OF_NUM", "NUM_OF", "EXPLICIT_TAGS", "EXPLICIT_EXCEPTIONS",
    "EXPLICIT_PATTERNS", "SUGGESTIVE_TAGS", "ESCALATE_MIN", "ESCALATE_TAGS",
    "NSFW_TABLES", "HARDCORE_CATEGORIES", "EXTREME_CATEGORIES",
    "CATEGORY_ORDER", "EXACT_ONLY",
    "_has", "_explicit_hits", "_suggestive_hits", "_normalize_tags",
    "_nsfw_core", "grade_explicitness", "resolve_level", "level_label",
    "_nsfw_categories", "grade_nsfw", "format_nsfw", "strip_nsfw",
]


def normalize(src):
    """把源码归一成可比对形式：去空行、去行尾空格、统一换行。"""
    lines = [ln.rstrip() for ln in src.replace("\r\n", "\n").split("\n")]
    return "\n".join(ln for ln in lines if ln.strip())


def slices(path):
    """按 AST 取顶层节点，返回 {名字: 归一化源码}。"""
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    tree = ast.parse(text)
    lines = text.split("\n")
    out = {}
    for node in tree.body:
        name = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            name = node.name
        if name:
            out[name] = normalize("\n".join(lines[node.lineno - 1:node.end_lineno]))
    return out


def main():
    fails = []

    if not os.path.exists(WARDROBE):
        print(f"[SKIP] 造型台未安装，跳过对拍：{WARDROBE}")
        return 0

    a = slices(WARDROBE)
    b = slices(V3_NSFW)

    for name in MUST_MATCH:
        if name not in a:
            fails.append(f"造型台里找不到 {name}（源结构变了？）")
            continue
        if name not in b:
            fails.append(f"V3 的 anima_v4_nsfw.py 里缺少 {name}")
            continue
        if a[name] != b[name]:
            fails.append(f"{name} 与造型台不一致 —— 请重跑 tools/sync_nsfw_tables.py")

    # 行为对拍：拿一批真实标签跑两边的 grade_nsfw，逐条比对档位
    try:
        nsfw = _boot.load("anima_v4_nsfw")
    except Exception as exc:
        fails.append(f"V3 判定层导入失败：{exc}")
        nsfw = None

    if nsfw is not None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_wardrobe_rules", WARDROBE)
        wr = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(wr)
        except Exception as exc:
            print(f"[WARN] 造型台规则层无法直接导入（{exc}），只做源码对拍")
            wr = None
        if wr is not None:
            probes = [
                [], ["1girl", "solo"], ["black hair"],
                ["wet hair"], ["see-through"], ["micro bikini"],
                ["completely nude"], ["nipples"], ["clitoris"],
                ["missionary"], ["creampie"], ["shibari"], ["vibrator"],
                ["gangbang"], ["double penetration"], ["suspension"],
                ["bukkake"], ["excessive cum"], ["collar and leash"],
                ["torn clothes"], ["open shirt"], ["upskirt"],
                ["latex"], ["lingerie"], ["nightgown"],
                ["after sex"], ["red velvet"], ["presenting"],
            ]
            for p in probes:
                x = nsfw.grade_nsfw(p)["num"]
                y = wr.grade_nsfw(p)["num"]
                if x != y:
                    fails.append(f"grade_nsfw({p}) 结果不同：V3={x} 造型台={y}")

    if fails:
        print(f"[check_nsfw_parity] 失败 {len(fails)} 项：")
        for f in fails:
            print("  ·", f)
        return 1
    print(f"[check_nsfw_parity] 通过：{len(MUST_MATCH)} 项逐字一致 · 行为对拍一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
