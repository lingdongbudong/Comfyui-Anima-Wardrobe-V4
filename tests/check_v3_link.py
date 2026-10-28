# -*- coding: utf-8 -*-
"""字段联动基线（v3.15.0 新增）。

守五件事，每一件都是"不报错但会静默失效"的类型：

  ① **三张联动表与词库的一致性** —— 表里每个键/取值都必须真实存在于词库里。
     写错一个词（比如把 `boy on top` 记成 `male on top`）不会报任何错，
     只会让那条约束**永远不生效**。

  ② **场景主题覆盖完整** —— 每个 place 都必须能查到主题。漏一个 =
     那个场景的服装/姿势联动静默失效（而且查不出来）。

  ③ **运行时零矛盾** —— 真跑 N 轮，n_act × n_pos 与 emotion × 嘴部/眼神
     的成品里不允许出现表里登记过的矛盾组合。

  ④ **场景加权真的生效** —— `place=poolside` 时泳装出现率必须显著高于
     无场景时的基线；且违和项（和服 / 大衣）必须**一次都不出现**。

  ⑤ **场景搭配库的字段引用完整性** —— `anima_v4_scenes.json` 直接存
     字段取值，词库改了它不会报错、只是**静默不生效**（v3.14.0 踩过：
     改词库后 61 处引用全部失效）。这条把它常驻化。

跑法：python tests/check_v3_link.py [轮数，默认 120]
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import _boot  # noqa: E402

R = _boot.load("anima_v4_rules")
L = _boot.load("anima_v4_link")

POOLS = os.path.join(PLUGIN, "presets", "anima_v4_pools.json")
SCENES = os.path.join(PLUGIN, "presets", "anima_v4_scenes.json")

PASS, FAIL = [], []


def ck(name, ok, note=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'OK' if ok else '!!'}] {name}" + (f"  {note}" if note and not ok else ""))


def _field_values(pools):
    """{字段 key: 该字段全部取值}。"""
    m = {}
    for s in pools["sections"]:
        for f in s["fields"]:
            m[f["key"]] = {en for _zh, en in (f.get("opts") or [])}
    return m


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    pools = json.load(open(POOLS, encoding="utf-8"))
    vals = _field_values(pools)

    # ── ① 三张表与词库一致 ────────────────────────────────────────
    print("── ① 联动表 ↔ 词库一致性 ──")
    bad = []
    for k, v in L.ACT_POS_BAN.items():
        if k not in vals.get("n_act", set()):
            bad.append(f"ACT_POS_BAN 键 `{k}` 不在 n_act")
        for x in v:
            if x not in vals.get("n_pos", set()):
                bad.append(f"ACT_POS_BAN[{k}] 值 `{x}` 不在 n_pos")
    ck("体位配对表：键与取值都真实存在", not bad, "; ".join(bad[:4]))
    ck("体位配对表非空", len(L.ACT_POS_BAN) >= 10, str(len(L.ACT_POS_BAN)))

    atoms = {t.strip() for en in vals.get("emotion", set()) for t in en.split(",")}
    bad = []
    for k, m in L.EMOTION_BAN.items():
        if k not in atoms:
            bad.append(f"EMOTION_BAN 键 `{k}` 不在 emotion")
        for fk, s2 in m.items():
            if fk not in ("eye_gaze", "mouth"):
                bad.append(f"EMOTION_BAN[{k}] 的字段 `{fk}` 不是 eye_gaze/mouth")
            for x in s2:
                if x not in vals.get(fk, set()):
                    bad.append(f"EMOTION_BAN[{k}/{fk}] 值 `{x}` 不存在")
    ck("表情配套表：键与取值都真实存在", not bad, "; ".join(bad[:4]))
    ck("表情配套表非空", len(L.EMOTION_BAN) >= 10, str(len(L.EMOTION_BAN)))

    bad = []
    for th, m in L.THEME_WEIGHT.items():
        for fk, o in m.items():
            for x in o:
                if x not in vals.get(fk, set()):
                    bad.append(f"THEME_WEIGHT[{th}/{fk}] `{x}`")
    for th, m in L.THEME_BAN.items():
        for fk, s2 in m.items():
            for x in s2:
                if x not in vals.get(fk, set()):
                    bad.append(f"THEME_BAN[{th}/{fk}] `{x}`")
    ck("场景倾向表：加权与剔除的取值都真实存在", not bad, "; ".join(bad[:4]))

    # ── ② 场景主题覆盖 ────────────────────────────────────────────
    print("\n── ② place 主题覆盖 ──")
    places = vals.get("place", set())
    missing = sorted(places - set(L.PLACE_THEME))
    extra = sorted(set(L.PLACE_THEME) - places)
    ck("每个 place 都能查到主题（漏了 = 该场景联动静默失效）", not missing,
       str(missing[:6]))
    ck("主题表没有词库里不存在的冗余 place", not extra, str(extra[:6]))
    ck("七个主题都至少被一个 place 用到",
       set(L.PLACE_THEME.values()) == set(L.THEME_WEIGHT.keys()),
       str(sorted(set(L.PLACE_THEME.values()) ^ set(L.THEME_WEIGHT.keys()))))

    # ── ⑦ 场景搭配库引用完整性（先查，后面要用它抽 place）───────────
    print("\n── ③ 场景搭配库字段引用完整性 ──")
    scenes = json.load(open(SCENES, encoding="utf-8"))["scenes"]
    bad = collections.Counter()
    for x in scenes:
        for k, v in (x.get("tags") or {}).items():
            if k in vals and v not in vals[k]:
                bad[(k, v)] += 1
    ck("场景库 87 条预设的字段取值全部存在于词库", not bad,
       str(dict(list(bad.items())[:4])))

    # ── ④ 运行时零矛盾 ────────────────────────────────────────────
    print(f"\n── ④ 运行时矛盾（{rounds} 轮 × hardcore/extreme）──")
    # ⚠️⚠️ 判据必须用**表本身**，不能用 `L.bans_for()`。
    #    拿被测函数自证的话，表被破坏时"引擎不拦"和"测试不查"会一起发生，
    #    断言照样全绿 —— v3.5.0 踩过一模一样的坑（同源夹具自证）。
    pos_bad = collections.Counter()
    mouth_bad = collections.Counter()
    gaze_bad = collections.Counter()
    for lv in ("hardcore", "extreme"):
        for s in range(rounds):
            st = R.draw(level=lv, seed=s * 7919 + 11)["state"]
            act = str(st.get("n_act") or "")
            pos = str(st.get("n_pos") or "")
            if act and pos and pos in L.ACT_POS_BAN.get(act, set()):
                pos_bad[(act, pos)] += 1
            for _t in str(st.get("emotion") or "").split(","):
                _t = _t.strip()
                if not _t:
                    continue
                for fk, bag in (("mouth", mouth_bad), ("eye_gaze", gaze_bad)):
                    v = str(st.get(fk) or "")
                    if v and v in (L.EMOTION_BAN.get(_t) or {}).get(fk, set()):
                        bag[(_t, v)] += 1
    ck(f"n_act × n_pos 零矛盾（{rounds * 2} 轮）", not pos_bad,
       str(pos_bad.most_common(3)))
    ck(f"emotion × 嘴部 零矛盾（{rounds * 2} 轮）", not mouth_bad,
       str(mouth_bad.most_common(3)))
    ck(f"emotion × 眼神 零矛盾（{rounds * 2} 轮）", not gaze_bad,
       str(gaze_bad.most_common(3)))

    # ── ⑤ place 预抽 ──────────────────────────────────────────────
    print("\n── ⑤ 场景预抽（联动的执行前提）──")
    got = sum(1 for s in range(rounds)
              if R.draw(level="sfw", seed=3000 + s)["state"].get("place"))
    ck(f"place 能被抽到（{got}/{rounds} 轮）", got > rounds // 4, str(got))
    st = R.draw(level="sfw", seed=1, locks={"place"})["state"]
    ck("锁定 place 时不被预抽写入", not st.get("place"), repr(st.get("place")))
    st = R.draw(level="sfw", seed=1, forced={"place": "poolside"})["state"]
    ck("forced place 生效", st.get("place") == "poolside", repr(st.get("place")))

    # ── ⑥ 场景加权 + 硬剔除真的生效 ───────────────────────────────
    print(f"\n── ⑥ 场景倾向（{rounds} 轮对照）──")
    swim = {
        "one-piece swimsuit", "bikini", "white bikini", "competitive swimsuit",
        "school swimsuit", "competition school swimsuit", "old school swimsuit",
        "new school swimsuit", "sports bikini", "micro bikini", "halterneck",
        "bikini top only", "bath towel",
    }
    banned_in_water = {}
    for fk in ("outfit", "top", "bottom"):
        banned_in_water[fk] = L.THEME_BAN["water"].get(fk, set())

    # ⚠️ 关掉「法典验证场景」段：**场景搭配库的预设会写 place**（它是一键搭配，
    #    优先级高于随机与 forced），把 forced 的 place 覆盖掉。
    #    不关的话统计会串台 —— 实测「alley + 大衣」这种完全合法的组合
    #    被误判成"泳池边违和"（8 次假阳性）。这与 v3.14.0 测"反推"之前
    #    先剔掉场景 extra 是同一个思路：**先把干扰源关掉再测目标**。
    no_canon = [sid for sid in R.section_ids() if sid != "canon"]

    def _place_of(st):
        return L.PLACE_THEME.get(str(st.get("place") or ""), "")

    def sample(forced=None, n=80):
        hit_o = tot_o = viol = 0
        for s in range(n):
            st = R.draw(level="sfw", seed=5000 + s, forced=forced,
                        enabled_sections=no_canon)["state"]
            o = st.get("outfit", "")
            if o:
                tot_o += 1
                if o in swim:
                    hit_o += 1
            if _place_of(st) != "water":
                continue          # 双保险：只在真正的水上场景里查违和
            for fk, bag in banned_in_water.items():
                if st.get(fk) and st.get(fk) in bag:
                    viol += 1
        return hit_o, tot_o, viol

    a_hit, a_tot, viol = sample(forced={"place": "poolside"})
    b_hit, b_tot, _ = sample(forced={"place": "classroom"})
    rate_a = a_hit / max(a_tot, 1)
    rate_b = b_hit / max(b_tot, 1)
    ck("★ 泳池边：抽到整套服装时泳装占比显著高于教室",
       rate_a > rate_b * 2 and rate_a > 0.35,
       f"poolside {a_hit}/{a_tot}={rate_a:.0%} vs classroom {b_hit}/{b_tot}={rate_b:.0%}")
    ck("★ 泳池边：违和服装（厚外套/和服/长裤）一次都不出现", viol == 0, f"{viol} 次")

    # ★ 兜底路径：**不关 canon 段**、place 完全随机跑一轮，按「实际 place」判违和。
    #   这一条覆盖的是"抽取之后才被改写"的路径 —— 场景搭配库的预设会写
    #   place / outfit / top，那批矛盾抽取时的候选池过滤**看不到**，
    #   全靠 sanitize 在最后兜住（见 rules.sanitize 的联动消解一节）。
    viol2 = 0
    for s in range(80):
        st = R.draw(level="sfw", seed=9000 + s)["state"]
        th = _place_of(st)
        if not th:
            continue
        for fk, bag in (L.THEME_BAN.get(th) or {}).items():
            if st.get(fk) and st.get(fk) in bag:
                viol2 += 1
    ck("★ 全场景随机 80 轮：没有任何「场景 × 服装」违和（sanitize 兜底）",
       viol2 == 0, f"{viol2} 次")

    # 场景 × 姿势：用「该场景 vs 不相关场景」对照，而不是拿绝对值卡阈值 ——
    # 姿势本身还受 base_prob 与密度自适应影响，绝对值会随这些参数漂。
    def pose_rate(place, want, n=80):
        hit = tot = 0
        for s in range(n):
            st = R.draw(level="sfw", seed=7000 + s, forced={"place": place},
                        enabled_sections=no_canon)["state"]
            p = st.get("pose_base", "")
            if p:
                tot += 1
                if p in want:
                    hit += 1
        return hit / max(tot, 1)

    lying = {"on side", "on back", "on stomach"}
    sitting = {"sitting", "head rest"}
    r_bed = pose_rate("bedroom", lying)
    r_lib_lying = pose_rate("library", lying)
    r_lib = pose_rate("library", sitting)
    r_bed_sitting = pose_rate("bedroom", sitting)
    # ⚠️ 阈值只卡"加权确实改变了分布"（相对关系），不卡绝对强度：
    #    姿势字段本身有 ~35% 概率整段不出现（base_prob + 密度自适应），
    #    绝对值会随那两个参数漂，拿它当阈值会做出很脆的测试。
    ck("★ 卧室：躺姿占比显著高于图书馆（场景 × 姿势加权生效）",
       r_bed > r_lib_lying * 2 and r_bed > 0.10,
       f"bedroom {r_bed:.0%} vs library {r_lib_lying:.0%}")
    ck("★ 图书馆：坐姿占比显著高于卧室",
       r_lib > r_bed_sitting * 1.5 and r_lib > 0.25,
       f"library {r_lib:.0%} vs bedroom {r_bed_sitting:.0%}")

    print("\n" + "=" * 62)
    print(f"[check_v3_link] 通过 {len(PASS)} / 失败 {len(FAIL)}")
    if FAIL:
        print("失败：[" + "] [".join(FAIL) + "]")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
