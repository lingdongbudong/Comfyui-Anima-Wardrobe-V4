# -*- coding: utf-8 -*-
"""上肢动作单槽基线（v3.39.0 新增）。

守四件事：

  ① **表本身是对的** —— `anima_v4_link.HAND_SLOT` 里每个标签都必须是该字段
     词库里的**逐字原文**。写错不会报错、只会静默失效，所以只能靠断言拦。

  ② **三个字段都被覆盖** —— `arms_hands` 全 20 项、`pose_risque` 14 项、
     `pose_base` 3 项。少登记一项就漏一条冲突路径。

  ③ **实抽零冲突** —— 各档抽样若干轮，成品里上肢标签必须 ≤1 条。
     v3.39.0 之前实测 sfw 2.5% / 擦边 14.5% / 成人 13.0% 同时出现两条。

  ④ **手部动作不许整体消失** —— 修冲突最容易踩的坑是"过滤把整个字段杀掉"：
     `arms_hands` 一旦被剔光，画面就没有手部指令，手位交回模型自己猜。
     所以既要零冲突，也要命中率不塌。

  ⑤ **显式优先** —— 场景/预设写死的那一条必须赢过随机那一条（哪怕优先级更低）。

跑法：python tests/check_v3_hands.py [每档抽样轮数，默认 200]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import _boot  # noqa: E402

R = _boot.load("anima_v4_rules")
L = _boot.load("anima_v4_link")

PASS, FAIL = [], []


def ck(name, ok, note=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'OK' if ok else '!!'}] {name}" + (f"  {note}" if note and not ok else ""))


def _hand_hits(state: dict):
    """state 里所有命中的上肢标签 → [(字段, 标签)]。"""
    out = []
    for fk in L.HAND_ORDER:
        for t in (state.get(fk) or "").split(","):
            t = t.strip()
            if t in (L.HAND_SLOT.get(fk) or ()):
                out.append((fk, t))
    return out


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    d = json.load(open(os.path.join(PLUGIN, "presets", "anima_v4_pools.json"),
                       encoding="utf-8"))
    fields = {f["key"]: f for s in d["sections"] for f in s["fields"]}

    print("── ① 表里的标签必须是词库原文 ──")
    unknown = []
    for fk, slot in L.HAND_SLOT.items():
        opts = {e for _z, e in (fields.get(fk, {}).get("opts") or [])}
        if not opts:
            unknown.append((fk, "<字段不存在>"))
            continue
        for t in sorted(slot):
            if t not in opts:
                unknown.append((fk, t))
    ck("HAND_SLOT 的每个标签都真实存在于对应字段", not unknown, str(unknown[:6]))

    print("\n── ② 三个字段的覆盖 ──")
    ck("pose_base 的 3 个手部项全部登记",
       L.HAND_SLOT.get("pose_base") == {"arms at sides", "hands on own knees",
                                        "head rest"},
       str(sorted(L.HAND_SLOT.get("pose_base") or ())))
    n_ah = len(L.HAND_SLOT.get("arms_hands") or ())
    n_pr = len(L.HAND_SLOT.get("pose_risque") or ())
    ck("arms_hands 全 20 项登记（整个字段都是手部动作）", n_ah == 20, str(n_ah))
    ck("arms_hands 登记集 == 字段全部选项",
       {e for _z, e in fields["arms_hands"]["opts"]} == L.HAND_SLOT["arms_hands"])
    ck("pose_risque 14 项登记（另 8 项是躯干/腿，不算手）", n_pr == 14, str(n_pr))
    # n_state（脱卸程度）里有 4 个值与 pose_risque 撞名，同样占手。
    # 只收这 4 个：它另外 13 项是纯服装状态（半脱 / 滑落 / 敞开），与手无关。
    ck("n_state 只登记 4 个与 pose_risque 撞名的值",
       L.HAND_SLOT.get("n_state") == {"shirt lift", "dress lift",
                                      "clothes pull", "undressing"},
       str(sorted(L.HAND_SLOT.get("n_state") or ())))
    ck("n_state 的撞名值必须真实存在于 n_state 词库",
       all(v in {e for _z, e in fields["n_state"]["opts"]}
           for v in L.HAND_SLOT["n_state"]))
    ck("n_state 优先级最低（服装状态让位给姿势字段）",
       L.HAND_PRIORITY["n_state"] < min(L.HAND_PRIORITY[k]
                                        for k in ("arms_hands", "pose_risque",
                                                  "pose_base")))
    ck("HAND_ORDER 与 HAND_PRIORITY 同序（高→低）",
       list(L.HAND_ORDER) == sorted(L.HAND_PRIORITY, key=L.HAND_PRIORITY.get,
                                    reverse=True),
       str(L.HAND_ORDER))

    print("\n── ③ 实抽：零冲突 ──")
    for lv_name in ("sfw", "suggestive", "explicit", "hardcore"):
        bad, tot, sample = 0, 0, []
        for i in range(rounds):
            st = R.draw(level=lv_name, seed=i)["state"]
            tot += 1
            hits = _hand_hits(st)
            if len(hits) > 1:
                bad += 1
                if len(sample) < 3:
                    sample.append((i, hits))
        ck(f"{lv_name} 档 {rounds} 轮零上肢冲突", bad == 0,
           f"{bad}/{tot}，例：{sample}")

    print("\n── ④ 手部动作不缺席（过滤没把字段杀掉）──")
    hit_ah, hit_any = 0, 0
    for i in range(rounds):
        st = R.draw(level="sfw", seed=50000 + i)["state"]
        hits = _hand_hits(st)
        if hits:
            hit_any += 1
        if any(fk == "arms_hands" for fk, _t in hits):
            hit_ah += 1
    rate_ah = hit_ah / max(1, rounds)
    rate_any = hit_any / max(1, rounds)
    # v3.39.0 实测：sfw 档 arms_hands 命中 67%（修复前 67%，过滤后不变）。
    # 下界取 0.45 留足抖动余量，但能拦住"整字段被杀"这种塌方。
    ck(f"SFW 档 arms_hands 命中率 ≥ 45%（实测 {rate_ah:.0%}）", rate_ah >= 0.45)
    ck(f"SFW 档有手部动作的样本 ≥ 50%（实测 {rate_any:.0%}）", rate_any >= 0.50)

    print("\n── ⑤ 裁决口径：显式 > 优先级 ──")
    st = {"arms_hands": "v", "pose_risque": "skirt pull"}
    ck("无显式时 arms_hands 赢", L.hand_winner(dict(st)) == "arms_hands",
       L.hand_winner(dict(st)))
    st2 = dict(st)
    st2["_preset_fields"] = ["pose_risque"]
    ck("pose_risque 是场景显式 → 反过来赢", L.hand_winner(st2) == "pose_risque",
       L.hand_winner(st2))
    cleared = R.sanitize(st2)
    ck("sanitize 清掉让位的那一侧", st2.get("arms_hands") == ""
       and st2.get("pose_risque") == "skirt pull", f"{cleared} / {st2}")
    ck("sanitize 的报告里写明了让位关系",
       any("上肢单槽" in c for c in cleared), str(cleared))
    st3 = dict(st)
    R.sanitize(st3)
    ck("sanitize 只留一条手部动作", len(_hand_hits(st3)) == 1, str(_hand_hits(st3)))
    again = R.sanitize(st3)
    ck("sanitize 幂等（再修不再变）", not any("上肢单槽" in c for c in again), str(again))

    print("\n── ⑥ 无冲突的姿势不被误伤 ──")
    keep = {"pose_base": "sitting", "pose_risque": "bent over", "arms_hands": "v"}
    R.sanitize(keep)
    ck("sitting + bent over + v 三条全留（只有 v 算手部）",
       keep.get("pose_base") == "sitting" and keep.get("pose_risque") == "bent over"
       and keep.get("arms_hands") == "v", str(keep))

    print("\n── ⑦ 自检 F18 ──")
    bad_state = {"count": "1girl, solo", "arms_hands": "v",
                 "pose_base": "hands on own knees"}
    rep = R.check(["1girl", "solo", "hands on own knees", "v"], bad_state, 0)
    f18 = next((c for c in rep["F"] if c["id"] == "F18"), None)
    ck("F18 存在", f18 is not None, str([c["id"] for c in rep["F"]]))
    ck("F18 对双写判失败", f18 is not None and not f18["ok"],
       str(f18))
    ok_state = {"count": "1girl, solo", "arms_hands": "v"}
    rep2 = R.check(["1girl", "solo", "v"], ok_state, 0)
    f18b = next(c for c in rep2["F"] if c["id"] == "F18")
    ck("F18 对单写判通过", f18b["ok"], str(f18b))
    ck("实抽成品的 F18 恒通过",
       all(next(c for c in R.draw(level=lv, seed=i)["report"]["F"]
                if c["id"] == "F18")["ok"]
           for lv in ("sfw", "suggestive")
           for i in range(30)))

    print("\n── ⑧ 场景库自身零双写 ──")
    sc = json.load(open(os.path.join(PLUGIN, "presets", "anima_v4_scenes.json"),
                        encoding="utf-8"))
    dup = []
    for x in sc.get("scenes") or []:
        tags = x.get("tags") or {}
        hits = [(k, v) for k, v in tags.items()
                if k in L.HAND_SLOT and v in L.HAND_SLOT[k]]
        if len(hits) > 1:
            dup.append((x.get("id"), hits))
    ck("没有预设同时写两个手部动作", not dup, str(dup[:4]))

    print()
    if FAIL:
        print(f"[check_v3_hands] 失败 {len(FAIL)} 项：{FAIL}")
        return 1
    print(f"[check_v3_hands] 通过 {len(PASS)} 项："
          "表一致性 / 覆盖 / 实抽零冲突 / 不缺席 / 裁决口径 / F18 / 场景库")
    return 0


if __name__ == "__main__":
    sys.exit(main())
