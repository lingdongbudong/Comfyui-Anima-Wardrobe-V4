# -*- coding: utf-8 -*-
"""高等级保底基线（v3.41.0 新增）。

守五件事：

  ① **每档都真的到位** —— 选 L1–L4 抽 N 轮，交付的 `real_level` 必须**全部**
     等于所选档。这是本功能唯一的硬承诺，不接受"概率上差不多"。
     （改前实测：L1 掉 24%、L2 13%、L3 39%、L4 59%）

  ② **不越档** —— 保底只补"正好本档"的选项，绝不顺手补一条更高的。

  ③ **SFW 档零漂移** —— lv=0 一次都不触发，且输出与改动前逐字节相同。

  ④ **载体合法** —— 锚点必须同时过三关：`tag_level==lv`（撑得起）、
     `option_level<=lv`（不被 F15/回滚判越档）、没被 `bans_for` 禁掉。
     这是踩过的坑：`bent over` 判定表判 1、段下限抬到 2，只在 L1 补它会被
     超档回滚当场 `state.pop()` 掉 —— 补了等于白补。

  ⑤ **人数相容** —— solo 场景不拿 `n_act` / `n_cum` 当"已达标"的证据，
     锚点也不给 solo 写需要伴侣的动作；多人模式只清一对一字段。

跑法：python tests/check_v3_levelfloor.py [每档抽样轮数，默认 300]
"""
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import _boot  # noqa: E402

R = _boot.load("anima_v4_rules")

PASS, FAIL = [], []


def ck(name, ok, note=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'OK' if ok else '!!'}] {name}" + (f"  {note}" if note and not ok else ""))


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 300

    print("── ① 每档都真的到位 ──")
    for lv in range(5):
        c = collections.Counter()
        for s in range(rounds):
            c[R.draw(level=lv, seed=s * 7919)["report"]["real_level"]] += 1
        ck(f"L{lv} 全部落在所选档（{rounds} 抽）", set(c) == {lv}, str(dict(c)))
    ck("L0 一次都没触发保底",
       not any("保底" in n for n in
               R.draw(level="sfw", seed=12345)["notes"]))

    print("\n── ② 不越档 ──")
    over = []
    for lv in range(5):
        for s in range(120):
            r = R.draw(level=lv, seed=90000 + s)
            if r["report"]["real_level"] > lv:
                over.append((lv, r["report"]["real_level"]))
    ck("五档 600 抽零越档", not over, str(over[:4]))

    print("\n── ③ 锚点合法性（逐档逐字段枚举）──")
    bad = []
    for lv in (1, 2, 3, 4):
        for key in R.LEVEL_FLOOR_ORDER:
            for _zh, en in R.level_floor_candidates(key, lv, {"count": "1girl, solo"}):
                if R.tag_level(en) != lv:
                    bad.append((lv, key, en, "tag_level"))
                if R.option_level(key, en) > lv:
                    bad.append((lv, key, en, "option_level"))
    ck("所有锚点都同时满足两个档位口径", not bad, str(bad[:4]))

    print("\n── ④ 人数相容 ──")    # solo：n_act / n_cum 不计入有效档位（一对一做不了）
    solo_state = {"count": "1girl, solo", "n_act": "missionary"}
    ck("solo + missionary 不算达标证据", R.effective_level(solo_state) == 0,
       str(R.effective_level(solo_state)))
    solo_ok = {"count": "1girl, solo", "n_act": "masturbation"}
    ck("solo + masturbation 仍然算（自指类放行）",
       R.effective_level(solo_ok) == R.tag_level("masturbation"),
       str(R.effective_level(solo_ok)))
    couple = {"count": "1girl, 1boy, hetero", "n_act": "missionary"}
    ck("一男一女 + missionary 计入档位",
       R.effective_level(couple) == R.tag_level("missionary"),
       str(R.effective_level(couple)))
    ck("solo 的锚点里没有需要伴侣的动作",
       not [1 for _z, en in R.level_floor_candidates("n_act", 3, solo_state)])

    # 三人以上才成立的元素：solo / 一男一女都不许（实测 extreme 曾补出 solo+threesome）
    for cnt in ("1girl, solo", "1girl, 1boy, hetero"):
        st = {"count": cnt}
        bad = [en for k in ("n_theme", "n_cum")
               for _z, en in R.level_floor_candidates(k, 4, st)
               if en in R.GROUP_ONLY_TAGS]
        ck(f"「{cnt}」的锚点不含三人专属元素", not bad, str(bad[:3]))
    ck("三人以上时锚点允许三人专属元素",
       any(en in R.GROUP_ONLY_TAGS
           for _z, en in R.level_floor_candidates("n_theme", 4,
                                                  {"count": "multiple girls, orgy"})))
    leak = []
    for lv in range(5):
        for s in range(150):
            r = R.draw(level=lv, seed=50000 + s)
            st = r["state"]
            if R.count_is_group(str(st.get("count") or "")):
                continue
            for k in ("n_theme", "n_cum"):
                v = str(st.get(k) or "").strip().lower()
                if v in R.GROUP_ONLY_TAGS:
                    leak.append((lv, st.get("count"), k, v))
    ck("750 抽零「人数不够却写三人元素」", not leak, str(leak[:3]))

    # v3.41.2：solo 不抽"需要伴侣"的动作（实拍 7/50 张踩到）
    leaks = []
    for lv in (2, 3, 4):
        for s in range(150):
            st = R.draw(level=lv, seed=60000 + s)["state"]
            if R.count_has_partner(str(st.get("count") or "")):
                continue
            for k in R.PARTNER_GATED_FIELDS:
                v = str(st.get(k) or "").strip().lower()
                if v and v not in R.SOLO_OK_PARTNER_OPTS:
                    leaks.append((lv, st.get("count"), k, v))
    ck("450 抽零「solo + 需要伴侣的动作」", not leaks, str(leaks[:3]))
    solo3 = [R.draw(level=3, seed=40000 + s, forced={"count": "1girl, solo"})["state"]
             for s in range(30)]
    ck("强制 solo 时 n_act 只剩自指类或为空",
       all((not s.get("n_act")) or str(s["n_act"]).lower() in R.SOLO_OK_PARTNER_OPTS
           for s in solo3),
       str({s.get("n_act") for s in solo3}))
    couple_ok = sum(1 for s in range(30)
                    if R.draw(level=3, seed=40200 + s,
                              forced={"count": "1girl, 1boy, hetero"})["state"].get("n_act"))
    ck("一男一女时 n_act 仍会正常抽到（没被 solo 过滤误伤）",
       couple_ok > 0, f"{couple_ok}/30")

    # 多人：一对一字段被清，个人状态与主题保留
    multi = R.draw(level=4, seed=777, forced={"count": "multiple girls, orgy"})
    ck("多人模式下一对一字段为空",
       not any(multi["state"].get(k) for k in ("n_act", "n_pos", "n_cum")),
       str({k: multi["state"].get(k) for k in ("n_act", "n_pos", "n_cum")}))
    ck("多人模式下仍然达标 L4", multi["report"]["real_level"] == 4,
       str(multi["report"]["real_level"]))

    print("\n── ⑤ 无载体时如实报告 ──")
    # 把所有载体都锁死 → 必须走"无可用载体"分支，而不是静默降级
    import random as _random
    all_locks = set(R.LEVEL_FLOOR_ORDER)
    notes = R.ensure_level_floor({"count": "1girl, solo"}, 4,
                                 R.empty_weights(), all_locks, "",
                                 _random.Random(1))
    ck("全部载体被锁时给出「无可用载体」", bool(notes) and "无可用载体" in notes[0],
       str(notes))

    print()
    if FAIL:
        print(f"[check_v3_levelfloor] 失败 {len(FAIL)} 项：{FAIL}")
        return 1
    print(f"[check_v3_levelfloor] 通过 {len(PASS)} 项："
          "到位率 / 不越档 / 锚点合法 / 人数相容 / 如实报告")
    return 0


if __name__ == "__main__":
    sys.exit(main())
