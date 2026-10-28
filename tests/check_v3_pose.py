# -*- coding: utf-8 -*-
"""姿势段基线与「暗示姿势」档位闸门（v3.14.0 新增）。

守三件事：

  ① **段级闸门的语义** —— `section_allowed()` 必须按**段内最低档**判，
     不能按最高档。v3.14.0 往 `pose_sfw` 段加了 L1/L2 的暗示姿势后，
     该段 `section_max` 从 0 变成 2 —— 用旧的「max <= lv」判据会让
     **SFW 档整段消失**（姿势一个都抽不到）。这是本文件最重要的一条断言。

  ② **暗示姿势的档位** —— L1/L2 的姿势不得出现在 SFW 档；
     L1/L2 档必须真的能抽到（不能因为闸门过严而永远抽不出来）。

  ③ **姿势 tag 的有效性** —— 禁止再出现 danbooru 上的**别名/deprecated 写法**
     （`lying on back` / `peace sign` / `arms crossed` …）。
     这些 tag 严格说是"能归一化的"，但模型训练用的是**正式写法**，
     用别名等于把命中率交给运气。

跑法：python tests/check_v3_pose.py [每档抽样轮数，默认 120]
"""
import json
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


# danbooru 上已废弃 / 是别名的写法（写进提示词会走归一化，命中率靠运气）。
# ⚠️ 这正是 v3.14.0 批量修掉的那批。
DEPRECATED = {
    "lying on back", "lying on side", "lying on stomach", "crouching",
    "peace sign", "arms crossed", "covering mouth", "hand on hip",
    "chin rest", "on all fours", "twirling", "leg muscles",
    "hugging own knees", "pulling own collar", "by the window",
    "lying on desk", "pinned down", "ankles locked behind",
}


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    d = json.load(open(os.path.join(PLUGIN, "presets", "anima_v4_pools.json"),
                       encoding="utf-8"))
    lv = json.load(open(os.path.join(PLUGIN, "presets", "anima_v4_levels.json"),
                        encoding="utf-8"))

    print("── ① 字段与档位 ──")
    fields = {f["key"]: f for s in d["sections"] for f in s["fields"]}
    ck("「暗示姿势 pose_risque」字段已存在", "pose_risque" in fields)
    n_risque = len(fields["pose_risque"]["opts"]) if "pose_risque" in fields else 0
    ck("pose_risque 有 22 项", n_risque == 22, str(n_risque))
    ck("姿势段共 4 个字段（base / arms / action / risque）",
       sum(1 for s in d["sections"] if s["id"] == "pose_sfw"
           for _f in s["fields"]) == 4)

    ol = lv["option_levels"].get("pose_risque", {})
    dist = {}
    for v in ol.values():
        dist[v] = dist.get(v, 0) + 1
    ck("暗示姿势档位 = L1×14 + L2×8", dist == {1: 14, 2: 8}, str(dist))
    ck("pose_sfw 段的 section_max 已被抬到 2（含 L2 选项）",
       lv["section_max"].get("pose_sfw") == 2, str(lv["section_max"].get("pose_sfw")))
    ck("pose_sfw 段的 section_floor 仍是 0",
       lv["section_floor"].get("pose_sfw") == 0)
    # ⚠️ 磁盘 JSON 会被"改了 overrides 但忘记重跑分类脚本"弄脏 ——
    #    这里再要求**运行时**口径一致（`option_level` 会现场重算上抬）。
    runtime = {e: R.option_level("pose_risque", e) for e in ol}
    ck("运行时的 pose_risque 档位与磁盘一致", runtime == ol,
       str({k: (ol[k], runtime[k]) for k in ol if ol[k] != runtime.get(k)}))
    ck("运行时 option_level(bent over) = 1（在 overrides 里上抬过）",
       R.option_level("pose_risque", "bent over") == 1,
       str(R.option_level("pose_risque", "bent over")))

    print("\n── ② 段级闸门：SFW 档姿势段必须仍然可用 ──")
    # ⚠️ 这是 v3.14.0 修的那个真 bug：按 max 判会让这里 False。
    ck("section_allowed(pose_sfw, 0) 为真（SFW 档姿势段可用）",
       R.section_allowed("pose_sfw", 0))
    for lvl in (1, 2, 3, 4):
        ck(f"section_allowed(pose_sfw, {lvl}) 为真", R.section_allowed("pose_sfw", lvl))
    ck("section_allowed(pose_nsfw, 2) 为真（v3.15.0：露骨档起开放非插入行为）",
       R.section_allowed("pose_nsfw", 2))
    ck("section_allowed(pose_nsfw, 1) 为假（暗示档不该出现性行为）",
       not R.section_allowed("pose_nsfw", 1))
    ck("section_allowed(pose_nsfw, 3) 为真", R.section_allowed("pose_nsfw", 3))

    print("\n── ③ 逐选项闸门 ──")
    sfw_pool = {e for _z, e, _n in R.eligible_options("pose_risque", 0)}
    ck("SFW 档的 pose_risque 候选池为空", not sfw_pool, str(sorted(sfw_pool)[:4]))
    for lvl, want in ((1, 14), (2, 22), (3, 22)):
        pool = R.eligible_options("pose_risque", lvl)
        ck(f"{lvl} 档候选 {want} 项", len(pool) == want, str(len(pool)))

    print("\n── ④ 实抽：SFW 档不出暗示姿势，L1/L2 能抽到 ──")
    risky = set(ol.keys())
    hit_sfw, hit_l1, hit_l2 = 0, 0, 0
    for i in range(rounds):
        for lvl_name, counter in (("sfw", None), ("suggestive", "l1"), ("explicit", "l2")):
            r = R.draw(level=lvl_name, seed=10000 + i)
            got = set()
            for t in r["tags"]:
                got |= {x.strip() for x in t.split(",")}
            n = len(got & risky)
            if lvl_name == "sfw":
                hit_sfw += n
            elif n:
                if counter == "l1":
                    hit_l1 += 1
                else:
                    hit_l2 += 1
    ck(f"SFW 档 {rounds} 轮**零**暗示姿势泄漏", hit_sfw == 0, f"共 {hit_sfw} 个")
    ck(f"suggestive 档至少抽到过暗示姿势（{hit_l1}/{rounds} 轮）", hit_l1 > 0)
    ck(f"explicit 档至少抽到过暗示姿势（{hit_l2}/{rounds} 轮）", hit_l2 > 0)

    print("\n── ⑤ 姿势 tag 不再用废弃写法 ──")
    bad = []
    for key in ("pose_base", "arms_hands", "action", "pose_risque", "n_pos"):
        for _z, e in fields.get(key, {}).get("opts", []):
            for t in str(e).split(","):
                if t.strip().lower() in DEPRECATED:
                    bad.append((key, t.strip()))
    ck("5 个姿势/体位字段里没有废弃写法", not bad, str(bad[:5]))

    print("\n── ⑥ 场景库引用全部合法 ──")
    valid = {f["key"]: {e for _z, e in f.get("opts") or []}
             for s in d["sections"] for f in s["fields"]}
    sc = json.load(open(os.path.join(PLUGIN, "presets", "anima_v4_scenes.json"),
                        encoding="utf-8"))
    illegal = []
    for x in sc.get("scenes") or []:
        for k, v in (x.get("tags") or {}).items():
            if k in valid and v not in valid[k]:
                illegal.append((x.get("id"), k, v))
    ck("每条预设的字段取值都真实存在", not illegal, str(illegal[:4]))

    print()
    if FAIL:
        print(f"[check_v3_pose] 失败 {len(FAIL)} 项：{FAIL}")
        return 1
    print(f"[check_v3_pose] 通过 {len(PASS)} 项：字段 / 档位 / 段闸门 / 实抽 / tag 有效性 / 场景引用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
