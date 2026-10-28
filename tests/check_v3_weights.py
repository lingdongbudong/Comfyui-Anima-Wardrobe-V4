# -*- coding: utf-8 -*-
"""三层权重语义 + 健壮性基线。

权重是本插件相对源脚本最大的增强（源脚本只有一个写死的
`Math.random()<0.65`），所以它的语义必须有回归钉住：

  ① 字段权重 0        → 该字段永不出现
  ② 字段权重 3.0（上限）→ 该字段必定出现
  ③ 选项权重 0        → 该选项永不出现
  ④ 选项权重把其它项归零 + 字段权重 3.0 → 结果唯一确定
  ⑤ 非法 / 空 / 缺字段的 JSON → 一律当默认，不抛异常
  ⑥ 引用不存在的段/字段/选项 → **不报错**，但必须给出告警
     （不报错是为了老工作流能跑；给告警是为了用户知道权重没生效）
  ⑦ 段权重 0          → 整段关闭
  ⑧ appearance_follow 关闭后，角色不再覆盖发色/瞳色权重

跑法：python tests/check_v3_weights.py
"""
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _boot  # noqa: E402

R = _boot.load("anima_v4_rules")

FAILS = []


def ck(name, cond, note=""):
    if cond:
        print(f"  [OK] {name}")
    else:
        print(f"  [!!] {name}  {note}")
        FAILS.append(name)


def main():
    print("── ① 字段权重 0 = 永不出现 ──")
    w = R.parse_weights('{"fields":{"outfit":0,"place":0,"hair_color":0}}')
    bad = []
    for s in range(30):
        st = R.draw(level="suggestive", seed=s, weights=w)["state"]
        for k in ("outfit", "place", "hair_color"):
            if st.get(k):
                bad.append((k, st[k]))
    ck("字段权重 0 关得掉", not bad, str(bad[:3]))

    print("── ② 字段权重 3.0 = 必定出现 ──")
    w = R.parse_weights('{"fields":{"place":3.0}}')
    miss = [s for s in range(30)
            if not R.draw(level="sfw", seed=s, weights=w)["state"].get("place")]
    ck("字段权重 3.0 必现", not miss, f"缺 {len(miss)} 次")

    print("── ③ + ④ 选项权重：唯一确定 ──")
    all_colors = [en for _zh, en in
                  R.field_by_key("hair_color")[1]["opts"]]
    opt = {c: 0 for c in all_colors}
    opt["white hair"] = 1
    w = R.parse_weights(
        '{"fields":{"hair_color":3.0},"options":{"hair_color":'
        + _dumps(opt) + '}}')
    # ⚠️ 必须关掉外貌对齐再测。
    #    v3.2.0 起角色**必定**会被抽到（角色权重已取消 + 未选则从角色库
    #    随机抽 1 位），而外貌对齐会把发色改成那个角色的官方发色 ——
    #    那样测的就不是选项权重了。
    #    这条用例以前是靠 `"role": 0` 把角色关掉来隔离变量的，
    #    角色权重取消后那个办法失效，改用 appearance_follow=False。
    got = {R.draw(level="sfw", seed=s, weights=w,
                  appearance_follow=False)["state"].get("hair_color")
           for s in range(25)}
    ck("其余选项归零 → 结果唯一（关闭外貌对齐）", got == {"white hair"}, str(got))

    print("── ⑤ 非法输入不炸 ──")
    cases = ["", None, "{bad json", "[1,2,3]", '"字符串"', "{}",
             '{"fields":null}', '{"fields":{"x":"abc"}}',
             '{"options":{"hair_color":{"black hair":"NaN"}}}']
    ok = True
    for c in cases:
        try:
            w = R.parse_weights(c)
            R.draw(level="sfw", seed=1, weights=w)
        except Exception as exc:
            ok = False
            print(f"      {c!r} 抛异常：{exc}")
    ck("空/非法/错类型 JSON 全部当默认", ok)

    # base_prob = 0 / 负数 的兜底。
    # ⚠️ 历史脏数据：v3.1.0 的「采用这条」在那一栏为空时写 Number("") === 0，
    #    而 0 意味着**所有可选字段都不抽**，出图只剩必填项。必须救回默认值。
    for bad in (0, -1, 0.0, None, "abc"):
        st = R.draw(level="sfw", seed=3, base_prob=bad)["state"]
        picked = sum(1 for k, v in st.items()
                     if not str(k).startswith("_") and v)
        if picked < 5:
            ck(f"base_prob={bad!r} 兜底成默认值", False,
               f"只抽到 {picked} 个字段")
            break
    else:
        ck("base_prob 为 0/负数/非法时兜底成默认值（不是不抽）", True)

    print("── ⑥ 引用不存在的项：不报错，但要有告警 ──")
    w = R.parse_weights(
        '{"sections":{"nope":2},"fields":{"alsonope":2},'
        '"options":{"hair_color":{"rainbow hair":2}}}')
    warns = R.validate_weights(w)
    ck("给出 3 条告警", len(warns) == 3, str(warns))
    res = R.draw(level="sfw", seed=5, weights=w)
    ck("非法权重不阻断抽取", bool(res["text"]))
    ck("告警进了报告", any("不存在" in n for n in res["notes"]), str(res["notes"][:3]))

    print("── ⑦ 段权重 0 = 整段关闭 ──")
    w = R.parse_weights('{"sections":{"hair":0,"makeup":0}}')
    bad = []
    for s in range(20):
        st = R.draw(level="sfw", seed=s, weights=w)["state"]
        for k in ("hair_len", "hair_color", "hair_curl", "hair_tie",
                  "hair_bangs", "hair_fx", "hair_acc", "makeup", "nails"):
            if st.get(k):
                bad.append(k)
    ck("段关闭彻底", not bad, str(sorted(set(bad))))

    print("── ⑧ 角色外貌对齐开关 ──")
    all_colors = [en for _zh, en in R.field_by_key("hair_color")[1]["opts"]]
    opt = {c: 0 for c in all_colors}
    opt["white hair"] = 1
    base = ('{"fields":{"hair_color":3.0},"options":{"hair_color":'
            + _dumps(opt) + '}}')
    w = R.parse_weights(base)
    got = {R.draw(level="sfw", seed=s, weights=w, appearance_follow=False,
                  force_role="hakurei reimu, touhou")["state"].get("hair_color")
           for s in range(5)}
    ck("关闭后权重说了算", got == {"white hair"}, str(got))
    got2 = {R.draw(level="sfw", seed=s, weights=w, appearance_follow=True,
                   force_role="hakurei reimu, touhou")["state"].get("hair_color")
            for s in range(5)}
    ck("开启后官方发色覆盖", got2 == {"black hair"}, str(got2))

    print("── ⑨ 权重计数（面板 🎯 徽标的数据源）──")
    st = R.weight_stats(R.parse_weights(
        '{"sections":{"hair":0},"fields":{"outfit":2},'
        '"options":{"hair_color":{"black hair":2,"pink hair":0}}}'))
    ck("段1/字段1/选项2 = 4", st["total"] == 4, str(st))

    print("── ⑩ 锁定字段 × 法典场景预设（v3.8.0 修）──")
    # ⚠️ 修之前：apply_preset 只认档位与权重，**不看 locks** ——
    #    于是"锁住 n_act 让它留给上游"会被预设写回去，用户看到的是
    #    "我锁了它还改"。预设是**自动填充**，必须与其他两条自动路径
    #    （角色外貌对齐、按人数清字段）一样尊重权重/锁定。
    # c8 = depth 口交侧视：n_act=deepthroat, n_cum=x-ray, viewpoint=from side
    c8 = R.canon().get("c8") or {}
    base = dict(level="hardcore", seed=11, forced={"n_canon": "c8"})
    st_free = R.draw(**base)["state"]
    ck("不锁定时预设照常填充 n_act",
       bool(c8.get("n_act")) and st_free.get("n_act") == c8.get("n_act"),
       str(st_free.get("n_act")))
    locked = {"n_act", "n_cum"}
    st_lock = R.draw(locks=locked, **base)["state"]
    hit = sorted(k for k in locked if st_lock.get(k))
    ck("锁定的字段不被预设写回", not hit, f"被写回：{hit}")
    ck("未锁定的字段照常填充（n_extra）", bool(st_lock.get("n_extra")))
    ck("预设 id 仍然写入（n_canon）", st_lock.get("n_canon") == "c8",
       str(st_lock.get("n_canon")))

    print()
    if FAILS:
        print(f"[check_v3_weights] 失败 {len(FAILS)} 项：{FAILS}")
        return 1
    print("[check_v3_weights] 通过：9 组语义全部符合预期")
    return 0


def _dumps(d):
    import json
    return json.dumps(d, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())
