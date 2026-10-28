# -*- coding: utf-8 -*-
"""场景档位分层基线（v3.40.0 新增）。

守五件事：

  ① **分层口径** —— `exact` 全是 `== lv`、`lower` 全是 `< lv`，两者并集等于原池；
     `lv=0` 原样返回（SFW 档池里本来就只有 L0）。

  ② **命中率** —— v3.42.0 起：`lv>=1` **锁档**（p=1.0，只在本档里抽，
     不再有低档兜底层），「有没有场景」由 `SCENE_APPEAR_P`（标定值 0.67）
     控制，对外承诺 `SCENE_TARGET_APPEAR = 60%`。见第 ⑦ 段。

  ③ **绝不越档** —— 抽到的场景档位恒 `<= lv`。分层只做减法，不做加法。

  ④ **显式套用不被改写** —— 面板「一键套用」是把目标权重写 3.0、其余置 0，
     分层**必须**让路，否则用户点的那条会被随机掉。

  ⑤ **SFW 档零漂移** —— `lv=0` 时骰子取任何值，输出逐字节相同。

跑法：python tests/check_v3_scenelevel.py [每档抽样轮数，默认 400]
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


def forced_weights():
    """面板随机路径的等价权重：n_canon 顶格（必抽），其余默认。"""
    w = R.empty_weights()
    w["fields"]["n_canon"] = 3.0
    return w


def scene_levels(rounds, lv):
    """按档位统计命中率。

    ⚠️ 种子用 `i*7919` **散开**，不能取 0..n：
       骰子是 `crc32(seed...)` 派的，0..199 这一段恰好有 56% 落在 <0.5 区间，
       会让「50% 命中」的断言凭空红掉（实测：0..199 = 56%，散开后 48%/51%）。
       换句话说那段区间是**抽样偏差**，不是实现错 —— 但基线不该建立在运气上。
    """
    w = forced_weights()
    c, tot = collections.Counter(), 0
    for s in range(rounds):
        pid = R.draw(level=lv, seed=s * 7919, weights=w,
                     base_prob=0.9)["state"].get("n_canon")
        if pid:
            tot += 1
            c[R.canon_level(pid)] += 1
    return c, tot


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    w = forced_weights()

    print("── ① 分层口径 ──")
    for lv in range(5):
        pool = R.eligible_options("n_canon", lv)
        exact = [it for it in pool if it[2] == lv]
        lower = [it for it in pool if it[2] < lv]
        ck(f"L{lv}：exact 全是 =={lv}、lower 全是 <{lv}",
           all(n == lv for _z, _e, n in exact) and all(n < lv for _z, _e, n in lower))
        ck(f"L{lv}：exact + lower 覆盖原池（{len(pool)} 条）",
           len(exact) + len(lower) == len(pool))
        print(f"       L{lv} 池 {len(pool)} = exact {len(exact)} + lower {len(lower)}")

    base0 = R.eligible_options("n_canon", 0)
    outs = [R.scene_level_layered(base0, 0, w, c) for c in (0.0, 0.5, 0.999999)]
    ck("LV0 原样返回（三次不同骰子给出同一份池子）",
       all(o[0] == base0 and o[1] is None for o in outs))

    print("\n── ② 命中率 ──")
    # 先测**机制本身**（纯函数，无抽样噪声）：骰子在 [0,1) 上均匀时，
    # 走「== lv」分支的占比必须**正好**等于 p。这条是硬不变量。
    for lv, want_p in ((1, R.SCENE_LEVEL_MATCH_P), (4, R.SCENE_LEVEL_MATCH_P_SMALL)):
        pool = R.eligible_options("n_canon", lv)
        n_exact = sum(1 for _z, _e, n in pool if n == lv)
        grid = 1000
        hit = 0
        for i in range(grid):
            got, _note = R.scene_level_layered(pool, lv, w, i / grid)
            if all(it[2] == lv for it in got):
                hit += 1
        ck(f"L{lv} 机制检验：1000 个均匀骰子中 {hit / grid:.1%} 走该档（p={want_p:.0%}）",
           abs(hit / grid - want_p) <= 0.005, f"{hit}/{grid}")
        ck(f"L{lv} 该档可用 {n_exact} 条，p 取对了吗",
           abs(R.scene_level_match_p(lv, n_exact) - want_p) < 1e-9)

    want = {1: R.SCENE_LEVEL_MATCH_P, 2: R.SCENE_LEVEL_MATCH_P,
            3: R.SCENE_LEVEL_MATCH_P, 4: R.SCENE_LEVEL_MATCH_P_SMALL}
    for lv in (1, 2, 3, 4):
        c, tot = scene_levels(rounds, lv)
        hit = c.get(lv, 0) / max(1, tot)
        ck(f"L{lv} 实抽命中率 {hit:.0%} ≈ 目标 {want[lv]:.0%}",
           abs(hit - want[lv]) <= 0.07, f"{dict(sorted(c.items()))} / {tot}")
    c, tot = scene_levels(rounds, 0)
    ck("LV0 仍然 100% 是 L0 场景（不因分层产生空池或跳档）",
       set(c) == {0}, str(dict(c)))

    print("\n── ③ 绝不越档 ──")
    over = []
    for lv in range(5):
        ww = forced_weights()
        for s in range(120):
            pid = R.draw(level=lv, seed=90000 + s, weights=ww, base_prob=0.9)["state"].get("n_canon")
            if pid and R.canon_level(pid) > lv:
                over.append((lv, pid, R.canon_level(pid)))
    ck("五档 600 抽零越档场景", not over, str(over[:4]))

    print("\n── ④ 显式套用不被改写 ──")
    # 取一条 manual_only（默认不进随机池，只能靠权重 3.0 进来）+ 一条普通场景
    manual = [s for s in R.scene_list() if s.get("manual_only")]
    ck("场景库里存在 manual_only 条目（否则本项测不到）", bool(manual))
    for case in (manual[0], [s for s in R.scene_list() if not s.get("manual_only")][0]):
        sid, slv = case["id"], int(case.get("level", 0))
        lv = max(slv, 2)  # 保证该条本身在本档合法
        ww = R.empty_weights()
        ww["fields"]["n_canon"] = 3.0
        ids = [en for _z, en in R.field_by_key("n_canon")[1]["opts"]] + \
              [x for _z, x, _n in R.scene_options(99, True)]
        ww["options"]["n_canon"] = {k: 0.0 for k in ids}
        ww["options"]["n_canon"][sid] = 3.0
        miss = [s for s in range(20)
                if R.draw(level=lv, seed=61000 + s, weights=ww,
                          base_prob=0.9)["state"].get("n_canon") != sid]
        ck(f"套用「{case.get('zh') or sid}」后 20 抽 20/20 命中（L{lv}）",
           not miss, f"miss={miss[:4]}")

    print("\n── ⑤ 报告可观测 ──")
    notes = set()
    for lv in (1, 4):
        for s in range(80):
            notes |= {n for n in R.draw(level=lv, seed=s, weights=forced_weights(),
                                        base_prob=0.9)["notes"]
                      if "场景档位匹配" in n}
    ck("报告里能看到分层命中/兜底说明", bool(notes), str(list(notes)[:2]))
    print("       例：" + (list(notes)[0] if notes else "—"))

    print("\n── ⑥ SFW 档零漂移 ──")
    # 分层的唯一入口是 `scene_level_layered`；`lv<=0` 时它直接原样返回，
    # 所以"它一次都没有被触发"就等于"池子与改动前一致"。
    # （另做过一次真 A/B：把改动前的 rules.py 作为平行模块加载，sfw 档 60/60 逐字节相同。）
    hits = []
    for i in range(200):
        r = R.draw(level="sfw", seed=i)
        if any("场景档位匹配" in n for n in r["notes"]):
            hits.append(i)
    ck("SFW 档 200 抽一次都没触发分层", not hits, str(hits[:5]))
    ck("模块级没有残留的 _scene_coin（它应是 draw 内的局部量）",
       not hasattr(R, "_scene_coin"))
    ck("lv=0 的 p 恒为 0（即使误调用也不会走该档分支）",
       R.scene_level_match_p(0, 82) == 0.0)

    print("\n── ⑦ 锁档：抽到的场景等级 == 所选等级（v3.42.0 起）──")
    # ⚠️ 与 ② 的区别：②用的是 `n_canon` 字段权重顶格 3.0（面板"必抽"路径），
    #    ⑦ 用**默认权重**走真实随机路径 —— 这才是用户实际出图时的那条路。
    ck("p 在 lv≥1 时恒为 1.0（锁档，不再留低档兜底层）",
       all(R.scene_level_match_p(lv, n) == 1.0
           for lv, n in ((1, 38), (2, 21), (3, 37), (4, 10))))
    ck("出现率常数 SCENE_APPEAR_P 在 (0,1) 内",
       0.0 < R.SCENE_APPEAR_P < 1.0, str(R.SCENE_APPEAR_P))
    for lv in (1, 2, 3, 4):
        c, tot = collections.Counter(), 0
        appear = 0
        for s in range(rounds):
            pid = R.draw(level=lv, seed=s * 7919 + 13,
                         base_prob=0.8)["state"].get("n_canon")
            tot += 1
            if pid:
                appear += 1
                c[R.canon_level(pid)] += 1
        same = c.get(lv, 0) / max(1, appear)
        lower = sum(v for k, v in c.items() if k < lv)
        ck(f"L{lv} 抽到的场景 {same:.1%} 正好是本档、低于本档 {lower} 条",
           same == 1.0 and lower == 0, str(dict(sorted(c.items()))))
        # ⚠️ 容差比"目标"宽，因为出现率**依赖权重与角色配置**：
        #    这里用 `empty_weights()`（标签数少、淘汰少）→ 实测 ~68%；
        #    用户工作流（options 置零 + 收藏角色 + 巨乳）→ 实测 59–64%。
        #    这条断言只守"既不回到 v3.42 之前的 ~30%，也没有变成 100%"。
        ck(f"L{lv} 场景出现率 {appear / tot:.0%} 落在 50–78%（目标 {R.SCENE_TARGET_APPEAR:.0%}，"
           "实际值随权重配置浮动）",
           0.50 <= appear / tot <= 0.78, f"{appear}/{tot}")
    # SFW 档保持"可缺席"，否则会与旧版输出全等这条纪律冲突
    l0 = sum(1 for s in range(rounds)
             if R.draw(level=0, seed=s * 7919 + 13,
                       base_prob=0.8)["state"].get("n_canon")) / rounds
    ck(f"L0 仍是「可缺席」（{l0:.0%} < 60%），不套用 60% 规则",
       l0 < 0.6, f"{l0:.0%}")

    print()
    if FAIL:
        print(f"[check_v3_scenelevel] 失败 {len(FAIL)} 项：{FAIL}")
        return 1
    print(f"[check_v3_scenelevel] 通过 {len(PASS)} 项："
          "分层口径 / 命中率 / 不越档 / 显式优先 / 可观测 / 零漂移")
    return 0


if __name__ == "__main__":
    sys.exit(main())
