# -*- coding: utf-8 -*-
"""特写搭配（manual_only）基线 —— v3.18.0。

盯四件事：
  ① 数据层   —— 32 条特写全在 `near` 组、`manual_only` 为真、部位齐全、档位分布；
  ② **随机隔离** —— 默认权重下，5 档 × N seed 一次都抽不到特写（这是"不影响原行为"的核心）；
  ③ 显式套用   —— 选项权重顶到 3.0 时必须命中，且景别/extra 真落地；取消后不再命中；
  ④ 零影响对拍 —— 把特写条目从库里摘掉重跑，输出 SHA256 必须全等（= v3.17.2 行为）；
  ⑤ 载荷与自检 —— /scenes 带 manual/part/near_parts；/pools 候选 = 随机候选 + 特写；
                  且 `validate_weights` 不再把合法 sc_* 误报成"不存在的选项"；
  ⑥ 口交特写取景（v3.22.0 起，v3.38.6 收紧）—— 第一人称、不写 pose_base、drop_fields 闭麦、
                  extra 只到面部（无舌头/无阴毛/无胸肩）、档位仍 L3。

跑法：python tests/check_v3_near.py [每档抽样次数，默认 40]
"""
import copy
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import _boot  # noqa: E402

R = _boot.load("anima_v4_rules")

FAILS = []
PARTS_EXPECT = ["面部", "眼与唇", "上半身与胸", "手部", "腿部", "脚部", "臀部", "🔞 成人向"]


def ck(name, cond, note=""):
    if cond:
        print(f"  [OK] {name}")
    else:
        print(f"  [!!] {name}  {note}")
        FAILS.append(name)


def digest(rounds):
    """固定 seed 跑一遍，返回输出指纹。"""
    out = []
    for lv in ("sfw", "suggestive", "explicit", "hardcore", "extreme"):
        for s in range(rounds):
            r = R.draw(level=lv, seed=s, base_prob=0.9)
            out.append([lv, s, r["text"], r["report"]["n"],
                        r["report"]["real_level"], r["report"]["ok_f"]])
    return hashlib.sha256(
        json.dumps(out, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    scenes = R.scene_list()
    near = [s for s in scenes if s.get("manual_only")]
    other = [s for s in scenes if not s.get("manual_only")]

    print("── ① 数据层 ──")
    ck("特写搭配 60 条（30 + 臀 6 + 腿 6 + 成人向 18）", len(near) == 60, str(len(near)))
    ck("全部在 group=near", all(s.get("group") == "near" for s in near),
       str([s["id"] for s in near if s.get("group") != "near"][:3]))
    ck("全部 manual_only=True", all(s.get("manual_only") is True for s in near))
    ck("原场景搭配一条都没被标记", not any(s.get("manual_only") for s in other))
    ck("每条都有部位 theme", all(s.get("theme") for s in near),
       str([s["id"] for s in near if not s.get("theme")][:3]))
    ck("部位集合与预期一致",
       sorted({s["theme"] for s in near}) == sorted(PARTS_EXPECT),
       str(sorted({s["theme"] for s in near})))
    lv = {}
    for s in near:
        lv[str(s["level"])] = lv.get(str(s["level"]), 0) + 1
    # 30 基础 + 臀 6 + 腿 6（L0 4 · L1 2）+ 成人向 18（L1 4 · L2 8 · L3 5 · L4 1）
    # v3.38.1：删除「指尖触碰镜头」「抓握床单」两条 L0 特写 → L0 36→34
    # v3.38.2：「大腿根特写」改"双手抱腿抬起"（pose_risque=leg up → hugging own legs）→ L2 降 L1
    # v3.38.8（2026-10-24）：「舌与唾液」加 ahegao / rolled back eyes（均 L3）→ L1 → L3
    ck("档位分布 L0=34 / L1=10 / L2=9 / L3=6 / L4=1",
       lv == {"0": 34, "1": 10, "2": 9, "3": 6, "4": 1}, str(lv))
    leg = [s for s in near if s.get("theme") == "腿部"]
    ck("腿部组 12 条（含坐姿 / 单腿伸向镜头）", len(leg) == 12, str(len(leg)))
    ck("腿部组含「伸向镜头」条目",
       any("伸向镜头" in s["zh"] for s in leg),
       str([s["zh"] for s in leg]))
    adult = [s for s in near if s.get("theme") == "🔞 成人向"]
    # v3.38.8：「舌与唾液」L1 → L3（ahegao 属 L3），成人向组变成 L1 4 · L2 7 · L3 6 · L4 1
    ck("成人向组 18 条（L1 4 · L2 7 · L3 6 · L4 1）",
       len(adult) == 18
       and sorted(int(s["level"]) for s in adult) == [1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2,
                                                     3, 3, 3, 3, 3, 3, 4],
       str(sorted(int(s["level"]) for s in adult)))
    duo = [s for s in adult if str(s.get("extra") or "").startswith("2girls")]
    ck("双女胸部组 6 条（擦边 2 + 成人向 4）",
       sorted(s["id"] for s in duo) == sorted([
           "sc_near_soft_breast_massage", "sc_near_soft_breast_hug",
           "sc_near_nsfw_breast_massage", "sc_near_nsfw_nipple_suck",
           "sc_near_nsfw_breast_suck", "sc_near_nsfw_lactation"]),
       str(sorted(s["id"] for s in duo)))
    ck("双女胸部组档位 L2×4 / L3 / L4",
       sorted(int(s["level"]) for s in duo) == [2, 2, 2, 2, 3, 4],
       str(sorted(int(s["level"]) for s in duo)))
    soft = [s for s in near if s["id"].startswith("sc_near_soft_")]
    ck("擦边双女写的是「隔衣」标签（clothed / covered breasts）",
       all("clothed" in str(s["extra"]) and "covered breasts" in str(s["extra"])
           for s in soft),
       str([s["id"] for s in soft if "clothed" not in str(s["extra"])]))
    ck("擦边双女不含露点标签（nipples / areolae 不出现在 extra）",
       not [s["id"] for s in soft
            if "nipples" in str(s["extra"]) or "areolae" in str(s["extra"])],
       str(soft))
    ck("双女胸部组都钉死人数并保留角色",
       all(s.get("count_lock") == "2girls, yuri" and s.get("role_ok") for s in duo),
       str([s["id"] for s in duo
            if not (s.get("count_lock") == "2girls, yuri" and s.get("role_ok"))]))
    hip = [s for s in near if s.get("theme") == "臀部"]
    ck("臀部组 6 条", len(hip) == 6, str(len(hip)))
    # v3.38.1：「裸臀俯卧」改「内裤俯卧」（穿内裤、去掉 bare ass）→ 从 L2 降到 L1
    ck("臀部组档位 L0×2 / L1×3 / L2×1",
       sorted(int(s["level"]) for s in hip) == [0, 0, 1, 1, 1, 2],
       str(sorted(int(s["level"]) for s in hip)))
    ck("臀部组都固定了景别与机位",
       all((s["tags"] or {}).get("shot_size") and (s["tags"] or {}).get("viewpoint")
           for s in hip),
       str([s["id"] for s in hip
            if not ((s["tags"] or {}).get("shot_size") and (s["tags"] or {}).get("viewpoint"))]))
    ck("没有 count / role 字段（预设不抢地基）",
       not [s["id"] for s in near
            if "count" in (s.get("tags") or {}) or "role" in (s.get("tags") or {})])
    ck("id 全部 sc_ 前缀（面板靠它认当前套用）",
       all(s["id"].startswith("sc_") for s in near))
    ro = [s["id"] for s in near if s.get("role_ok")]
    ck("role_ok（有脸，保留角色）恰好 11 条",
       sorted(ro) == sorted(["sc_near_nsfw_fellatio", "sc_near_nsfw_cunnilingus",
                             "sc_near_nsfw_tongue", "sc_near_nsfw_cleavage",
                             "sc_near_nsfw_sheer", "sc_near_nsfw_breast_massage",
                             "sc_near_nsfw_nipple_suck", "sc_near_nsfw_breast_suck",
                             "sc_near_nsfw_lactation", "sc_near_soft_breast_massage",
                             "sc_near_soft_breast_hug"]), str(ro))
    ck("role_ok 之外的条目都不保留角色",
       not [s["id"] for s in near if s.get("role_ok") and s.get("theme") != "🔞 成人向"])
    cu = [s for s in near if s["id"] == "sc_near_nsfw_cunnilingus"][0]
    ck("舔阴特写是双女（count_lock = 2girls, yuri）",
       cu.get("count_lock") == "2girls, yuri", str(cu.get("count_lock")))
    # v3.38.4（2026-10-24）：yuri 由 count_lock 负责，extra 不再重复写 ——
    # 重复的 yuri 会把语义拉向"接吻/拥抱"，与 cunnilingus 抢动作（实测姿势崩坏）
    ck("双女条目不在 extra 重复写 yuri（由 count_lock 负责）",
       "yuri" not in str(cu.get("extra")), str(cu.get("extra")))
    # v3.38.7（2026-10-24 用户要求）：必须同时看见「舌头」与「生殖器」——
    # extra 因此多了 pussy / licking / tongue out / saliva 四个落点词（上限放宽到 12）
    ck("双女条目 extra 保持精简（不超过 12 个词条，不堆自造描述）",
       len([x for x in str(cu.get("extra") or "").split(",") if x.strip()]) <= 12,
       str(cu.get("extra")))
    ck("舔阴特写钉死 mouth = tongue out（舌头必须在画面里）",
       (cu.get("tags") or {}).get("mouth") == "tongue out", str((cu.get("tags") or {}).get("mouth")))
    ck("舔阴特写不再闭麦 mouth（否则和写死的 tongue out 自相矛盾）",
       "mouth" not in (cu.get("drop_fields") or []), str(cu.get("drop_fields")))
    ck("舔阴特写 extra 显式写 pussy（生殖器要看得见）",
       "pussy" in str(cu.get("extra") or ""), str(cu.get("extra")))
    ck("舔阴特写用 close-up（中景看不清舌与生殖器）",
       (cu.get("tags") or {}).get("shot_size") == "close-up", str((cu.get("tags") or {}).get("shot_size")))

    # ── ①之一 舌与唾液：面部+肩膀 / 正面 / 极端表情 / 舌姿随机（v3.38.7）──
    tg = [s for s in near if s["id"] == "sc_near_nsfw_tongue"][0]
    tt = tg.get("tags") or {}
    ck("舌与唾液用 close-up（只要面部与肩膀，不再只剩嘴）",
       tt.get("shot_size") == "close-up", str(tt.get("shot_size")))
    ck("舌与唾液 extra 带 shoulders，且不再写 mouth only",
       "shoulders" in str(tg.get("extra")) and "mouth only" not in str(tg.get("extra")),
       str(tg.get("extra")))
    # v3.38.8：翻白眼（rolled back eyes）与"直视镜头"在眼睛上互斥 ——
    # 正面改成靠构图保证（viewpoint 已闭麦 → 默认正对），眼神用与 ahegao 相容的半闭眼
    ck("舌与唾液正面视角：构图靠闭麦 viewpoint，眼神用 half-closed eyes（与翻白眼相容）",
       tt.get("eye_gaze") == "half-closed eyes"
       and "viewpoint" not in tt
       and "viewpoint" in (tg.get("drop_fields") or []),
       f"{tt.get('eye_gaze')} / tags={sorted(tt)} / drop={tg.get('drop_fields')}")
    ck("舌与唾液写死 mouth = tongue out（舌头必须在画面里）",
       tt.get("mouth") == "tongue out", str(tt.get("mouth")))
    ck("舌与唾液闭麦 viewpoint（俯仰/侧背/POV 会把脸拍歪）",
       "viewpoint" in (tg.get("drop_fields") or []), str(tg.get("drop_fields")))
    ck("舌与唾液闭麦 figure / makeup（胸型与咬唇妆会和吐舌抢戏）",
       {"figure", "makeup"} <= set(tg.get("drop_fields") or []), str(tg.get("drop_fields")))
    # v3.38.11（用户 2026-10-24）：舌钉（danbooru: tongue piercing）作为可选装饰，
    # 与舌姿组合成 7 种（3 种带钉 / 4 种不带）
    _rvs = tg.get("random_variants") or []
    ck("舌与唾液七组舌姿随机（含舌钉），且每组都真的带舌头标签",
       len(_rvs) == 7 and all("tongue" in str(v.get("extra")) for v in _rvs),
       str([v.get("zh") for v in _rvs]))
    ck("舌与唾液既有带舌钉也有不带舌钉的变体",
       any("tongue piercing" in str(v.get("extra")) for v in _rvs)
       and any("tongue piercing" not in str(v.get("extra")) for v in _rvs),
       str([v.get("zh") for v in _rvs]))
    ck("舌与唾液表情随机 ≥ 4 种（偏极端）",
       len((tg.get("random_fields") or {}).get("emotion") or []) >= 4,
       str((tg.get("random_fields") or {}).get("emotion")))
    # v3.38.8（用户 2026-10-24 决定）：要真的极端表情 —— ahegao / rolled back eyes 都是 L3，
    # 所以这条整体从 L1 升到 L3，档位断言同步改（见上方档位分布两条）。
    ck("舌与唾液 extra 写死 ahegao + rolled back eyes（真极端表情）",
       "ahegao" in str(tg.get("extra")) and "rolled back eyes" in str(tg.get("extra")),
       str(tg.get("extra")))
    ck("舌与唾液档位随内容升到 L3", int(tg.get("level", 0)) == 3, str(tg.get("level")))
    ck("舌与唾液表情候选不再含与 ahegao 冲突的 smug / evil smile",
       not ({"smug", "evil smile"} & set((tg.get("random_fields") or {}).get("emotion") or [])),
       str((tg.get("random_fields") or {}).get("emotion")))
    # v3.38.10（用户 2026-10-24）：取消「舔唇」舌姿（licking lips 会抢极端表情），
    # 并用 n_orgasm 里现成的 ahegao 选项再加固一次出现率。
    ck("舌与唾液舌姿里没有「舔唇」",
       all("licking lips" not in str(v.get("extra", "")) for v in (tg.get("random_variants") or [])),
       str([v.get("extra") for v in (tg.get("random_variants") or [])]))
    ck("舌与唾液用 n_orgasm 写死 ahegao，加固极端表情",
       (tg.get("tags") or {}).get("n_orgasm") == "ahegao, rolled back eyes",
       str((tg.get("tags") or {}).get("n_orgasm")))
    # 引擎级：20 抽 —— 极端表情与舌头必须每次都齐，且绝不出现舔唇
    _miss, _lick = [], []
    for _sd in range(20):
        _toks = {x.strip() for x in R.draw(level=int(tg.get("level", 3)), seed=_sd,
                                          forced={"n_canon": tg["id"]})["text"].split(",")}
        if not ({"ahegao", "rolled back eyes", "tongue"} <= _toks):
            _miss.append(_sd)
        if "licking lips" in _toks:
            _lick.append(_sd)
    ck("舌与唾液 20 抽：ahegao / rolled back eyes / tongue 每次都齐",
       not _miss, str(_miss))
    ck("舌与唾液 20 抽：一次都不出现 licking lips", not _lick, str(_lick))

    # ── ①之二 口交特写：第一人称 + 只拍脸与肩（v3.22.0）──────────
    # 报障：套用后不是第一人称、画面里冒出跪着的整具身体 / 对方的手 / 胸口。
    # 这三条断言就是那次修复的护栏 —— 任何一条回退都会让 bug 原样复发。
    fe = [s for s in near if s["id"] == "sc_near_nsfw_fellatio"][0]
    ft = fe.get("tags") or {}
    ck("口交特写用第一人称（viewpoint = pov, fellatio）",
       ft.get("viewpoint") == "pov, fellatio", str(ft.get("viewpoint")))
    ck("口交特写不写 pose_base（跪姿会把整具身体拉进画面）",
       "pose_base" not in ft, str(sorted(ft)))
    ck("口交特写用 drop_fields 闭麦 pose_base",
       "pose_base" in (fe.get("drop_fields") or []), str(fe.get("drop_fields")))
    ck("口交特写 extra 带 solo focus（镜头只对着她一个人）",
       "solo focus" in str(fe.get("extra") or ""), str(fe.get("extra")))
    # v3.38.3（用户 2026-10-24）：画面只许有「面部 + 生殖器」，胸部/肩部必须出画 ——
    # 原来 extra 主动写了 shoulders / head and shoulders，等于把胸请进画面（实测出图带胸）。
    ck("口交特写 extra 带 face、且明确把肩/躯干排除出画",
       "face" in str(fe.get("extra") or "")
       and "chest out of frame" in str(fe.get("extra") or "")
       and "shoulders" not in str(fe.get("extra") or ""),
       str(fe.get("extra")))
    # v3.38.6（2026-10-24 用户要求）：放大画面，女方**只出现面部**；
    # 原来 close-up 会带到下颌/颈/肩，且生殖器根部（阴毛）会入画。
    ck("口交特写用 extreme close-up（画面只到面部）",
       ft.get("shot_size") == "extreme close-up", str(ft.get("shot_size")))
    ck("口交特写 extra 不再写 chin（下颌会把颈肩带进画面）",
       "chin" not in str(fe.get("extra") or ""), str(fe.get("extra")))
    ck("口交特写禁项含 pubic hair（生殖器根部毛发不许出现）",
       "pubic hair" in (fe.get("ban_tags") or []), str(fe.get("ban_tags")))
    ck("口交特写闭麦 n_body（该字段的候选就是 pubic hair / hairless pussy）",
       "n_body" in (fe.get("drop_fields") or []), str(fe.get("drop_fields")))
    ck("口交特写变体不再用 nose touching（鼻压耻骨会把根部毛发带进画面）",
       all("nose touching" not in str(v.get("extra", "")) for v in (fe.get("random_variants") or [])),
       str([v.get("extra") for v in (fe.get("random_variants") or [])]))
    ck("口交特写闭麦 figure（禁胸型描述）",
       "figure" in (fe.get("drop_fields") or []), str(fe.get("drop_fields")))
    ck("口交特写禁掉胸部尺寸类标签（挡 breast_size 注入）",
       {"huge breasts", "large breasts"} <= set(fe.get("ban_tags") or []),
       str(fe.get("ban_tags")))
    # 用户口径（2026-10-23 补充）：**生殖器要在画面里**，所以"只看见脸与肩"
    # 约束的是**女方**——`penis` 必须显式写在 extra，不能靠 pov 标签碰运气。
    ck("口交特写 extra 显式写 penis（生殖器要出现在画面里）",
       "penis" in str(fe.get("extra") or ""), str(fe.get("extra")))
    ck("口交特写档位仍是 L3（靠 pov, fellatio 拿档，不靠 extra 里的裸动作词）",
       int(fe.get("level", 0)) == 3, str(fe.get("level")))
    ck("口交特写的 extra 不再带 teeth（会画出露齿特写）",
       "teeth" not in str(fe.get("extra") or ""), str(fe.get("extra")))
    # 闭麦的机制验证：字段权重 0 时引擎一个姿势标签都不出
    wf = R.empty_weights()
    wf["fields"]["pose_base"] = 0.0
    leak = []
    for sd in range(12):
        st = R.draw(level="extreme", seed=sd, weights=wf, base_prob=0.9)["state"]
        if st.get("pose_base"):
            leak.append((sd, st.get("pose_base")))
    ck("pose_base 权重 0 → 12 个 seed 一个姿势标签都不出", not leak, str(leak[:3]))

    # ── ①之三 口交特写：口部状态 / 表情要能随机抽（v3.22.0）────────
    # 用户口径：同一条特写里也要有几种状态与表情，不能每次都是同一张嘴。
    rf = fe.get("random_fields") or {}
    ck("口交特写有 random_fields（mouth / emotion 可随机）",
       set(rf) == {"mouth", "emotion"}, str(sorted(rf)))
    # v3.38.6（2026-10-24 用户要求）：**画面里不许出现舌头** —— 候选去掉 `tongue out`，
    # 只留张嘴 / 微张（原 v3.38.5 已去掉 `licking lips`）
    ck("口部状态候选 = 2 种（张嘴/微张），不含吐舌",
       len(rf.get("mouth") or []) == 2 and "tongue out" not in (rf.get("mouth") or []),
       str(rf.get("mouth")))
    ck("口交特写禁项含 tongue out（双保险：字段抽到也会被清空）",
       "tongue out" in (fe.get("ban_tags") or []), str(fe.get("ban_tags")))
    ck("口交特写任何变体都不含舌头类标签",
       all("tongue" not in str(v.get("extra", "")) for v in (fe.get("random_variants") or [])),
       str([v.get("extra") for v in (fe.get("random_variants") or [])]))
    ck("口交特写必定深喉：每个变体都带 deepthroat 类标签",
       all(any(k in v.get("extra", "") for k in ("deepthroat", "throat bulge", "irrumatio"))
           for v in (fe.get("random_variants") or [])),
       str([v.get("zh") for v in (fe.get("random_variants") or [])]))
    ck("口交特写每个变体都带极端表情",
       all(any(k in v.get("extra", "") for k in ("ahegao", "rolled back eyes", "mind break",
                                                 "fucked silly", "drool", "tears"))
           for v in (fe.get("random_variants") or [])),
       str([v.get("extra") for v in (fe.get("random_variants") or [])]))
    ck("表情候选 ≥ 4 种", len(rf.get("emotion") or []) >= 4, str(rf.get("emotion")))
    ck("random_fields 与 tags 不重叠（要么写死、要么随机）",
       not (set(rf) & set(ft)), str(sorted(set(rf) & set(ft))))
    # 引擎级：20 个 seed 里两个字段都要真变，且**一次都不能空**
    # ⚠️ 这里只需要"锁住 n_canon = 口交特写"，其余字段留默认（前端套用时会把
    #    白名单外字段清零，但那是**取景**的事，与本条测的"随机抽取"无关）。
    wrf = R.empty_weights()
    wrf["fields"]["n_canon"] = 3.0
    rf_ids = [en for _zh, en in R.field_by_key("n_canon")[1]["opts"]] + \
             [sid for _zh, sid, _n in R.scene_options(99, include_manual=True)]
    wrf["options"]["n_canon"] = {k: 0.0 for k in rf_ids}
    wrf["options"]["n_canon"][fe["id"]] = 3.0
    seen_m, seen_e, blank = set(), set(), []
    for sd in range(20):
        st = R.draw(level="extreme", seed=sd, weights=wrf, base_prob=0.9)["state"]
        seen_m.add(st.get("mouth") or "")
        seen_e.add(st.get("emotion") or "")
        if not st.get("mouth") or not st.get("emotion"):
            blank.append(sd)
    # v3.38.6：口部候选只剩 2 种（张嘴 / 微张）—— 用户明确要求画面里不出现舌头
    ck("20 个 seed 里两种口部状态都出现", len(seen_m - {""}) >= 2, str(sorted(seen_m)))
    ck("20 个 seed 里表情至少出现 3 种", len(seen_e - {""}) >= 3, str(sorted(seen_e)))
    ck("20 个 seed 里 mouth / emotion 一次都没被清空（联动矛盾要重抽，不是清空）",
       not blank, str(blank))
    ck("count_lock 只用合法的 count 选项原文",
       all((not s.get("count_lock")) or s["count_lock"] == "2girls, yuri" for s in near),
       str([s["id"] for s in near if s.get("count_lock")]))
    ck("每条都有 extra 部位词",
       all(str(s.get("extra") or "").strip() for s in near),
       str([s["id"] for s in near if not str(s.get("extra") or "").strip()][:3]))

    print("── ② 随机隔离：默认权重下抽不到特写 ──")
    ck("eligible_options 不含任何特写",
       not [en for _zh, en, _n in R.eligible_options("n_canon", 4)
            if R.scene_index().get(en, {}).get("manual_only")])
    hits = []
    for lv_key in ("sfw", "suggestive", "explicit", "hardcore", "extreme"):
        for s in range(rounds):
            st = R.draw(level=lv_key, seed=s, base_prob=0.9)["state"]
            got = st.get("n_canon") or ""
            if got.startswith("sc_near_"):
                hits.append((lv_key, s, got))
    ck(f"5 档 × {rounds} seed 全部未命中特写", not hits, str(hits[:3]))

    print("── ③ 显式套用：权重 3.0 才放行 ──")
    all_ids = [en for _zh, en in R.field_by_key("n_canon")[1]["opts"]] + \
              [sid for _zh, sid, _n in R.scene_options(99, include_manual=True)]
    target = "sc_near_leg_crossed"
    w = R.empty_weights()
    w["fields"]["n_canon"] = 3.0
    w["options"]["n_canon"] = {k: 0.0 for k in all_ids}
    w["options"]["n_canon"][target] = 3.0
    st = R.draw(level="sfw", seed=7, weights=w, base_prob=0.9)["state"]
    ck("套用后 n_canon 命中该条", st.get("n_canon") == target, str(st.get("n_canon")))
    # 景别取**预设里写的那个值**（四肢组 v3.18.0 调成了 extreme close-up），
    # 不写死字面量 —— 否则改配方就要改测试。
    want_shot = R.scene_index()[target]["tags"].get("shot_size")
    ck(f"景别按预设固定（{want_shot}）", st.get("shot_size") == want_shot,
       str(st.get("shot_size")))
    ck("extra 部位词落地", "thighs" in str(st.get("n_extra") or ""),
       str(st.get("n_extra")))
    ck("档位不够时抽不到（L2 条目在 sfw 档）",
       R.canon_level("sc_near_wet_cloth") == 2)
    # 「取消套用」= 面板 clearScene：字段权重回 1.0 + 选项袋清空。
    w2 = R.empty_weights()
    w2["fields"]["n_canon"] = 1.0
    w2["options"]["n_canon"] = {}
    hits2 = [R.draw(level="sfw", seed=s, weights=w2, base_prob=0.9)["state"].get("n_canon")
             for s in range(20)]
    ck("取消套用后不再命中（字段 1.0 + 选项袋清空）",
       not [x for x in hits2 if x == target], str(hits2[:3]))

    print("── ④ 零影响对拍：摘掉特写后输出必须全等 ──")
    # 前：现在（含 32 条 manual）
    h_with = digest(rounds)
    # 后：模拟 v3.17.2（库里没有 manual_only 条目）
    saved = R._CACHE.get("scenes")
    fake = copy.deepcopy(saved)
    fake["scenes"] = [s for s in fake["scenes"] if not s.get("manual_only")]
    R._CACHE["scenes"] = fake
    R._CACHE.pop("scene_index", None)
    R._CACHE.pop("canon_merged", None)
    h_without = digest(rounds)
    # 还原，别污染同进程后续检查
    R._CACHE["scenes"] = saved
    R._CACHE.pop("scene_index", None)
    R._CACHE.pop("canon_merged", None)
    ck("含/不含特写：输出 SHA256 全等（v3.17.2 行为未变）", h_with == h_without,
       f"{h_with[:16]} vs {h_without[:16]}")

    print("── ⑤ 载荷与自检 ──")
    nodes = _boot.load("nodes")
    sc = nodes.scenes_payload()
    ck("/scenes 的 counters.near == 60", sc["counters"]["near"] == 60,
       str(sc["counters"]))
    ck("/scenes 每条带 manual / part 字段",
       all("manual" in s and "part" in s for s in sc["scenes"]))
    ck("near_parts 顺序 = 库里书写顺序",
       sc["near_parts"] == [p for p in PARTS_EXPECT if p in sc["near_parts"]],
       str(sc["near_parts"]))
    ck("非特写条目的 part 为空（不与题材标签混用）",
       not [s["id"] for s in sc["scenes"] if not s["manual"] and s["part"]])
    pools = nodes.pools_payload()
    ncanon = None
    for sec in pools["sections"]:
        for f in sec["fields"]:
            if f["key"] == "n_canon":
                ncanon = f
    panel_ids = [o["en"] for o in (ncanon or {}).get("opts", [])]
    engine_ids = [en for _zh, en, _n in R.eligible_options("n_canon", 4)]
    manual_ids = [sid for _zh, sid, _n in R.manual_scene_options(4)]
    # v3.21.0：比集合不比列表 —— 面板按词库书写顺序列，引擎按档位/权重排序，
    #          两边内容与数量一致即可（姿势场景加入后顺序确实变了）。
    ck("/pools 候选 = 随机候选 + 特写搭配",
       len(panel_ids) == len(engine_ids) + len(manual_ids)
       and set(panel_ids) == set(engine_ids + manual_ids),
       f"{len(panel_ids)} vs {len(engine_ids)}+{len(manual_ids)}")
    warns = R.validate_weights(w)
    ck("合法 sc_* 选项不再被误报（v3.17.2 的假告警已修）", not warns, str(warns))
    bad = R.validate_weights({"sections": {}, "fields": {},
                              "options": {"n_canon": {"sc_not_exist": 2.0}}})
    ck("非法 id 仍然要报（不是把整类放过）", len(bad) == 1, str(bad))

    print("── ⑤之二 锁 role = 不自动抽角色（v3.18.0 补的机关）──")
    leak = []
    for sd in range(10):
        st = R.draw(level="sfw", seed=sd, locks={"role"}, base_prob=0.9)["state"]
        if st.get("role") or st.get("_role_count"):
            leak.append((sd, st.get("role"), st.get("_role_count")))
    ck("locks={'role'} 时一个角色 tag 都不出", not leak, str(leak[:3]))
    st_n = R.draw(level="sfw", seed=0, locks={"role"}, base_prob=0.9)
    ck("报告写明为什么没角色",
       any("角色字段已锁定" in n for n in st_n["notes"]), str(st_n["notes"][:4]))

    print("── ⑥ 关 ③ 段的实际效果（前端腿/脚/手组的依据）──")
    w3 = copy.deepcopy(w)
    w3["sections"]["face"] = 0.0
    leaked = []
    for s in range(15):
        st = R.draw(level="sfw", seed=s, weights=w3, base_prob=0.9)["state"]
        for k in ("emotion", "eye_gaze", "mouth", "eyes_color"):
            if st.get(k):
                leaked.append((s, k, st.get(k)))
    ck("③ 段权重 0 → 表情/眼神/嘴部/瞳色一个都不出", not leaked, str(leaked[:3]))
    # F10 要求"有角色就必须绑发色或瞳色"。③ 段关掉后 eyes_color 没了，
    # 但 ② 段仍开 → 外貌对齐会写 hair_color，F10 照样过。逐 seed 验一遍。
    f10_bad = []
    for s in range(6):
        rr = R.draw(level="sfw", seed=s, weights=w3, base_prob=0.9,
                    force_role="shinomiya kaguya, kaguya-sama: love is war")
        f10 = [x for x in rr["report"]["F"] if x.get("id") == "F10"]
        if not f10 or not f10[0].get("ok"):
            f10_bad.append((s, rr["state"].get("hair_color"), f10))
    ck("关 ③ 段后自检 F10 仍通过（发色由 ② 段与外貌对齐兜住）",
       not f10_bad, str(f10_bad[:2]))

    print("-" * 60)
    if FAILS:
        print(f"[check_v3_near] 失败 {len(FAILS)} 项：{FAILS}")
        return 1
    print(f"[check_v3_near] 通过：{len(near)} 条特写 · {rounds} seed/档 · 零影响对拍全等")
    return 0


if __name__ == "__main__":
    sys.exit(main())
