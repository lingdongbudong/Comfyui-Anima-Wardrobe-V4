# -*- coding: utf-8 -*-
"""成品检查 + 自动修复基线（v3.8.0 新增能力）。

为什么需要单独一组基线：
  `sanitize()` 看的是 **state 字段**，管不到那些"绕过字段"的内容 ——
  手写补句 extra_body、法典预设自带的 n_extra、锁定/强制指定的值、
  上游拼接台送进来的文本。`repair()` 看的是**成品标签串**，专治这一类。

钉住四件事：

  ① 档位    —— 超档标签必须被剔除；**已登记校准项（wet hair）必须保住**；
               判定表盲区（pov crotch 这类）按逐选项升档表折算后一起管住。
  ② 结构互斥 —— 数量 / 视角 / 眼罩 / 服装 / 设备景深 / 体位，六组都在成品层生效。
  ③ 格式    —— 下划线归一、去重保序；`score_` 例外不被动。
  ④ 幂等 + 不误伤 —— repair(repair(x)) == repair(x)；
               正常生成的正文**一个字都不该被改**（否则就成了"顺手改用户内容"）。

另外钉住两条**不变量**：
  · LEVEL_RAISE 与 LEVEL_DEMOTE 的 (字段, 选项) 集合不相交；
  · LEVEL_RAISE 里每条都必须是真实存在的 (字段, 选项) —— 防手滑写错字段名后
    静默失效（写错字段名不会报错，只会不生效）。

跑法：python tests/check_v3_repair.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import _boot  # noqa: E402

R = _boot.load("anima_v4_rules")
OV = _boot.load("anima_v4_overrides")
N = _boot.load("anima_v4_nsfw")

LEVELS = ("sfw", "suggestive", "explicit", "hardcore", "extreme")

FAILS = []


def ck(name, cond, note=""):
    if cond:
        print(f"  [OK] {name}")
    else:
        print(f"  [!!] {name}  {note}")
        FAILS.append(name)


def rep(tags, lv):
    return R.repair(list(tags), lv)


def drops(fixes):
    return " ".join(fixes)


def main():
    print("── ① 档位：超档剔除 / 校准项保住 / 盲区折算 ──")
    out, fx = rep(["completely nude", "1girl", "solo"], 0)
    ck("超 0 档的 completely nude 被剔除", "completely nude" not in out, str(out))
    ck("剔除动作写进了修复记录", any("档位" in f for f in fx), str(fx))

    out, fx = rep(["wet hair", "hair over eyes", "1girl", "solo"], 0)
    ck("已登记校准项 wet hair 必须保住（否则 SFW 档再也抽不到湿发）",
       "wet hair" in out, str(out))

    # 判定表对 `pov crotch` 判 0（表里只有 `crotch cut`）→ 必须靠逐选项升档折算
    for lv, should_keep in ((0, False), (1, False), (2, True), (3, True)):
        out, _fx = rep(["pov crotch", "1girl", "solo"], lv)
        ck(f"pov crotch 在 L{lv} {'保留' if should_keep else '被剔除'}",
           ("pov crotch" in out) == should_keep, str(out))
    ck("tag_level 带上折算（判定表 0 + 升档表 2 → 2）",
       R.tag_level("pov crotch") == 2 and R.tag_level("pov breasts") == 1,
       f"{R.tag_level('pov crotch')} / {R.tag_level('pov breasts')}")

    print("── ② 结构互斥（在成品层生效，看标签不看字段）──")
    cases = [
        (["pov", "first-person view", "full body", "1girl", "solo"], 0,
         "full body", False, "POV × 全身（跨来源冲突，sanitize 抓不到）"),
        (["completely nude", "school uniform", "1girl", "solo"], 2,
         "school uniform", False, "全裸 × 具体服装"),
        (["pantyhose", "bare feet", "1girl", "solo"], 0,
         "bare feet", False, "连裤袜 × 赤足"),
        (["blindfold", "heart-shaped pupils", "1girl", "solo"], 3,
         "heart-shaped pupils", False, "蒙眼 × 心形瞳"),
        (["blindfold", "glasses", "1girl", "solo"], 3,
         "glasses", False, "蒙眼 × 眼镜"),
        (["1girl", "solo", "2girls", "yuri"], 2,
         "solo", False, "solo × 多人标签（数量互斥）"),
        (["from above", "from below", "1girl", "solo"], 0,
         "from below", False, "俯拍 × 仰拍同现"),
        (["facing away", "looking at viewer", "1girl", "solo"], 0,
         "looking at viewer", False, "背对镜头 × 注视镜头"),
        (["selfie", "focus on face", "1girl", "solo"], 0,
         "focus on face", False, "低画质设备 × 专业景深"),
        (["standing sex", "prone bone", "1girl", "1boy", "hetero"], 3,
         "prone bone", False, "站立性行为 × 俯卧体态"),
    ]
    for tags, lv, victim, keep, label in cases:
        out, _fx = rep(tags, lv)
        ck(label, (victim in out) == keep, str(out))

    # 改写型（不是删掉，而是换成站得住的值）
    out, fx = rep(["from above", "looking up", "1girl", "solo"], 0)
    ck("俯拍 × 抬眼 → 改写成注视镜头（不是删掉眼神）",
       "looking at viewer" in out and "looking up" not in out, str(out))

    print("── ③ 格式：下划线归一 / 去重保序 ──")
    out, fx = rep(["black_thighhighs", "Black Thighhighs", "1girl", "solo"], 0)
    ck("下划线归一成空格", "black thighhighs" in out, str(out))
    ck("归一后重复项只剩一条", out.count("black thighhighs") == 1, str(out))
    out, _fx = rep(["score_9", "1girl", "solo"], 0)
    ck("score_ 前缀不动（与自检 F12 的例外一致）", "score_9" in out, str(out))
    out, _fx = rep(["a", "b", "a", "c", "b"], 0)
    ck("去重保序", out == ["a", "b", "c"], str(out))

    print("── ④ 幂等 ──")
    allbags = [c[0] for c in cases] + [
        ["pov crotch", "pov breasts", "1girl", "solo"],
        ["black_thighhighs", "a", "a"],
        ["wet hair", "from above", "looking up", "blindfold", "glasses"],
    ]
    notidem = []
    for tags in allbags:
        for lv in (0, 2, 4):
            once, _ = rep(tags, lv)
            twice, fx2 = rep(once, lv)
            if twice != once or fx2:
                notidem.append((tags, lv, once, twice, fx2))
    ck("repair 幂等（修完再修不再变、也不再产生记录）", not notidem,
       str(notidem[:2]))

    print("── ⑤ 生成流程集成：该修的修、不该动的别动 ──")
    r = R.draw(level="sfw", seed=7,
               extra_body="pov crotch, completely nude, black_thighhighs")
    txt = r["text"]
    ck("手写补句里的超档内容被剔除",
       "pov crotch" not in txt and "completely nude" not in txt, txt[:80])
    ck("手写补句里的下划线被归一", "black_thighhighs" not in txt and "black thighhighs" in txt)
    ck("修复记录进了 report['repaired']", bool(r["report"].get("repaired")),
       str(r["report"].get("repaired")))
    ck("修复记录也进了 notes（面板能看到）",
       any("成品自动修复" in n for n in r["notes"]), str(r["notes"][-2:]))
    ck("修完之后自检仍然全绿",
       r["report"]["ok_f"] == r["report"]["total_f"],
       str([c["id"] for c in r["report"]["F"] if not c["ok"]]))

    touched, total, sample = 0, 0, []
    for lv in LEVELS:
        for s in range(40):
            res = R.draw(level=lv, seed=s * 31 + 7)
            total += 1
            again, fx = R.repair(list(res["tags"]), res["level_num"])
            if fx or again != res["tags"]:
                touched += 1
                if len(sample) < 2:
                    sample.append((lv, s, fx))
    ck(f"正常生成的正文零改动（{total} 个样本）", touched == 0,
       f"{touched} 个被改：{sample}")

    print("── ⑥ 校准表不变量 ──")
    inter = set(OV.LEVEL_RAISE) & set(OV.LEVEL_DEMOTE)
    ck("LEVEL_RAISE 与 LEVEL_DEMOTE 不相交", not inter, str(sorted(inter)))
    badkey, baden = [], []
    for (fk, en) in OV.LEVEL_RAISE:
        _sec, fld = R.field_by_key(fk)
        if not fld:
            badkey.append(fk)
            continue
        if en not in [e for _zh, e in fld.get("opts", [])]:
            baden.append((fk, en))
    ck("LEVEL_RAISE 的字段 key 都真实存在", not badkey, str(badkey))
    ck("LEVEL_RAISE 的选项原文都真实存在（写错字段名会静默失效）",
       not baden, str(baden))
    disk = json.load(open(os.path.join(PLUGIN, "presets", "anima_v4_levels.json"),
                          encoding="utf-8"))["option_levels"]
    mismatch = [(fk, en) for (fk, en) in OV.LEVEL_RAISE
                if int(disk.get(fk, {}).get(en, 0)) != R.option_level(fk, en)]
    ck("分类脚本落盘的档位 == 运行时 option_level（两级口径不打架）",
       not mismatch, str(mismatch))

    print("── ⑦ 成品反推 + 检查（新节点依赖的能力）──")
    # ⚠️ v3.12.0 踩到的坑：场景库（anima_v4_scenes.json）的 `extra` 会往成品里塞
    #    **不属于任何字段**的标签（实测某 NSFW 场景带
    #    "first-person view, straddling, looking down at viewer"）。而 `pov` 同时属于
    #    多个 viewpoint 选项（`first-person view, pov` / `pov, cowgirl position` …）
    #    → 成品层**本质上无法消歧**。
    #
    # ⚠️⚠️ v3.14.0 改成**直接锁掉 n_canon**（本次不抽场景），不再靠"事后剔除 extra"：
    #    后者会误伤 —— extra 里也可能出现**与字段选项同名**的标签。实测某场景的
    #    extra 带 `mirror, reflection`，而它恰好就是 `viewpoint` 的合法取值，
    #    事后一剔就把真值也剔了，反推必然失败（且失败原因极难看出来）。
    #    锁字段测的是「反推能力」本身，与场景无关 —— 这才是这条断言该测的。
    _locks = {"n_canon"}
    src = R.draw(level="hardcore", seed=3, locks=_locks)["tags"]
    st = R.infer_state(src)
    ck("能从成品反推出字段（至少 5 个）", len(st) >= 5, f"{len(st)} 个")

    extra_bag = set()
    for _sc in (json.load(open(os.path.join(PLUGIN, "presets", "anima_v4_scenes.json"),
                               encoding="utf-8")).get("scenes") or []):
        for _t in str(_sc.get("extra") or "").split(","):
            if _t.strip():
                extra_bag.add(_t.strip().lower())
    ck("场景库 extra 标签已识别（用于剔除污染）", len(extra_bag) > 0, str(len(extra_bag)))
    ck("反推出的视角/景别与实际一致",
       st.get("viewpoint")
       == R.draw(level="hardcore", seed=3, locks=_locks)["state"].get("viewpoint"),
       f"{st.get('viewpoint')!r}")
    _st, rep2 = R.check_text(["pov", "full body", "blindfold", "glasses", "1girl", "solo"], 0)
    ck("check_text 对矛盾文本给出致命项结论", rep2["total_f"] > 0)
    txt2 = R.format_check_report(["1girl", "solo"], 0, rep2, fixes=["示例修复"])
    ck("报告渲染出「已自动修复」段", "已自动修复" in txt2 and "致命项" in txt2)

    # ── v3.16.0 口径统一回归 ──────────────────────────────────────
    # 「实际落档」改按校准口径（tag_level）计算后，必须满足：
    #   · 报告档位 ≤ 所选档（100%，此前 SFW 23% 显示 2 / explicit 40% 显示 3）
    #   · 判据是**传入的等级参数**（独立真源），不是被测链路的任何输出。
    # raw_level（判定表裸口径）保留在报告里，供对拍排查，不参与判定。
    bad_real = []
    for _lvk in LEVELS:
        _lv = R.level_num(_lvk)
        for _seed in range(1000, 1030):
            _rep = R.draw(level=_lvk, seed=_seed)["report"]
            if int(_rep["real_level"]) > _lv:
                bad_real.append((_lvk, _seed, int(_rep["real_level"])))
    ck("报告「实际落档」≤ 所选档（30 轮 × 5 档）", not bad_real,
       f"越界样本 {bad_real[:4]}")
    _w = R.check(["1girl", "solo", "wet hair"], {"hair_fx": "wet hair"}, 0)
    ck("湿发（校准词）在 SFW 报告落档 0", int(_w["real_level"]) == 0
       and int(_w["raw_level"]) == 2,
       f"real={_w['real_level']} raw={_w.get('raw_level')}")

    print()
    if FAILS:
        print(f"[check_v3_repair] 失败 {len(FAILS)} 项：{FAILS}")
        return 1
    print("[check_v3_repair] 通过：档位 / 互斥 / 格式 / 幂等 / 集成 / 不变量 全部符合预期")
    return 0


if __name__ == "__main__":
    sys.exit(main())
