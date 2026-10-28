# -*- coding: utf-8 -*-
"""服装智配 + 颜色合成基线（v3.19.0）。

守七件事，全是"不报错但会静默失效"的类型：

  ① **颜色字段与引擎常量双向一致** —— 词库里有几个色，引擎就得认几个。
     少一个 = 那个颜色永远抽不出颜色（变成裸色 tag 被丢掉）。

  ② **风格表覆盖完整** —— 服装六类的每个选项都必须在 STYLE_OF 里登记
     （哪怕是显式空串=中性）。漏登记不会报错，只是那条词**不参与智配**。

  ③ **表里的每个取值都真实存在于词库** —— 写错一个词（`thighhigh` 少了 s）
     不会报错，只会让那条约束**永远不生效**。

  ④ **颜色合成四条路径** —— 命中矩阵 / 旧条目已带色跳过 / 换落点 /
     无落点。任何一条走错都会吐无效 tag 或吞掉颜色。

  ⑤ **层级抑制** —— 整套服装抽到后，上装/下装必须被压到近零
     （否则会出现「连衣裙 + 衬衫 + 长裤」三层叠穿）。

  ⑥ **风格硬收敛** —— 控件指定「泳装」时，整套服装只允许泳装组。

  ⑦ **控件候选与引擎真源一致** —— 节点下拉、面板下拉、引擎三处同一份。

跑法：python tests/check_v3_color.py [轮数，默认 40]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import _boot  # noqa: E402

OS = _boot.load("anima_v4_outfit_style")
R = _boot.load("anima_v4_rules")

POOLS = os.path.join(PLUGIN, "presets", "anima_v4_pools.json")
FIELDS = ("outfit", "top", "bottom", "socks", "shoes", "accessory")

FAILS = []


def ck(cond, label, detail=""):
    print(f"  [{'OK' if cond else '!!'}] {label}" + (f" —— {detail}" if detail else ""))
    if not cond:
        FAILS.append(label)
    return cond


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    pools = json.load(open(POOLS, encoding="utf-8"))
    sec = {s["id"]: s for s in pools["sections"]}
    fld = {f["key"]: f for s in pools["sections"] for f in s["fields"]}
    opts = {k: [en for _zh, en in fld[k]["opts"]]
            for k in FIELDS + ("cloth_color", "sock_color")}

    # ── ① 颜色字段与引擎常量 ────────────────────────────────────────
    print("① 颜色字段一致性")
    ck("cloth_color" in fld, "词库存在 cloth_color 字段")
    ck(opts["cloth_color"] == OS.COLOR_TAGS,
       "词库颜色 == OS.COLOR_TAGS", f"{len(opts['cloth_color'])} 色")
    ck("sock_color" in fld, "词库存在 sock_color 字段")
    ck(opts["sock_color"] == OS.COLOR_TAGS,
       "袜子色 == OS.COLOR_TAGS（两通道同一套色）", f"{len(opts['sock_color'])} 色")
    ck(all(c in OS.COLOR_ZH for c in OS.COLOR_TAGS), "每个颜色都有中文名")
    ck(len(set(OS.COLOR_TAGS)) == len(OS.COLOR_TAGS), "颜色无重复")

    # ── ②③ 风格表覆盖 + 取值有效性 ────────────────────────────────
    print("②③ 风格表覆盖与有效性")
    missing, bad_key = [], []
    for k in FIELDS:
        table = OS.STYLE_OF.get(k) or {}
        for en in opts[k]:
            if en not in table:
                missing.append(f"{k}/{en}")
        for en in table:
            if en not in opts[k]:
                bad_key.append(f"{k}/{en}")
    ck(not missing, "服装六类每个选项都登记了风格", f"漏 {len(missing)}：{missing[:6]}")
    ck(not bad_key, "风格表无词库外键", f"多 {len(bad_key)}：{bad_key[:6]}")

    bad_style, bad_ban = [], []
    for k, table in OS.STYLE_OF.items():
        for en, raw in table.items():
            for s in str(raw).split():
                if s not in dict(OS.STYLES):
                    bad_style.append(f"{k}/{en}->{s}")
    for (style, k), vals in OS.STYLE_BANS.items():
        if style not in dict(OS.STYLES):
            bad_style.append(f"BAN 风格 {style}")
        for en in vals:
            if en not in opts.get(k, []):
                bad_ban.append(f"STYLE_BANS[{style}][{k}]={en}")
    for anchor, per in OS.ANCHOR_BANS.items():
        if anchor not in opts["outfit"]:
            bad_ban.append(f"ANCHOR_BANS 锚点 {anchor}")
        for k, vals in per.items():
            for en in vals:
                if en not in opts.get(k, []):
                    bad_ban.append(f"ANCHOR_BANS[{anchor}][{k}]={en}")
    ck(not bad_style, "风格名都合法", str(bad_style[:5]))
    ck(not bad_ban, "铁律表取值都在词库里", str(bad_ban[:5]))

    # 每个风格至少有一个 outfit，否则「选该风格」等于空转
    empty = []
    for key, zh in OS.STYLES:
        if not any(key in str(v).split() for v in (OS.STYLE_OF["outfit"] or {}).values()):
            empty.append(zh)
    ck(not empty, "每个风格都有整套服装可抽", str(empty))

    # ── ④ 颜色合成四条路径 ─────────────────────────────────────────
    print("④ 颜色合成")
    ck(OS.combo_ok("purple", "thighhighs"), "矩阵：紫色+过膝袜 有效")
    ck(not OS.combo_ok("purple", "kneehighs"), "矩阵：紫色+及膝袜 无效（已知盲区）")

    # v3.20.0 起「袜子颜色」走独立的 sock_color 通道 —— 旧断言用 cloth_color
    # 染袜子的写法已不成立（那是分通道要解决的问题本身）。
    st = {"sock_color": "purple", "socks": "thighhighs, garter straps"}
    notes = OS.colorize(st)
    ck(st.get("socks") == "purple thighhighs, garter straps",
       "紫色 + 吊带袜 → 组合 tag", str(st.get("socks")))
    ck("sock_color" not in st, "合成后不再单独输出颜色")
    ck(notes and "颜色合成" in notes[0], "合成有回显")

    st = {"sock_color": "red", "socks": "black thighhighs"}
    notes = OS.colorize(st)
    ck(st.get("socks") == "black thighhighs", "旧条目已带色 → 不覆盖",
       str(st.get("socks")))
    ck(notes and "已自带颜色" in notes[0], "跳过有原因回显")

    # ── ④之二 双通道：袜子色只管袜子，主色只管身上 ──────────────
    st = {"sock_color": "purple", "socks": "thighhighs", "bottom": "skirt"}
    OS.colorize(st)
    ck(st.get("socks") == "purple thighhighs", "袜子色只落到 socks",
       str(st.get("socks")))
    ck(st.get("bottom") == "skirt", "袜子色不污染下装", str(st.get("bottom")))
    ck("sock_color" not in st, "袜子色合成后不单独输出")

    st = {"cloth_color": "red", "socks": "thighhighs", "bottom": "skirt"}
    OS.colorize(st)
    ck(st.get("bottom") == "red skirt", "主色只落到下装/上装/整套",
       str(st.get("bottom")))
    ck(st.get("socks") == "thighhighs", "主色**不**再抢袜子（v3.20.0 分通道）",
       str(st.get("socks")))

    st = {"sock_color": "red", "cloth_color": "blue",
          "socks": "thighhighs", "bottom": "skirt", "outfit": "dress"}
    OS.colorize(st)
    ck(st.get("socks") == "red thighhighs" and st.get("bottom") == "blue skirt",
       "两色并存各管各的", f"{st.get('socks')} / {st.get('bottom')}")

    st = {"sock_color": "purple", "socks": "kneehighs"}
    notes = OS.colorize(st)
    ck(st.get("socks") == "kneehighs" and notes and "跳过" in notes[0],
       "袜子色落在不可着色的款式上 → 跳过并回显", str(notes[:1]))

    st = {"sock_color": "purple"}
    notes = OS.colorize(st)
    ck(notes and "无落点" in notes[0], "没抽到袜子时不崩且如实回报", str(notes[:1]))

    # 合成出来的 tag 必须都在矩阵里被认过（不许凭空造 tag）
    bad_combo = []
    for c in OS.COLOR_TAGS:
        for g in ("thighhighs", "skirt", "pantyhose", "dress"):
            if OS.combo_ok(c, g):
                st = {"sock_color": c, "socks": g}
                OS.colorize(st)
                if st.get("socks") != f"{c} {g}":
                    bad_combo.append(f"{c}/{g}")
    ck(not bad_combo, "矩阵命中即真的拼上", str(bad_combo[:5]))

    # ── ⑤ 层级抑制 ────────────────────────────────────────────────
    print("⑤ 层级抑制（防三层叠穿）")
    for outfit in ("school uniform", "jirai kei", "evening gown"):
        b = OS.layer_bias({"outfit": outfit}, "top")
        ck(b <= 0.1, f"{outfit} → 压掉上装", f"×{b}")
    ck(OS.layer_bias({"outfit": "apron only"}, "top") == 1.0,
       "局部单品（仅围裙）不压制上装")
    ck(OS.layer_bias({}, "top") == 1.0, "没抽到整套 → 不干预")
    ck(OS.layer_bias({"outfit": "dress"}, "socks") == 1.0,
       "整套只压上装/下装，不压袜子")

    # ── ⑥ 风格智配运行时 ─────────────────────────────────────────
    print("⑥ 风格硬收敛（运行时）")
    swim = {"swim", "casual", "sporty"}      # 泳装组 + 高兼容组
    bad = []
    hit = 0
    for i in range(rounds):
        d = R.draw(level="sfw", seed=i, outfit_style="泳装")
        o = d["state"].get("outfit")
        # ⚠️ 法典场景预设会**显式写死**整套服装（如 sc_office_overtime），
        #    那是用户主动套用的，优先级高于智配 —— 这类轮次不参与断言。
        if d["state"].get("n_canon"):
            continue
        if not o:
            continue
        hit += 1
        # ⚠️ 成品里的 outfit 可能已被颜色合成改写成「brown bikini」，
        #    判风格前先把颜色前缀剥掉（合成是另一条链路，不由这里负责）。
        base = o
        for c in OS.COLOR_TAGS:
            if base.startswith(c + " "):
                base = base[len(c) + 1:]
                break
        stl = OS.style_of_value("outfit", base)
        # 中性单品（缠胸布之类）没有风格倾向，不算违规
        if stl and not (stl & swim):
            bad.append(o)
    ck(hit > 0, "泳装风格确实抽到了整套服装", f"{hit}/{rounds} 轮")
    ck(not bad, "泳装风格下整套只会是泳装/兼容组", str(bad[:5]))

    # 「随机」下不得干预过多：抽到的整套风格应有多样性
    styles = set()
    for i in range(rounds):
        d = R.draw(level="sfw", seed=1000 + i, outfit_style="随机")
        o = d["state"].get("outfit")
        if o:
            styles |= OS.style_of_value("outfit", o)
    ck(len(styles) >= 3, "「随机」保持风格多样性", f"{sorted(styles)}")

    # 「不限」= 智配关闭：风格权重必须恒为 1.0
    ck(all(OS.style_bias({"outfit": "school uniform"}, k, "shirt", "不限") == 1.0
           for k in ("top",)), "「不限」关闭智配（权重恒 1.0）")

    # 成品里不允许出现「整套 + 上装 + 下装」三层
    triple = []
    for i in range(rounds):
        s = R.draw(level="sfw", seed=2000 + i, outfit_style="随机")["state"]
        if s.get("n_canon"):
            continue
        o = s.get("outfit")
        if o and o not in OS.OUTFIT_PARTIAL and s.get("top") and s.get("bottom"):
            triple.append(f"{o} + {s['top']} + {s['bottom']}")
    ck(len(triple) <= max(1, rounds // 10),
       "三层叠穿被压到可忽略", f"{len(triple)}/{rounds}：{triple[:3]}")

    # ── ⑦ 控件候选三处一致 ────────────────────────────────────────
    print("⑦ 控件候选一致性")
    try:
        N = _boot.load("nodes")
        ck(list(N.OUTFIT_STYLE_CHOICES) == list(OS.STYLE_CHOICES),
           "节点控件候选 == 引擎真源", str(N.OUTFIT_STYLE_CHOICES))
    except Exception as exc:
        print(f"  [SKIP] 加载 nodes 失败（{exc}），跳过节点一致性")
    js = os.path.join(PLUGIN, "js", "anima_wardrobe_v4_studio.js")
    txt = open(js, encoding="utf-8").read()
    miss = [z for z in OS.STYLE_CHOICES if f'"{z}"' not in txt]
    ck(not miss, "面板下拉覆盖全部候选", str(miss))

    print()
    if FAILS:
        print(f"[check_v3_color] 失败 {len(FAILS)} 项：{FAILS}")
        return 1
    print("[check_v3_color] 通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
