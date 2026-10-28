# -*- coding: utf-8 -*-
"""场景搭配预设库基线（v3.9.0）。

「一键设置场景搭配」= 把 姿势/场景/表情/动作 的固定组合一次套用，套用到的
字段不参与随机。它复用**法典场景那一套机制**（`canon()` 合并 → `apply_preset`
填充 → 档位/权重/锁定三闸门），所以这组基线要钉住的不只是"数据文件合法"，
而是**这条复用链路真的按预期工作**：

  ① 数据层   —— build_scenes --check 通过（派生档位与磁盘一致）、字段/选项真实存在、
                不得写 count/role、id 不与法典撞名。
  ② 合并层   —— canon() = 法典 14 组 + 场景 N 条；法典条目逐字节不变。
  ③ 闸门层   —— 按档位可用性正确（L0 抽不到 L2+ 的场景）；
                强制指定超档场景时 F15 必须报出来。
  ④ 应用层   —— 预设字段真的被写进 state；**被 trim 裁不掉**（"真固定"）。
  ⑤ 输出层   —— 预设 id **不出现在正文里**；同 seed 逐字节可复现。
  ⑥ 载荷层   —— /pools 的 n_canon 候选数与引擎一致；/scenes 的字段名有中文标签。

跑法：python tests/check_v3_scenes.py
"""
import os
import subprocess
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import _boot  # noqa: E402

R = _boot.load("anima_v4_rules")
BUILD = os.path.join(PLUGIN, "tools", "build_scenes.py")

FAILS = []


def ck(name, cond, note=""):
    if cond:
        print(f"  [OK] {name}")
    else:
        print(f"  [!!] {name}  {note}")
        FAILS.append(name)


def main():
    print("── ① 数据层：构建脚本校验 + 结构 ──")
    r = subprocess.run([sys.executable, BUILD, "--check"],
                       capture_output=True, text=True, cwd=PLUGIN)
    ck("build_scenes --check 通过（派生档位与磁盘一致）", r.returncode == 0,
       (r.stdout + r.stderr).strip().replace("\n", " | ")[:200])

    scenes = R.scene_list()
    ck("场景库非空", len(scenes) > 0, str(len(scenes)))
    ids = [s["id"] for s in scenes]
    ck("id 唯一", len(set(ids)) == len(ids))
    ck("id 一律以 sc_ 开头（与法典 c1..c14 区分）",
       all(i.startswith("sc_") for i in ids))
    canon_ids = set(R.pools().get("canon", {}).keys())
    ck("id 不与法典预设撞名", not (set(ids) & canon_ids),
       str(sorted(set(ids) & canon_ids)))

    forbidden = [(s["id"], k) for s in scenes for k in ("count", "role")
                 if k in (s.get("tags") or {})]
    ck("没有预设去写 count / role（人数与角色是地基）", not forbidden,
       str(forbidden[:3]))

    bad = []
    for s in scenes:
        for k, v in (s.get("tags") or {}).items():
            _sec, fld = R.field_by_key(k)
            if not fld or v not in [en for _zh, en in fld.get("opts", [])]:
                bad.append((s["id"], k, v))
    ck("每条预设的字段与取值都真实存在（写错=静默失效）", not bad, str(bad[:3]))

    by_group = {}
    for s in scenes:
        by_group[s["group"]] = by_group.get(s["group"], 0) + 1
    ck("分组齐全（sfw / nsfw 都有）",
       {"sfw", "nsfw"} <= set(by_group), str(by_group))

    # ── v3.21.0：姿势场景分组 ──────────────────────────────────
    pose = [s for s in scenes if s.get("group") == "pose"]
    ck("存在「姿势场景」分组（group=pose）", len(pose) >= 24, f"{len(pose)} 条")
    ck("姿势场景每条都写了 pose_base",
       all("pose_base" in (s.get("tags") or {}) for s in pose),
       str([s["id"] for s in pose if "pose_base" not in (s.get("tags") or {})][:3]))
    ck("姿势场景的 theme 以「姿势·」开头（面板角标可辨）",
       all(str(s.get("theme") or "").startswith("姿势·") for s in pose),
       str([s["id"] for s in pose if not str(s.get("theme") or "").startswith("姿势·")][:3]))
    pure = [s for s in pose if "place" not in (s.get("tags") or {})]
    ck("纯姿势型不锁地点（可套用在任何环境）", len(pure) >= 14, f"{len(pure)} 条")
    ck("完整造型型锁了地点", len(pose) - len(pure) >= 10, f"{len(pose) - len(pure)} 条")
    ck("姿势场景覆盖跪坐/正座类",
       any("seiza" in (s.get("tags") or {}).values() for s in pose))
    ck("姿势场景全部落在 SFW 档（L0/L1）",
       all(int(s["level"]) <= 1 for s in pose),
       str(sorted({int(s["level"]) for s in pose})))

    lv0 = [s["id"] for s in scenes if int(s["level"]) == 0]
    ck("存在全年龄档（L0）场景 —— SFW 一键搭配可用", len(lv0) >= 5,
       f"{len(lv0)} 条")

    # ── ①之二 人数钉死（v3.22.1）────────────────────────────────
    # 报障：场景写的 `n_act` 整段消失，肛交变群交、单人自慰变双人。
    # 根因是人数随机抽到多人 → 引擎清空单人向字段，而场景库没声明人数。
    # 这一组断言就是那次修复的护栏。
    locked = [s for s in scenes if s.get("count_lock")]
    ck("有 count_lock 的场景 ≥ 40 条（双人正戏 / 自慰 / 双女 / 群体）",
       len(locked) >= 40, str(len(locked)))
    ck("count 取值合法（不写空串、必须是 count 的选项原文）",
       all(s["count_lock"] in [en for _z, en in R.field_by_key("count")[1]["opts"]]
           for s in locked),
       str([s["id"] for s in locked
            if s["count_lock"] not in [en for _z, en in R.field_by_key("count")[1]["opts"]]][:3]))
    ck("count_lock 档位不高于条目档位（否则闸门会静默跳过）",
       all(R.option_level("count", s["count_lock"]) <= int(s["level"]) for s in locked),
       str([s["id"] for s in locked
            if R.option_level("count", s["count_lock"]) > int(s["level"])][:3]))
    # 引擎级：套用后人数必须变成声明值，且场景的 n_act / n_pos 不再被多人分支清空
    allids = [en for _z, en in R.field_by_key("n_canon")[1]["opts"]] + \
             [sid for _z, sid, _n in R.scene_options(99, include_manual=True)]
    bad_count, lost_act = [], []
    for s in locked:
        w = R.empty_weights()
        w["fields"]["n_canon"] = 3.0
        bag = {k: 0.0 for k in allids}; bag[s["id"]] = 3.0
        w["options"]["n_canon"] = bag
        lvk = {0: "sfw", 1: "suggestive", 2: "explicit",
               3: "hardcore", 4: "extreme"}[int(s["level"])]
        st = R.draw(level=lvk, seed=7, weights=w, base_prob=0.9)["state"]
        if st.get("count") != s["count_lock"]:
            bad_count.append((s["id"], st.get("count"), s["count_lock"]))
        for k in ("n_act", "n_pos", "n_theme"):
            if s["tags"].get(k) and not st.get(k):
                lost_act.append((s["id"], k, s["tags"][k]))
    # v3.22.3（用户口径）：非必要多人的场景一律一名女性
    nolock = [s["id"] for s in scenes
              if s.get("group") != "near" and not s.get("manual_only") and not s.get("count_lock")]
    ck("每条非特写场景都声明了人数（count_lock）", not nolock, str(nolock[:3]))
    MULTI_F = ("2girls, yuri", "multiple girls, orgy")
    # 必要多人白名单：双女互慰（2 女）+ RBQ 壁尻共用（群交，用户 2026-10-23 明确要求）
    # + v3.42.2 那批 L4 SM 场景（v3.42.7 起 9 条已改单人，只剩「双女对悬」一条 2girls，
    #   其余 id 保留登记：万一将来又被改成双女，不用再跑一次白名单）
    WHITE_MULTI = {"sc_msb_mutual", "sc_ccc_rbq_wall"} | {
        "sc_les_sm_suspension_pair", "sc_les_sm_suspension_twine",
        "sc_les_sm_pillory_duo", "sc_les_sm_wax_bound",
        "sc_les_sm_mutual_rope", "sc_les_sm_backtoback",
        "sc_les_sm_pet_leash", "sc_les_sm_collar_hold",
        "sc_les_sm_enema_bound", "sc_les_sm_clamp_pull"}
    # 特写里的「双女」组（舔阴 / 双女胸部 6 条）是必要多人，单独算，不参与这条
    bad_multi = [s["id"] for s in scenes
                 if s.get("count_lock") in MULTI_F and s["id"] not in WHITE_MULTI
                 and not s.get("manual_only")]
    ck("非特写场景里多女只在白名单（其余都是一名女性）", not bad_multi, str(bad_multi[:3]))
    ck("默认（sfw/pose）都是 1girl, solo",
       all(s["count_lock"] == "1girl, solo" for s in scenes
           if s.get("group") in ("sfw", "pose")),
       str([s["id"] for s in scenes if s.get("group") in ("sfw", "pose")
            and s["count_lock"] != "1girl, solo"][:3]))
    # ── v3.24.0：候选构图变体 / 贴地场景的相机禁令 ───────────────────
    pz = next((x for x in scenes if x["id"] == "sc_ccc_paizuri"), {})
    rv = pz.get("random_variants") or []
    ck("乳交有 2 个构图变体（我躺着 / 我坐着）",
       [v.get("zh") for v in rv] == ["我躺着", "我坐着"], str([v.get("zh") for v in rv]))
    wm = next((x for x in scenes if x["id"] == "sc_cam_worm_sit"), {})
    props = (wm.get("random_fields") or {}).get("prop") or []
    ck("贴地场景坐处候选 = 台阶 / 椅子 / 沙发",
       props == ["stairs", "chair", "couch"], str(props))
    # 相机禁令：device 闭麦 + 正文 20 抽不出现相机类词
    ck("贴地场景闭麦 device（selfie / 监控 这类会带出相机）",
       "device" in (wm.get("drop_fields") or []), str(wm.get("drop_fields")))
    BADW = ("camera", "selfie", "webcam", "photo", "phone", "dslr", "tripod")
    hit = []
    for sd in range(20):
        w20 = R.empty_weights()
        w20["fields"]["n_canon"] = 3.0
        ids20 = [en for _z, en in R.field_by_key("n_canon")[1]["opts"]] + \
                [x for _z, x, _n in R.scene_options(99, True)]
        bag20 = {k: 0.0 for k in ids20}; bag20["sc_cam_worm_sit"] = 3.0
        w20["options"]["n_canon"] = bag20
        txt = R.draw(level="suggestive", seed=7000 + sd, weights=w20, base_prob=0.9)["text"].lower()
        got = [b for b in BADW if b in txt]
        if got:
            hit.append((sd, got))
    # ── v3.26.0：雨中透衫回眸 —— 只剩一把伞的反面：一把都不要 ────────
    rw = next((x for x in scenes if x["id"] == "sc_rain_wetshirt"), {})
    ck("雨中透衫：不再有裸 umbrella 标签",
       "umbrella" not in str(rw.get("extra", "")).lower(), str(rw.get("extra"))[:80])
    ck("雨中透衫：闭麦 prop（prop 池里有 umbrella / parasol）",
       "prop" in (rw.get("drop_fields") or []), str(rw.get("drop_fields")))
    ck("雨中透衫：仍是擦边 L1（未被 wet clothes 之类抬档）",
       int(rw.get("level", -1)) == 1, str(rw.get("level")))
    UMB = ("umbrella", "parasol", "canopy")
    ubad, hand_bad = [], []
    for sd in range(20):
        w20 = R.empty_weights()
        w20["fields"]["n_canon"] = 3.0
        ids20 = [en for _z, en in R.field_by_key("n_canon")[1]["opts"]] + \
                [x for _z, x, _n in R.scene_options(99, True)]
        bag20 = {k: 0.0 for k in ids20}; bag20["sc_rain_wetshirt"] = 3.0
        w20["options"]["n_canon"] = bag20
        rr = R.draw(level="suggestive", seed=6500 + sd, weights=w20, base_prob=0.9)
        txt = rr["text"].lower()
        if any(b in txt for b in UMB):
            ubad.append(sd)
        if rr["state"].get("pose_risque") != "hair flip":
            hand_bad.append((sd, rr["state"].get("pose_risque"),
                             rr["state"].get("arms_hands")))
    ck("雨中透衫：20 抽正文零伞类词（不再出现凭空第二把）", not ubad, str(ubad[:3]))
    # ── v3.27.0：护士查房（多池变体：姿势 × 道具）──────────────────
    nu = next((x for x in scenes if x["id"] == "sc_nurse_rounds"), {})
    pools = R.scene_random_variants("sc_nurse_rounds")
    ck("护士查房：变体是多池（姿势 + 道具两个池）",
       [p["key"] for p in pools] == ["pose", "tool"], str([p["key"] for p in pools]))
    ck("护士查房：姿势池 5 个、道具池 4 个（含空手）",
       [len(p["items"]) for p in pools] == [5, 4], str([len(p["items"]) for p in pools]))
    ck("护士查房：道具池里有「空手」（用户口径：可以不拿东西）",
       any(it["zh"] == "空手" for it in pools[1]["items"]),
       str([it["zh"] for it in pools[1]["items"]]))
    ck("护士查房：闭麦 prop / pose_base / arms_hands（会与姿势和持物打架）",
       all(k in (nu.get("drop_fields") or []) for k in ("prop", "pose_base", "arms_hands")),
       str(nu.get("drop_fields")))
    # 乳交是单池写法，扩成多池后必须仍然只返回 1 个池
    pz_pools = R.scene_random_variants("sc_ccc_paizuri")
    ck("单池写法（数组）仍解析为 1 个池",
       len(pz_pools) == 1 and len(pz_pools[0]["items"]) == 2, str(len(pz_pools)))
    TOOLS = ("clipboard", "stethoscope", "medical tray")
    JUNK = ("ice cream", "wine glass", "cake", "balloon", "parasol", "umbrella")
    multi, junk, empty_cnt = [], [], 0
    for sd in range(20):
        w20 = R.empty_weights()
        w20["fields"]["n_canon"] = 3.0
        ids20 = [en for _z, en in R.field_by_key("n_canon")[1]["opts"]] + \
                [x for _z, x, _n in R.scene_options(99, True)]
        bag20 = {k: 0.0 for k in ids20}; bag20["sc_nurse_rounds"] = 3.0
        w20["options"]["n_canon"] = bag20
        txt = R.draw(level="suggestive", seed=7400 + sd, weights=w20, base_prob=0.9)["text"].lower()
        n_tool = sum(1 for t in TOOLS if t in txt)
        if n_tool > 1:
            multi.append((sd, n_tool))
        if n_tool == 0:
            empty_cnt += 1
        if any(b in txt for b in JUNK):
            junk.append(sd)
    ck("护士查房：20 抽手里至多一件道具（含空手，不会两件以上）", not multi, str(multi[:3]))
    # 空手是 1/4 概率；20 抽里既不能一次不出（说明池没接上），也不该占多数
    ck("护士查房：空手能抽到、但不是多数（1–12 / 20）", 1 <= empty_cnt <= 12,
       f"{empty_cnt}/20")
    # ── v3.27.2：偷窥场景 —— 画面内不出现相机与监控 UI ──────────────
    vo = next((x for x in scenes if x["id"] == "sc_ccc_voyeur_cam"), {})
    ck("偷窥场景：extra 不再含 camera（裸名词会要求把机器画进来）",
       "camera" not in str(vo.get("extra", "")).lower(), str(vo.get("extra"))[:80])
    ck("偷窥场景：tags 不再有 device（security camera footage 会带监控 UI）",
       "device" not in (vo.get("tags") or {}), str((vo.get("tags") or {}).get("device")))
    ck("偷窥场景：闭麦 device / prop / n_cum",
       all(k in (vo.get("drop_fields") or []) for k in ("device", "prop", "n_cum")),
       str(vo.get("drop_fields")))
    VPS = ["from above", "from side", "from behind", "dutch angle", "framed by foreground"]
    ck("偷窥场景：机位 5 选 1（俯视 / 平视 / 背后 / 斜角 / 前景框住）",
       (vo.get("random_fields") or {}).get("viewpoint") == VPS,
       str((vo.get("random_fields") or {}).get("viewpoint")))
    CAM = ("camera", "footage", "cctv", "webcam", "tripod")
    cam_hit, vp_seen = [], set()
    for sd in range(40):
        w20 = R.empty_weights()
        w20["fields"]["n_canon"] = 3.0
        ids20 = [en for _z, en in R.field_by_key("n_canon")[1]["opts"]] + \
                [x for _z, x, _n in R.scene_options(99, True)]
        bag20 = {k: 0.0 for k in ids20}; bag20["sc_ccc_voyeur_cam"] = 3.0
        w20["options"]["n_canon"] = bag20
        rr = R.draw(level="explicit", seed=6600 + sd, weights=w20, base_prob=0.9)
        txt = rr["text"].lower()
        vp_seen.add(rr["state"].get("viewpoint") or "")
        cam_hit += [(sd, b) for b in CAM if b in txt]
    ck("偷窥场景：40 抽正文零相机类词", not cam_hit, str(cam_hit[:3]))
    # ── v3.29.0：第三人称·俯视（原「第一人称·俯视自身」改名）/ 新「第一人称·俯视自身」──
    t3 = next((x for x in scenes if x["id"] == "sc_ccc_pov_crotch_self"), {})
    ck("改名：sc_ccc_pov_crotch_self 现在叫「第三人称 · 俯视」",
       t3.get("zh") == "第三人称 · 俯视", str(t3.get("zh")))
    ck("改名：内容同步成第三人称（viewpoint=from above，不含 pov）",
       (t3.get("tags") or {}).get("viewpoint") == "from above"
       and "pov" not in str(t3.get("tags")).lower(),
       str((t3.get("tags") or {}).get("viewpoint")))
    ck("改名：extra 不再有 first-person / own body",
       "first-person" not in str(t3.get("extra", "")).lower()
       and "own body" not in str(t3.get("extra", "")).lower(), str(t3.get("extra"))[:80])
    ck("改名：闭麦 n_act / n_pos / prop（避免 handjob、bent over、卧室杂货）",
       all(k in (t3.get("drop_fields") or []) for k in ("n_act", "n_pos", "prop")),
       str(t3.get("drop_fields")))

    t1 = next((x for x in scenes if x["id"] == "sc_ccc_pov_self_body"), {})
    ck("新增：存在「第一人称 · 俯视自身」", t1.get("zh") == "第一人称 · 俯视自身", str(t1.get("zh")))
    ck("新增：是第一人称（viewpoint=pov crotch）+ 情色 L2",
       (t1.get("tags") or {}).get("viewpoint") == "pov crotch" and int(t1.get("level", -1)) == 2,
       f"{t1.get('level')} / {(t1.get('tags') or {}).get('viewpoint')}")
    ck("新增：画框写明低头看自己、脸不入画、近大远小",
       all(k in str(t1.get("extra", "")).lower()
           for k in ("looking down along own body", "foreshortening", "head out of frame")),
       str(t1.get("extra"))[:100])
    ck("新增：写死景别与乳头（画面只到乳头与下半身）",
       (t1.get("tags") or {}).get("shot_size") == "extreme close-up"
       and (t1.get("tags") or {}).get("n_exposure") == "nipples",
       str({k: (t1.get("tags") or {}).get(k) for k in ("shot_size", "n_exposure")}))

    # ── v3.38.9（用户 2026-10-24）：「第一人称 · 口交」→「第三人称 · 口交」──
    # 报障：场景库里的口交条目是第一人称（pov, fellatio），且姿势完全没写，
    # 出图时会看到"自己视角 + 自己的身体"，与场景搭配（第三人称）语义不符。
    t2 = next((x for x in scenes if x["id"] == "sc_ccc_pov_oral"), {})
    ck("改名：sc_ccc_pov_oral 现在叫「第三人称 · 口交」",
       t2.get("zh") == "第三人称 · 口交", str(t2.get("zh")))
    ck("改名：viewpoint 从 pov, fellatio 改成 from side（不含 pov）",
       (t2.get("tags") or {}).get("viewpoint") == "from side"
       and "pov" not in str(t2.get("tags")).lower(),
       str((t2.get("tags") or {}).get("viewpoint")))
    ck("改名：主题从「第一人称」并入「双人正戏」",
       t2.get("theme") == "双人正戏", str(t2.get("theme")))
    ck("姿势合理：她跪、身体前倾、双腿之间、手扶腿",
       (t2.get("tags") or {}).get("pose_base") == "kneeling"
       and (t2.get("tags") or {}).get("pose_risque") == "leaning forward"
       and all(k in str(t2.get("extra")) for k in ("fellatio", "between legs", "hands on thighs")),
       str((t2.get("tags") or {}).get("pose_base")) + " / " + str(t2.get("extra")))
    ck("姿势合理：extra 不再有 first-person view",
       "first-person" not in str(t2.get("extra")).lower(), str(t2.get("extra"))[:80])
    ck("闭麦会破坏第三人称/姿势的字段（device/n_act/n_pos/n_exposure/arms_hands/n_cum）",
       all(k in (t2.get("drop_fields") or [])
           for k in ("device", "n_act", "n_pos", "n_exposure", "arms_hands", "n_cum")),
       str(t2.get("drop_fields")))
    # 引擎级：30 抽 —— 机位恒定、零 pov、零 presenting、人数恒 1girl,1boy,hetero
    _vp, _bad, _cnt = Counter(), [], Counter()
    for _sd in range(30):
        _res = R.draw(level=int(t2.get("level", 3)), seed=_sd, forced={"n_canon": t2["id"]})
        _toks = {x.strip() for x in _res["text"].split(",")}
        _vp[_res["state"].get("viewpoint") or ""] += 1
        _cnt[_res["state"].get("count") or ""] += 1
        if {"pov", "presenting", "first-person view"} & _toks:
            _bad.append(_sd)
    ck("第三人称口交：30 抽机位恒 from side、零 pov / presenting",
       set(_vp) == {"from side"} and not _bad, f"{dict(_vp)} / bad={_bad[:3]}")
    ck("第三人称口交：30 抽人数恒 1girl, 1boy, hetero",
       set(_cnt) == {"1girl, 1boy, hetero"}, str(dict(_cnt)))

    # ── v3.39.0（用户 2026-10-24）：新增「远景」主题 12 条 ──
    # 报障：全库 218 条里只有 1 条 wide shot（占 0.5%），近景/特写合计 50%，
    # 远景是完全空白的一档。12 条全 SFW / L0，写法 = wide shot + scenery +
    # landscape/negative space + 大场景 place + distant figure（竖屏下能压到最小）。
    wide = [x for x in scenes if x["id"].startswith("sc_wide_")]
    # v3.39.1：再补 4 条「回眸」→ 12 + 4 = 16
    ck("新增远景 16 条（12 常规 + 4 回眸）", len(wide) == 16, str(len(wide)))
    ck("远景全部在 sfw 组 + 主题为「远景」",
       all(x["group"] == "sfw" and x.get("theme") == "远景" for x in wide),
       str([(x["id"], x["group"], x.get("theme")) for x in wide]))
    ck("远景全部 L0（只做安全内容）", all(int(x["level"]) == 0 for x in wide),
       str([(x["id"], x["level"]) for x in wide]))
    ck("远景全部写死 wide shot",
       all((x.get("tags") or {}).get("shot_size") == "wide shot" for x in wide),
       str([(x["id"], (x.get("tags") or {}).get("shot_size")) for x in wide]))
    ck("远景全部钉 1girl, solo（多人会稀释'人在远处'的效果）",
       all(x.get("count_lock") == "1girl, solo" for x in wide),
       str([(x["id"], x.get("count_lock")) for x in wide]))
    # dof 一律闭麦（`focus on face` 与远景互斥）；action 只对非回眸条目闭麦 ——
    # 回眸那 4 条把 `action=looking back` 写死在 tags 里，再闭麦就自相矛盾了
    ck("远景全部闭麦 dof（focus on face 与远景互斥）",
       all("dof" in (x.get("drop_fields") or []) for x in wide),
       str([(x["id"], x.get("drop_fields")) for x in wide]))
    ck("非回眸条目闭麦 action（否则会抽到喝水/吃东西）",
       all("action" in (x.get("drop_fields") or [])
           for x in wide if not x["id"].endswith("_lookback")),
       str([(x["id"], x.get("drop_fields")) for x in wide if "action" not in (x.get("drop_fields") or [])]))
    ck("远景 extra 都带 scenery + distant figure",
       all("scenery" in str(x.get("extra")) and "distant figure" in str(x.get("extra"))
           for x in wide),
       str([x["id"] for x in wide if "distant figure" not in str(x.get("extra"))]))
    ck("远景覆盖 16 个不同 place（不重复取景地）",
       len({(x.get("tags") or {}).get("place") for x in wide}) == 16,
       str(sorted({(x.get("tags") or {}).get("place") for x in wide})))
    # 回眸 4 条：走 action=looking back + eye_gaze=looking back + from behind，
    # 三个字段一起写才稳定（只写 action 时模型经常只转肩不回头）
    _lb = [x for x in wide if x["id"].endswith("_lookback")]
    ck("远景里有 4 条回眸", len(_lb) == 4, str(len(_lb)))
    ck("回眸条目三个字段齐全（from behind / looking back / looking back）",
       all((x.get("tags") or {}).get("viewpoint") == "from behind"
           and (x.get("tags") or {}).get("action") == "looking back"
           and (x.get("tags") or {}).get("eye_gaze") == "looking back" for x in _lb),
       str([(x["id"], (x.get("tags") or {}).get("action")) for x in _lb]))
    ck("回眸条目 extra 写 looking back over shoulder（动作落点）",
       all("looking back over shoulder" in str(x.get("extra")) for x in _lb),
       str([x["id"] for x in _lb]))
    # 引擎级：每条各抽 1 次，景别必须真是 wide shot
    _wrong = []
    for x in wide:
        _st = R.draw(level=0, seed=7, forced={"n_canon": x["id"]})["state"]
        if _st.get("shot_size") != "wide shot":
            _wrong.append((x["id"], _st.get("shot_size")))
    ck("远景 16 条实抽景别恒 wide shot", not _wrong, str(_wrong))

    # ── v3.39.2（用户 2026-10-24）：雪原条目改成"冬季叠穿" ──
    # 报障：雪原里人物穿短裤/薄袜/凉鞋，与季节完全不符（outfit 随机抽到泳装也不奇怪）。
    _snow = next((x for x in wide if x["id"] == "sc_wide_snow_field"), {})
    _st = _snow.get("tags") or {}
    ck("雪原写死长裙 + 连裤袜 + 长靴 + 围巾 + 针织",
       _st.get("bottom") == "long skirt" and _st.get("socks") == "pantyhose"
       and _st.get("shoes") == "knee boots" and _st.get("accessory") == "scarf"
       and _st.get("cloth_mat") == "knitwear", str(_st))
    _WINTER_TOPS = {"coat", "down jacket", "fur-trimmed coat", "fur coat", "fur collar"}
    ck("雪原外套只在冬装池里抽（5 种：大衣/羽绒/毛边/毛皮/毛领）",
       set((_snow.get("random_fields") or {}).get("top") or []) == _WINTER_TOPS,
       str((_snow.get("random_fields") or {}).get("top")))
    ck("雪原闭麦 outfit（整身套装会和上面的冬装打架）",
       "outfit" in (_snow.get("drop_fields") or []), str(_snow.get("drop_fields")))
    ck("雪原 extra 写明 winter clothes / layered / long coat / maxi skirt",
       all(k in str(_snow.get("extra")) for k in ("winter clothes", "layered clothes",
                                                  "long coat", "maxi skirt")),
       str(_snow.get("extra"))[:110])
    # 引擎级：20 抽 —— 外套必须在冬装池内、下装恒长裙、且不出现夏装/泳装
    _SUMMER = {"bikini", "one-piece swimsuit", "shorts", "short shorts", "denim shorts",
               "sandals", "bare feet", "miniskirt", "tank top", "sleeveless shirt",
               "tube top", "camisole", "sundress", "high heels"}
    _bad_top, _bad_bot, _bad_summer = [], [], []
    for _sd in range(20):
        _r = R.draw(level=0, seed=_sd, forced={"n_canon": "sc_wide_snow_field"})
        if _r["state"].get("top") not in _WINTER_TOPS:
            _bad_top.append((_sd, _r["state"].get("top")))
        if _r["state"].get("bottom") != "long skirt":
            _bad_bot.append((_sd, _r["state"].get("bottom")))
        _toks = {x.strip() for x in _r["text"].split(",")}
        if _SUMMER & _toks:
            _bad_summer.append((_sd, sorted(_SUMMER & _toks)))
    ck("雪原 20 抽外套恒在冬装池", not _bad_top, str(_bad_top[:3]))
    ck("雪原 20 抽下装恒 long skirt", not _bad_bot, str(_bad_bot[:3]))
    ck("雪原 20 抽不出现夏装/泳装/光腿类标签", not _bad_summer, str(_bad_summer[:3]))
    # v3.33.0（用户口径：「增加更多姿势，不再固定为躺姿」）：
    # 姿势从"锁死 on back"放开成 5 选 1 —— 但**只放实测能出第一人称的那几种**。
    # 站 / 坐直 / 跪 三种实测都会变成「从上方俯拍她」（站着那张还会把整张脸带进来），
    # 所以池子里只有仰躺 / 侧躺 / 坐起 / 屈膝 / 盘腿。
    ck("俯视自身：姿势 3 选 1（仰躺/侧躺/屈膝）",
       (t1.get("random_fields") or {}).get("pose_base")
       == ["on back", "on side", "knees up"],
       str((t1.get("random_fields") or {}).get("pose_base")))
    ck("俯视自身：姿势不再写死在 tags 里", "pose_base" not in (t1.get("tags") or {}),
       str((t1.get("tags") or {}).get("pose_base")))
    ck("新增：闭麦 n_cum / n_act（单人无第二人，且与明确自慰分层）",
       all(k in (t1.get("drop_fields") or []) for k in ("n_cum", "n_act")),
       str(t1.get("drop_fields")))
    # ⚠️ v3.32.1：`first-person view` 会把画面变成「手机第一人称拍摄」——
    #    实测这个模型必然补上 HDR / 对焦框 / 录像按钮 / 日文菜单，
    #    正向换 8 种措辞（pov / from above / close-up / 双手空着 / 插画风 /
    #    提高 cfg / 加 UI 负词）全部无效。第一人称语义交给 `pov crotch`
    #    + `looking down along own body` + `foreshortening` 就够。
    ck("俯视自身：正文不写 first-person view（它会带出相机 UI）",
       "first-person view" not in str(t1.get("extra", "")).lower(),
       str(t1.get("extra"))[:100])
    # ⚠️ `traditional media` 是实测唯一能压住相机 UI 的词：它把画面拉回"画出来的"
    #    而不是"拍出来的"。但**光有它还不够** —— 手部动作进来之后 UI 又回到约 1/4，
    #    要再加 `painted style`（不是 `painting`：那个会把"墙上的画"真的画出来，
    #    而且画里常是裸女像；`painted texture` 会变厚涂、`canvas texture` 无效、
    #    `comic, manga panel` 会直接出三格分镜）。
    ck("俯视自身：带 traditional media + painted style（压掉相机 UI 的有效组合）",
       "traditional media" in str(t1.get("extra", "")).lower()
       and "painted style" in str(t1.get("extra", "")).lower(),
       str(t1.get("extra"))[-60:])
    ck("俯视自身：不用 painting（它会把墙上的画真的画出来）",
       "painting" not in str(t1.get("extra", "")).lower(),
       str(t1.get("extra"))[-60:])

    # v3.33.0（用户口径：「手部增加更多动作例如按摩胸部、抚摸生殖器等」）：
    # `arms_hands` 字段的 20 个选项里根本没有这类动作（全是叉腰 / 比耶 / 敬礼），
    # 所以走 `random_variants` 的自由短语池 —— 与姿势字段正交，各自独立抽。
    _rv = t1.get("random_variants") or {}
    _hand = (_rv.get("hand") or {}).get("items") or []
    _hand_ex = [str(x.get("extra", "")).lower() for x in _hand]
    ck("俯视自身：手部动作池 8 条（字段里的 20 个通用手部姿势做不到这些）",
       len(_hand) == 8, str(len(_hand)))
    ck("俯视自身：手部动作含「揉胸」与「抚摸生殖器」两类",
       any(("kneading her own breast" in x) or ("massaging her breast" in x) or
           ("cupping her breast" in x) for x in _hand_ex)
       and any(("rubbing her pussy" in x) or ("spreading her pussy" in x) or
               ("inside her pussy" in x) for x in _hand_ex),
       str(_hand_ex))
    # v3.33.0（用户追加口径「优先保证是人物自身视角」）：
    # **双手同时在胸上**会被画成「对面有个人在揉她」（实测 f_8 / g1 / h4 全部跑成第三人称正面），
    # 所以手部池一律单手或手指动作。
    ck("俯视自身：手部动作不含「双手同时」的动作（会变成对面视角）",
       not any("both hands" in x for x in _hand_ex), str(_hand_ex))
    ck("俯视自身：`arms_hands` 仍然闭麦（两套手部指令会打架）",
       "arms_hands" in (t1.get("drop_fields") or []), str(t1.get("drop_fields")))

    # ── v3.32.0：第一人称 · 俯视自身 = **代入本体视角**，正文不得有面部特征 ──
    # 用户口径（2026-10-23）：「视角是代入人物视角，提示词内应该没有人物面部特征，
    # 然后以自己视角看自己身体才对。」所以这条要钉的不是"字段长什么样"，而是
    # **抽 40 次正文里一个面部/头发标签都不许出现**，且不许冒出角色名
    # （角色 tag 会把镜头从"自己的身体"拉回一张脸）。
    FACE_FIELDS = ["eyes_color", "emotion", "eye_gaze", "mouth", "makeup",
                   "hair_len", "hair_color", "hair_curl", "hair_tie",
                   "hair_bangs", "hair_fx", "hair_acc"]
    ck("俯视自身：闭麦全部面部 / 头发字段",
       all(k in (t1.get("drop_fields") or []) for k in FACE_FIELDS),
       str([k for k in FACE_FIELDS if k not in (t1.get("drop_fields") or [])]))
    ck("俯视自身：tags 里不再写眼神（eye_gaze=looking down 本身就是面部）",
       "eye_gaze" not in (t1.get("tags") or {}),
       str((t1.get("tags") or {}).get("eye_gaze")))
    ck("俯视自身：声明 no_role（不写角色名，否则镜头会被拉回脸）",
       t1.get("no_role") is True, str(t1.get("no_role")))
    _bad = set()
    for _k in FACE_FIELDS:
        for _zh, _en in (R.field_by_key(_k)[1].get("opts") or []):
            _bad.add(_en.lower())
    _leak, _roles = [], []
    for sd in range(40):
        rr = R.draw(level="explicit", seed=6800 + sd, weights=R.empty_weights(),
                    base_prob=0.9, forced={"n_canon": "sc_ccc_pov_self_body"})
        _toks = [x.strip().lower() for x in rr["text"].split(",")]
        _hit = [x for x in _toks if x in _bad]
        if _hit:
            _leak.append((sd, _hit))
        if rr["state"].get("role"):
            _roles.append((sd, rr["state"]["role"]))
    ck("俯视自身：40 抽零面部/头发标签泄漏", not _leak, str(_leak[:3]))
    ck("俯视自身：40 抽零角色名（no_role 在引擎侧真的生效）", not _roles, str(_roles[:3]))
    # ── v3.30.0：镜前检视 —— 手部固定为「双手掰开展示」─────────────
    mc = next((x for x in scenes if x["id"] == "sc_msb_mirror_check"), {})
    mct = mc.get("tags") or {}
    ck("镜前检视：不再把 arms_hands 钉在「手在头发里」",
       "arms_hands" not in mct, str(mct.get("arms_hands")))
    ck("镜前检视：闭麦 arms_hands / n_act / n_cum（手部与单人向）",
       all(k in (mc.get("drop_fields") or []) for k in ("arms_hands", "n_act", "n_cum")),
       str(mc.get("drop_fields")))
    ck("镜前检视：extra 写死双手掰开",
       all(k in str(mc.get("extra", "")).lower()
           for k in ("spread pussy", "two hands spreading", "both hands between her legs")),
       str(mc.get("extra"))[:90])
    ck("镜前检视：`legs apart` 换成 n_pos 的 `spread legs`（原来那个属 pose_base，会打架）",
       mct.get("n_pos") == "spread legs" and "legs apart" not in str(mc.get("extra", "")),
       f"{mct.get('n_pos')} / {str(mc.get('extra'))[:60]}")
    ck("镜前检视：姿势只剩坐 / 跪 / 正座",
       (mc.get("random_fields") or {}).get("pose_base") == ["sitting", "kneeling", "seiza"],
       str((mc.get("random_fields") or {}).get("pose_base")))
    mc_ok, mc_bad, mc_pose = 0, [], set()
    for sd in range(20):
        w20 = R.empty_weights()
        w20["fields"]["n_canon"] = 3.0
        ids20 = [en for _z, en in R.field_by_key("n_canon")[1]["opts"]] + \
                [x for _z, x, _n in R.scene_options(99, True)]
        bag20 = {k: 0.0 for k in ids20}; bag20["sc_msb_mirror_check"] = 3.0
        w20["options"]["n_canon"] = bag20
        rr = R.draw(level="explicit", seed=6700 + sd, weights=w20, base_prob=0.9)
        t = rr["text"].lower()
        mc_pose.add(rr["state"].get("pose_base") or "")
        if "spread pussy" in t and "two hands spreading" in t:
            mc_ok += 1
        mc_bad += [(sd, b) for b in ("anilingus", "cum string", "creampie", "handjob")
                   if b in t]
    ck("镜前检视：20 抽全部带「双手掰开」", mc_ok == 20, f"{mc_ok}/20")
    ck("镜前检视：20 抽零双人向词（单人场景）", not mc_bad, str(mc_bad[:3]))
    ck("镜前检视：姿态只在坐 / 跪 / 正座之内",
       mc_pose <= {"sitting", "kneeling", "seiza"}, str(sorted(mc_pose)))

    # ── v3.33.0：束缚 · 口球垂涎 —— 画面里只能有她一个人 ────────────────
    # 用户口径（2026-10-23）：「继续更新束缚 · 口球垂涎场景保证画面只有一人。」
    # 原来这条挂的是 `1girl, 1boy, hetero`，且 `n_act` / `n_pos` / `n_orgasm` 照抽 ——
    # 实测正文里会出现 `cum on breasts` / `mating press` / `against wall, sex` / `after sex`，
    # 模型一定画第二个人。改成单人自缚后要钉住四件事：
    # ① 人数钉死 `1girl, solo`；② 双人向字段全部闭麦；
    # ③ 机位不许走 `pov` 系（`pov, cowgirl position` 这类会直接带出第二个人）；
    # ④ 眼神不许 `looking at another`。
    g = next((x for x in scenes if x["id"] == "sc_ccc_bdsm_gag"), {})
    ck("口球：人数钉死 1girl, solo（原来是 1girl, 1boy, hetero）",
       g.get("count_lock") == "1girl, solo", str(g.get("count_lock")))
    ck("口球：闭麦双人向字段 n_act / n_cum / n_pos / n_orgasm",
       all(k in (g.get("drop_fields") or []) for k in ("n_act", "n_cum", "n_pos", "n_orgasm")),
       str([k for k in ("n_act", "n_cum", "n_pos", "n_orgasm")
            if k not in (g.get("drop_fields") or [])]))
    ck("口球：机位只在单人机位里选（不含 pov 系）",
       all("pov" not in v for v in ((g.get("random_fields") or {}).get("viewpoint") or ["x"])),
       str((g.get("random_fields") or {}).get("viewpoint")))
    ck("口球：眼神不含 looking at another",
       "looking at another" not in ((g.get("random_fields") or {}).get("eye_gaze") or []),
       str((g.get("random_fields") or {}).get("eye_gaze")))
    _gbad = []
    for sd in range(40):
        rr = R.draw(level="hardcore", seed=6900 + sd, weights=R.empty_weights(),
                    base_prob=0.9, forced={"n_canon": "sc_ccc_bdsm_gag"})
        _t = rr["text"].lower()
        _h = [w for w in ("1boy", "hetero", "penis", "cum", "fellatio", "handjob",
                          "mating", "boy", "another", "pov") if w in _t]
        if _h:
            _gbad.append((sd, _h))
    ck("口球：40 抽零双人词 / 零 pov 机位", not _gbad, str(_gbad[:3]))

    # ── v3.34.0：异种 · 触手 —— 束缚感 + 高潮表情 + 触手入口（概率）──────
    # 用户口径（2026-10-23）：「使人物状态更有被束缚感等符合场景的表情与状态，
    # 并且有概率使触手插入口部。」随后追加：「口球不要加入到提示词内了。」
    # ⚠️ 最后这条是关键教训：`tentacle gag` 会被画成一根触手**横穿嘴巴**（就是口球的样子），
    #    要"伸进嘴里"反而得用 `tentacle in her mouth, oral, deepthroat`（实测才会含着）。
    tt = next((x for x in scenes if x["id"] == "sc_ccc_tentacle"), {})
    _trv = tt.get("random_variants") or {}
    _bind = (_trv.get("bind") or {}).get("items") or []
    _mouth = (_trv.get("mouth") or {}).get("items") or []
    ck("触手：束缚方式 3 选 1（双手吊起 / 手臂反绑 / 缠满全身）",
       len(_bind) == 3, str([i.get("zh") for i in _bind]))
    ck("触手：口部 3 选 1（贴脸 / 绕颈 / 入口，约 1/3 概率）",
       len(_mouth) == 3, str([i.get("zh") for i in _mouth]))
    ck("触手：口部池里一定有一条「触手入口」",
       any("in her mouth" in str(i.get("extra", "")).lower() for i in _mouth),
       str([i.get("extra") for i in _mouth]))
    # ⚠️ 用户明确「口球不要加入到提示词内」—— 正文与变体里都不许出现 gag 类词。
    ck("触手：全程不出现 gag 类词（会被画成口球）",
       "gag" not in str(tt.get("extra", "")).lower()
       and not any("gag" in str(i.get("extra", "")).lower() for i in _mouth),
       str([i.get("extra") for i in _mouth]))
    ck("触手：高潮状态改成随机（不再写死 body writhe）",
       set(((tt.get("random_fields") or {}).get("n_orgasm") or []))
       == {"body writhe", "orgasm, trembling", "ahegao, rolled back eyes",
           "mind break", "moaning", "aroused"},
       str((tt.get("random_fields") or {}).get("n_orgasm")))
    ck("触手：表情限定在失控 / 受惊一侧（不含 embarrassed 那种从容）",
       set(((tt.get("random_fields") or {}).get("emotion") or []))
       == {"tears", "crying", "scared", "surprised"},
       str((tt.get("random_fields") or {}).get("emotion")))
    _tbad = []
    for sd in range(30):
        rr = R.draw(level="hardcore", seed=6950 + sd, weights=R.empty_weights(),
                    base_prob=0.9, forced={"n_canon": "sc_ccc_tentacle"})
        _t = rr["text"].lower()
        _h = [w for w in ("1boy", "hetero", "gag", "fellatio", "handjob") if w in _t]
        if _h:
            _tbad.append((sd, _h))
    ck("触手：30 抽零双人词 / 零 gag 词", not _tbad, str(_tbad[:3]))

    # ── v3.34.0：事后 · 余韵 —— 画面里只有她一个人 ────────────────────
    # 用户口径（2026-10-23）：「顺便更新事后 · 余韵场景，保证只有一人出现在画面中。」
    # 原来挂的是 `1girl, 1boy, hetero`；另外两个隐藏入口：`viewpoint` 的
    # `pov, cowgirl position` 与 `eye_gaze` 的 `looking at another`。
    ag = next((x for x in scenes if x["id"] == "sc_ccc_afterglow"), {})
    _agrf = ag.get("random_fields") or {}
    ck("余韵：人数钉死 1girl, solo（原来是 1girl, 1boy, hetero）",
       ag.get("count_lock") == "1girl, solo", str(ag.get("count_lock")))
    ck("余韵：闭麦双人向字段 n_act / n_pos / pose_risque",
       all(k in (ag.get("drop_fields") or []) for k in ("n_act", "n_pos", "pose_risque")),
       str(ag.get("drop_fields")))
    ck("余韵：机位限定单人机位（不含 pov 系）",
       all("pov" not in v for v in (_agrf.get("viewpoint") or ["x"])),
       str(_agrf.get("viewpoint")))
    ck("余韵：眼神不含 looking at another",
       "looking at another" not in (_agrf.get("eye_gaze") or []),
       str(_agrf.get("eye_gaze")))
    # v3.34.1（用户口径：「保证能够出现中景画面的各种姿势全身照」）：
    # 景别从"只拍脸"放开到 **cowboy shot / full body**，姿势 6 选 1；
    # 同时 `dof` 必须离开 `focus on face` —— 焦点钉在脸上会把镜头一路拉回特写，
    # 全身照根本不成立（实测就是这么失败的）。
    ck("余韵：景别只在中景/全身里选（cowboy shot / full body）",
       set(_agrf.get("shot_size") or []) == {"cowboy shot", "full body"},
       str(_agrf.get("shot_size")))
    ck("余韵：姿势 6 选 1（侧躺/仰躺/俯卧/坐起/蜷缩/屈膝）",
       set(_agrf.get("pose_base") or [])
       == {"on side", "on back", "on stomach", "sitting", "fetal position", "knees up"},
       str(_agrf.get("pose_base")))
    ck("余韵：dof 不再钉 focus on face（它会把镜头拉回脸）",
       "focus on face" not in (_agrf.get("dof") or [])
       and "dof" not in (ag.get("tags") or {}),
       f"{_agrf.get('dof')} / {(ag.get('tags') or {}).get('dof')}")
    ck("余韵：机位去掉 from behind（事后余韵要看得见表情）",
       "from behind" not in (_agrf.get("viewpoint") or []),
       str(_agrf.get("viewpoint")))
    _abad, _empty_shot, _poses = [], 0, set()
    for sd in range(60):
        rr = R.draw(level="hardcore", seed=6980 + sd, weights=R.empty_weights(),
                    base_prob=0.9, forced={"n_canon": "sc_ccc_afterglow"})
        _t = rr["text"].lower()
        _toks = {x.strip().lower() for x in _t.split(",")}
        _h = [w for w in ("1boy", "hetero", "penis", "cum in", "another", "pov") if w in _t]
        if _h:
            _abad.append((sd, _h))
        if not rr["state"].get("shot_size"):
            _empty_shot += 1
        _poses.add(rr["state"].get("pose_base"))
    ck("余韵：60 抽零双人词 / 零 pov", not _abad, str(_abad[:3]))
    # ⚠️ v3.34.1 引擎修复的回归断言：`trim_to_cap` 以前只保护 `canon()` 里的
    #    tags 字段，**不含 random_fields** —— 密度超限时「景别·全身」会被当软字段削掉，
    #    正文里只剩 `depth of field` 没有 `full body`，用户看到的是"选了全身照却出特写"。
    #    现在 `_preset_fields` 也进了 protected，60 抽必须一个空景别都没有。
    ck("余韵：60 抽景别一次都没被密度裁剪削掉", _empty_shot == 0, f"{_empty_shot}/60")
    ck("余韵：60 抽覆盖到全部 6 种姿势",
       _poses == {"on side", "on back", "on stomach", "sitting", "fetal position", "knees up"},
       str(sorted(x for x in _poses if x)))

    # ── v3.35.0：隐奸 · 被子下 —— 改成第一人称「她顶着被子坐在我身上」──
    # 用户口径（2026-10-23）：「改为第一人称她顶着被子坐我身上。」
    # 原来的组合是第三人称侧面（`from side` + `on side` + `sex from behind`），
    # 画面里根本不像"我在下面"。改成 POV 骑乘后要钉住四件事：
    # ① 机位与体位都是 `cowgirl position`，且视角是 `pov`（镜头=躺着的男方）；
    # ② 被子必须是**罩在她头上、撑成帐篷**（`blanket draped over her head` +
    #    `tented blanket`），不是"盖住全身"（盖住就什么都看不见了）；
    # ③ 男方只露身体不露脸（`faceless male`），否则会变成双人对话构图；
    # ④ 闭麦 `device` —— POV 场景抽到 `webcam footage` / `polaroid frame` 会带出手机 UI 和画框。
    hs = next((x for x in scenes if x["id"] == "sc_ccc_hidden_sex"), {})
    _hst = hs.get("tags") or {}
    ck("隐奸：机位改成第一人称骑乘（pov, cowgirl position）",
       _hst.get("viewpoint") == "pov, cowgirl position", str(_hst.get("viewpoint")))
    ck("隐奸：体位是 cowgirl position + 跪跨",
       _hst.get("n_act") == "cowgirl position" and _hst.get("pose_base") == "kneeling",
       f"{_hst.get('n_act')} / {_hst.get('pose_base')}")
    # v3.35.1（用户口径：「被子不要遮挡胸部，并且生殖器清晰可见」）：
    # 被子从"罩头 + 帐篷盖身"收成**只当兜帽**（挂在肩后），胸与私处都留在外面。
    # 光写 `blanket draped over her head` 不够 —— 模型会把被子顺手画成披肩盖住胸，
    # 必须再补一句 `blanket hanging behind her shoulders` 把被子"推"到背后。
    # 私处同理：骑乘位天然被身体挡住，要 `leaning back`（后仰把胯推到镜头前）
    # + `pussy visible` + `clitoris` + `spread pussy lips` 才真的看得清，
    # 只写 `pussy visible` 时实测还只是"隐约可见"。
    ck("隐奸：被子只当兜帽（罩头 + 挂在肩后，不挡胸）",
       all(k in str(hs.get("extra", "")).lower()
           for k in ("blanket draped over her head like a hood",
                     "blanket hanging behind her shoulders")),
       str(hs.get("extra"))[:140])
    # v3.36.0（用户口径：「增加乳夹，生殖器插入」）：
    # 乳夹走 `n_theme = nipple clamps`（词库里唯一带"夹"的主题），
    # 链条细节写进 extra 的两句（`nipple clamps with chain` + `chain between nipple clamps`），
    # 只写 `nipple clamps` 时模型会把夹子画成"贴纸"、没有链子连接。
    # 插入则要把上一版"外阴展示"那组词换掉 —— `spread pussy lips` / `clitoris` / `implied sex`
    # 都是"未插入 + 只做暗示"的语义，与"正在插入"直接打架，留着会让模型二选一。
    ck("隐奸：乳夹（n_theme = nipple clamps + 链子描述）",
       (hs.get("tags") or {}).get("n_theme") == "nipple clamps"
       and "nipple clamps with chain" in str(hs.get("extra", "")).lower()
       and "chain between nipple clamps" in str(hs.get("extra", "")).lower(),
       f"{(hs.get('tags') or {}).get('n_theme')} / {str(hs.get('extra'))[-100:]}")
    ck("隐奸：胸点名可见（bare breasts + nipples）",
       all(k in str(hs.get("extra", "")).lower() for k in ("bare breasts", "nipples")),
       str(hs.get("extra"))[:120])
    ck("隐奸：结合处写成插入状态（penetration / deep penetration / stretched）",
       all(k in str(hs.get("extra", "")).lower()
           for k in ("penetration", "deep penetration", "pussy stretched around him")),
       str(hs.get("extra"))[-140:])
    ck("隐奸：去掉与明确插入矛盾的暗示词（implied sex / spread pussy lips）",
       "implied sex" not in str(hs.get("extra", "")).lower()
       and "spread pussy lips" not in str(hs.get("extra", "")).lower(),
       str(hs.get("extra"))[-140:])
    ck("隐奸：后仰把胯推到镜头前（leaning back）",
       "leaning back" in str(hs.get("extra", "")).lower(), str(hs.get("extra"))[:80])
    ck("隐奸：被子不再整块盖住身体（去掉 tented blanket / covering her body）",
       "tented blanket" not in str(hs.get("extra", "")).lower()
       and "covering her body" not in str(hs.get("extra", "")).lower(),
       str(hs.get("extra"))[:140])
    ck("隐奸：男方不露脸（faceless male）",
       "faceless male" in str(hs.get("extra", "")).lower(), str(hs.get("extra"))[-60:])
    ck("隐奸：闭麦 device（POV 抽到 webcam / polaroid 会带相机 UI 与画框）",
       "device" in (hs.get("drop_fields") or []), str(hs.get("drop_fields")))
    _hbad = []
    for sd in range(20):
        rr = R.draw(level="hardcore", seed=6990 + sd, weights=R.empty_weights(),
                    base_prob=0.9, forced={"n_canon": "sc_ccc_hidden_sex"})
        _t = rr["text"].lower()
        _h = [w for w in ("boots", "polaroid", "webcam", "thighhigh", "hakama",
                          "coat", "hands up", "on one knee") if w in _t]
        if _h:
            _hbad.append((sd, _h))
    ck("隐奸：20 抽零杂物（靴子 / 拍立得 / 监控 / 外套 / 单膝跪）",
       not _hbad, str(_hbad[:3]))

    # ── v3.37.0：骑乘位 · 女方在上 —— 赤足 + 结合处插入 ────────────────
    # 用户口径（2026-10-23）：「保证人物不穿鞋，生殖器插入。」
    # ① 不穿鞋：`shoes` 写死 `bare feet`（词库里它就是"赤足"选项），
    #    并把 `socks` 也钉成 `barefoot` —— 否则会抽 `thighhighs`，光脚穿长袜一样矛盾；
    #    闭麦 `n_shoes_keep`（`thigh boots` 是从那里漏进来的，不在 `shoes` 里）。
    # ② 插入：`cowgirl position` 本身只是"骑乘"，不写 `penetration` 时结合处经常被身体挡住，
    #    要 `penetration` + `deep penetration` + `pussy stretched around him` 三句才清楚。
    cw = next((x for x in scenes if x["id"] == "sc_ccc_cowgirl"), {})
    _cwt = cw.get("tags") or {}
    ck("骑乘：鞋子写死赤足（bare feet）+ 袜子 barefoot",
       _cwt.get("shoes") == "bare feet" and _cwt.get("socks") == "barefoot",
       f"{_cwt.get('shoes')} / {_cwt.get('socks')}")
    ck("骑乘：闭麦 n_shoes_keep（thigh boots 从这里漏）",
       "n_shoes_keep" in (cw.get("drop_fields") or []), str(cw.get("drop_fields")))
    ck("骑乘：结合处写成插入状态",
       all(k in str(cw.get("extra", "")).lower()
           for k in ("penetration", "deep penetration", "pussy stretched around him")),
       str(cw.get("extra"))[-110:])
    _cwbad = []
    for sd in range(40):
        rr = R.draw(level="hardcore", seed=6960 + sd, weights=R.empty_weights(),
                    base_prob=0.9, forced={"n_canon": "sc_ccc_cowgirl"})
        # ⚠️ v3.41.2：必须按**标签**逐条比对，并排掉角色/作品名 ——
        #    有角色叫 `stocking`（《Panty & Stocking》），子串匹配会把她当袜子。
        _role = {x.strip().lower() for x in str(rr["state"].get("role") or "").split(",")}
        _t = [x.strip().lower() for x in rr["text"].split(",")
              if x.strip() and x.strip().lower() not in _role]
        _h = [w for w in ("high heels", "boots", "sneakers", "slippers", "loafers",
                          "sandals", "geta", "uwabaki", "mary janes",
                          "thighhigh", "stocking", "pantyhose", "latex", "poncho")
              if any(w in x for x in _t)]
        if _h:
            _cwbad.append((sd, _h))
    ck("骑乘：40 抽零鞋类 / 零袜类 / 零服装残留", not _cwbad, str(_cwbad[:3]))

    # ── v3.31.0：去掉镜子（改名 + 换机位 + 闭麦 prop）─────────────────
    ck("去镜：改名为「自慰 · 侧面检视」", mc.get("zh") == "自慰 · 侧面检视", str(mc.get("zh")))
    ck("去镜：机位不再是镜中倒影（from side）",
       mct.get("viewpoint") == "from side" and "mirror" not in str(mct), str(mct.get("viewpoint")))
    ck("去镜：tags 里没有 prop（mirror 已移除）", "prop" not in mct, str(mct.get("prop")))
    ck("去镜：闭麦 prop（否则随机又把镜子抽回来）", "prop" in (mc.get("drop_fields") or []),
       str(mc.get("drop_fields")))
    ck("去镜：extra 不再含 mirror / reflection",
       not any(k in str(mc.get("extra", "")).lower() for k in ("mirror", "reflection")),
       str(mc.get("extra"))[:80])
    mir = []
    for sd in range(20):
        w20 = R.empty_weights()
        w20["fields"]["n_canon"] = 3.0
        ids20 = [en for _z, en in R.field_by_key("n_canon")[1]["opts"]] + \
                [x for _z, x, _n in R.scene_options(99, True)]
        bag20 = {k: 0.0 for k in ids20}; bag20["sc_msb_mirror_check"] = 3.0
        w20["options"]["n_canon"] = bag20
        t = R.draw(level="explicit", seed=6750 + sd, weights=w20, base_prob=0.9)["text"].lower()
        mir += [(sd, b) for b in ("mirror", "reflection") if b in t]
    ck("去镜：20 抽正文零镜面词", not mir, str(mir[:3]))

    names = [x.get("zh") for x in scenes]
    ck("场景中文名没有重复（改名不会撞名）", len(names) == len(set(names)),
       str([n for n in set(names) if names.count(n) > 1][:3]))
    ck("偷窥场景：5 种机位都能抽到", set(VPS) <= vp_seen, str(sorted(vp_seen)))
    ck("护士查房：20 抽零杂道具（冰淇淋 / 高脚杯 / 蛋糕 / 气球）", not junk, str(junk[:3]))
    # ⚠️ v3.39.0：手部入口从 `arms_hands` 改成 `pose_risque = hair flip`（甩发）。
    #    原来两个都写 = 同一条预设自带两个手部动作（上肢单槽冲突），
    #    而擦边档位是由 `hair flip` 判 L1 撑起来的，所以留它。
    ck("雨中透衫：手部锁在「甩发」（v3.39.0 起只留 pose_risque 一侧）",
       not hand_bad, str(hand_bad[:3]))
    ck("贴地场景 20 抽正文零相机类词", not hit, str(hit[:3]))
    ck("套用后 count 等于 count_lock（引擎侧真的钉住了）", not bad_count, str(bad_count[:3]))
    ck("钉人数后 n_act / n_pos / n_theme 不再被多人分支清空",
       not lost_act, str(lost_act[:3]))

    print("── ② 合并层：canon = 法典 + 场景 ──")
    merged = R.canon()
    ck("合并后条数 = 法典 14 + 场景 N",
       len(merged) == 14 + len(scenes), f"{len(merged)} vs {14 + len(scenes)}")
    ck("法典条目原样保留（c8 内容不变）",
       merged.get("c8", {}).get("n_act") == "deepthroat",
       str(merged.get("c8")))
    ck("场景 id 能取到 `{字段: 值}` 形状的预设",
       isinstance(merged.get(lv0[0]), dict) and bool(merged.get(lv0[0])),
       str(merged.get(lv0[0]))[:80])
    ck("场景预设的 n_extra 挂在同一键上（与法典同形状）",
       "n_extra" in (merged.get(lv0[0]) or {}))

    print("── ③ 闸门层：按档位可用性 ──")
    for lv in (0, 2, 3, 4):
        got = {R.canon_level(en) for _zh, en, _n in
               R.eligible_options("n_canon", lv) if en.startswith("sc_")}
        ck(f"L{lv} 的场景候选档位全部 ≤ {lv}", all(g <= lv for g in got),
           str(sorted(got)))
    ck("L0 候选中不含 L2+ 场景",
       not [en for _z, en, _n in R.eligible_options("n_canon", 0)
            if en.startswith("sc_") and R.canon_level(en) > 0])
    # ⚠️ v3.18.0：随机候选池故意排除特写搭配（manual_only），
    #    所以 L4 能拿到的 = 全部场景 − 特写条数；特写要单独断言"一条都不在池子里"。
    manual_n = len([s for s in scenes if s.get("manual_only")])
    ck("高档（L4）能拿到全部**非特写**场景",
       len([en for _z, en, _n in R.eligible_options("n_canon", 4)
            if en.startswith("sc_")]) == len(scenes) - manual_n,
       f"{len(scenes) - manual_n} vs {len(scenes)}-{manual_n}")
    ck("特写搭配一条都不在随机候选池里",
       not [en for _z, en, _n in R.eligible_options("n_canon", 4)
            if R.scene_index().get(en, {}).get("manual_only")])

    # 文本框（n_extra）必须**按标签**判档，不能套 canon 段的段下限（=2）——
    # 否则 SFW 场景自带的附加标签串（`afternoon light, quiet`）会被判成 2 档，
    # 在闸门测试与自检里假报"越档"。
    ck("n_extra 按标签判档（不套段下限）",
       R.field_value_num("n_extra", "afternoon light, quiet") == 0,
       str(R.field_value_num("n_extra", "afternoon light, quiet")))

    # 强制指定超档场景 → F15（档位准入）必须报出来
    hi = [s["id"] for s in scenes if int(s["level"]) >= 4]
    if hi:
        rr = R.draw(level=0, seed=5, forced={"n_canon": hi[0]}, base_prob=0.0)
        ck("强制超档场景 → F15 报越档", "n_canon" in rr["report"]["over_fields"],
           str(rr["report"]["over_fields"]))
    else:
        ck("强制超档场景 → F15 报越档", False, "库里没有 L4 场景，无法验证")

    print("── ④ 应用层：预设真被写进去，且裁不掉（真固定）──")
    sid = "sc_rain_street_lookback" if "sc_rain_street_lookback" in merged \
        else lv0[0]
    want = {k: v for k, v in merged[sid].items() if k != "n_extra"}
    res = R.draw(level=0, seed=9, forced={"n_canon": sid}, base_prob=0.0)
    st = res["state"]
    missing = {k: v for k, v in want.items() if st.get(k) != v}
    ck(f"场景「{sid}」的字段全部写入 state", not missing, str(missing))
    ck("n_extra 也写进去了", bool(st.get("n_extra")))

    # trim：把上限压到 16，场景字段必须活下来（这正是"真固定"的判据）
    res2 = R.draw(level=0, seed=9, forced={"n_canon": sid},
                  base_prob=1.0, tag_cap="16")
    st2 = res2["state"]
    lost = [k for k in want if not st2.get(k)]
    ck("标签上限压到 16 后，场景字段一个都没被裁掉", not lost,
       f"被裁：{lost}；dropped={res2['dropped']}")
    ck("被裁的只可能是非预设字段", not (set(res2["dropped"] or []) & set(want)),
       str(res2["dropped"]))

    print("── ⑤ 输出层：id 不进正文 + 可复现 ──")
    ck("预设 id 不出现在正文里",
       sid not in res["text"] and not any(
           t.startswith("sc_") for t in res["tags"]), res["text"][:80])
    ck("法典 id（c8）也不出现在正文里",
       not any((t.startswith("c") and t[1:].isdigit()) for t in res["tags"]))
    a = R.draw(level=0, seed=42, forced={"n_canon": sid})["text"]
    b = R.draw(level=0, seed=42, forced={"n_canon": sid})["text"]
    ck("同 seed 逐字节可复现", a == b)
    ck("L0 场景输出的自检全绿",
       res["report"]["ok_f"] == res["report"]["total_f"],
       str([c["id"] for c in res["report"]["F"] if not c["ok"]]))

    print("── ⑥ 载荷层：面板与引擎同口径 ──")
    nodes = _boot.load("nodes")
    pools = nodes.pools_payload()
    ncanon = None
    for s in pools["sections"]:
        for f in s["fields"]:
            if f["key"] == "n_canon":
                ncanon = f
    ck("/pools 里有 n_canon 字段", ncanon is not None)
    # ⚠️ 面板列出的候选数必须与引擎实际能抽到的同源候选**完全一致**
    #    （历史教训：预演 A、实跑 B）
    panel_ids = [o["en"] for o in (ncanon or {}).get("opts", [])]
    engine_ids = [en for _zh, en, _n in R.eligible_options("n_canon", 4)]
    # ⚠️ v3.18.0 起口径变了：面板要能列出**特写搭配**（manual_only），
    #    而引擎的随机候选池**故意不含**它们（否则随机分布会变）。
    #    所以这里断言的是「面板 = 随机候选 + 特写搭配」，而不是两边全等。
    manual_ids = [sid for _zh, sid, _n in R.manual_scene_options(4)]
    # ⚠️ v3.21.0：改成比较**集合**而不是列表 —— 面板按词库书写顺序列，
    #    引擎按档位/权重排序，两边数量与内容一致就够了，顺序本来就不承诺相同。
    ck("/pools 的 n_canon 候选 == 引擎随机候选 + 特写搭配（L4）",
       len(panel_ids) == len(engine_ids) + len(manual_ids)
       and set(panel_ids) == set(engine_ids + manual_ids),
       f"{len(panel_ids)} vs {len(engine_ids)}+{len(manual_ids)}")
    ck("面板候选带上了场景条目",
       sum(1 for i in panel_ids if i.startswith("sc_")) == len(scenes))

    sc_payload = nodes.scenes_payload()
    ck("/scenes 载荷含全部分组与场景",
       sc_payload["counters"]["scenes"] == len(scenes)
       and bool(sc_payload["groups"]), str(sc_payload["counters"]))
    # v3.10.0：一级分组是 **NSFW 档位**（L0–L4），不是 sfw/nsfw
    ck("载荷带五个档位分组", len(sc_payload["level_groups"]) == 5,
       str([g["title"] for g in sc_payload["level_groups"]]))
    ck("五个档位分组的条数之和 == 场景总数",
       sum(g["count"] for g in sc_payload["level_groups"]) == len(scenes),
       str([(g["title"], g["count"]) for g in sc_payload["level_groups"]]))
    ck("每一档都有场景（分类展示不留空组）",
       all(g["count"] > 0 for g in sc_payload["level_groups"]),
       str([(g["title"], g["count"]) for g in sc_payload["level_groups"]]))
    ck("每条场景都带题材标签（面板卡片要显示）",
       all(s.get("theme") for s in sc_payload["scenes"]),
       str([s["id"] for s in sc_payload["scenes"] if not s.get("theme")][:3]))
    ck("库规模已扩到 60 条以上", len(scenes) >= 60, str(len(scenes)))
    no_lab = [f for sc in sc_payload["scenes"] for f in sc["fields"]
              if not f.get("lab") or f.get("lab") == f.get("field")]
    ck("每个字段都带中文标签（面板直接渲染）", not no_lab, str(no_lab[:3]))

    print("── ⑦ 挖矿类主题（原「自慰」，v3.11.0；v4.0.0 题材改名）──")
    msb = [s for s in scenes if s.get("theme") == "挖矿"]
    ck("存在「挖矿」题材预设", len(msb) >= 20, f"{len(msb)} 条")
    lvset = {int(s["level"]) for s in msb}
    ck("挖矿类覆盖 L2 / L3 / L4 三档（按 NSFW 等级分类）",
       {2, 3, 4} <= lvset, str(sorted(lvset)))
    ck("挖矿类全部 ≥ L2（L1 擦边档拿得到是漏洞）",
       all(int(s["level"]) >= 2 for s in msb))
    ck("用户示例①「拉开内裤展示」在库里",
       any(s["id"] == "sc_msb_panties_aside" for s in msb))
    ck("用户示例②「假阳具」在库里",
       any("dildo" in str(s.get("tags", {}).get("n_theme", ""))
           or s.get("tags", {}).get("n_act") == "dildo riding" for s in msb))
    # ⚠️ 自慰是单人行为，但预设**不能写 count/role** —— 所以"单人"靠 extra 里的
    #    `solo` 标签表达：人数抽到单人时与 count 的 solo 去重，抽到多人时
    #    repair 的"数量互斥"会把它去掉（优雅降级，不崩不越档）。
    solo_ok = [s for s in msb if "solo" in (s.get("extra") or "")]
    ck("挖矿类预设用 extra 里的 solo 表达单人", len(solo_ok) >= len(msb) - 1,
       f"{len(solo_ok)}/{len(msb)} 含 solo")
    ck("双人互慰**不**写 solo（它本来就是两个人）",
       "solo" not in (next(s for s in msb
                          if s["id"] == "sc_msb_mutual")["extra"]))
    # 闸门：自慰类在 L2 档只放 L2 的、L3 档不放 L4 的
    ids_l2 = {en for _z, en, _n in R.eligible_options("n_canon", 2)
              if en.startswith("sc_msb_")}
    ck("L2 档只拿到 L2 的挖矿场景",
       ids_l2 == {s["id"] for s in msb if int(s["level"]) == 2},
       f"{len(ids_l2)} 条")
    ids_l3 = {en for _z, en, _n in R.eligible_options("n_canon", 3)
              if en.startswith("sc_msb_")}
    ck("L3 档拿不到 L4 的挖矿场景（潮吹）",
       not (ids_l3 & {s["id"] for s in msb if int(s["level"]) == 4}),
       str(sorted(ids_l3 & {s["id"] for s in msb if int(s["level"]) == 4})))

    print("── ⑧ 擦边组扩充（v3.17.1：3 → 28；v3.17.2 镜头模板：→ 38）──")
    # 只统计**场景搭配**的擦边组：特写搭配里也有 1 条 L1（泪光），
    # 它不属于这一组，混进来会让"全部落在 sfw 组"的断言失真。
    l1 = [s for s in scenes if int(s.get("level", -1)) == 1 and not s.get("manual_only")]
    ck("擦边组 ≥ 38 条", len(l1) >= 38, f"{len(l1)} 条")
    # v3.21.0：姿势场景（group=pose）也是 SFW 内容，L1 的「四肢着地」就在这里，
    # 不放行它会让这条断言把"新分组"当成"分组错误"。
    ck("擦边条目全部落在 sfw / pose 组（面板分组正确）",
       all(s["group"] in ("sfw", "pose") for s in l1),
       str(sorted({s["group"] for s in l1})))
    # 派生档位复算（与 build_scenes 同口径）：有标签的档位 ≤1 且至少一条 =1
    sys.path.insert(0, os.path.join(PLUGIN, "tools"))
    from build_scenes import scene_level
    bad_lv = [(s["id"], scene_level(s["tags"], s.get("extra", "")))
              for s in l1 if scene_level(s["tags"], s.get("extra", "")) != 1]
    ck("擦边条目派生档位全部 = 1（不沉到全年龄、不浮到成人）",
       not bad_lv, str(bad_lv[:4]))
    # 暗示姿势的使用率（v3.14.0 pose_risque 字段进场景配方）
    n_risque = sum(1 for s in l1 if "pose_risque" in s["tags"])
    ck("擦边条目大量使用暗示姿势（pose_risque）", n_risque >= 20,
       f"{n_risque}/{len(l1)} 条")
    # 四大题材方向都有覆盖（新增 25 条的 theme 分布）
    new_ids = {"sc_changing_room_peek", "sc_bedroom_sleepshirt", "sc_bath_towel",
               "sc_balcony_laundry", "sc_rain_wetshirt", "sc_sofa_catnap",
               "sc_konbini_midnight", "sc_kitchen_apron", "sc_skirt_wind",
               "sc_hotel_mirror", "sc_beach_volley", "sc_pool_ladder",
               "sc_surf_board", "sc_float_ring", "sc_shower_peek",
               "sc_watergun_fight", "sc_ol_overtime", "sc_maid_serving",
               "sc_nurse_rounds", "sc_classroom_openwin", "sc_jk_bike_ride",
               "sc_yoga_mat", "sc_gym_mirror", "sc_gymnastics_split",
               "sc_jog_rest"}
    got = {s["id"] for s in scenes} & new_ids
    ck("v3.17.1 新增 25 条全部在库", len(got) == 25,
       f"缺 {sorted(new_ids - got)}")
    # v3.17.2 镜头×姿势模板（10 条，纯镜头不带 place，地点交给随机）
    cam_ids = {"sc_cam_wide_low_side", "sc_cam_med_high_kneel",
               "sc_cam_fisheye_squat", "sc_cam_bird_lying", "sc_cam_pov_stand",
               "sc_cam_low_stretch", "sc_cam_side_hairflip", "sc_cam_dutch_wall",
               "sc_cam_ots_lookback", "sc_cam_worm_sit"}
    got_cam = {s["id"] for s in scenes} & cam_ids
    ck("v3.17.2 镜头模板 10 条全部在库", len(got_cam) == 10,
       f"缺 {sorted(cam_ids - got_cam)}")
    ck("镜头模板一律不带 place（纯镜头模板，地点随机）",
       all("place" not in s["tags"] for s in scenes if s["id"] in cam_ids),
       str([s["id"] for s in scenes if s["id"] in cam_ids and "place" in s["tags"]]))
    ck("镜头模板 theme=「镜头实验」",
       all(s.get("theme") == "镜头实验" for s in scenes if s["id"] in cam_ids))
    # 抽一条真套用：擦边预设写进 state 后 F15 档位准入不红。
    # ⚠️ 必须走 **state**（apply_preset 的真实路径）—— 用 check_text 纯文本反推
    #    会把 `bent over` 误归到 n_pos 槽位（成品层反推歧义），假越档。
    _sample = next(s for s in scenes if s["id"] == "sc_yoga_mat")
    _tags = list(dict.fromkeys(
        t.strip() for f in _sample["tags"].values() for t in str(f).split(",")))
    _rep = R.check(_tags, dict(_sample["tags"]), 1)
    ck("擦边预设成品在 L1 检查无致命越档",
       all(c["ok"] for c in _rep["F"] if c["id"] == "F15"),
       str([c["note"] for c in _rep["F"] if c["id"] == "F15" and not c["ok"]]))

    # ── v3.44.1：丝袜专项 10 条（服装一定出现丝袜 + 腿环概率）──────
    # 这组不是"内容好看不好看"，而是**契约**：
    #   · 每条必须锁 socks（否则"一定出现"是假的）；
    #   · 候选必须是**丝袜类**，混进 `barefoot` / `ankle socks` 就等于没锁；
    #   · 候选最高档位不能超过条目档位（否则 build_scenes 会把 level 顶上去）；
    #   · 腿环走 `accessory` 候选，出现率按候选数算，写死成 100% 就不是"概率"了；
    #   · 最硬的一条：真套用一次，正文里必须真的有丝袜标签。
    print("\n── 丝袜专项（v3.44.1：10 条 + 腿环候选）──")
    sock_ids = sorted(s["id"] for s in scenes if s["id"].startswith("sc_sock_"))
    ck("丝袜专项 10 条全部在库", len(sock_ids) == 10,
       f"{len(sock_ids)}：{sock_ids}")
    ck("10 条 theme 一律「丝袜」（面板题材条能一键筛出）",
       all(next(s for s in scenes if s["id"] == i).get("theme") == "丝袜"
           for i in sock_ids),
       str([(i, next(s for s in scenes if s["id"] == i).get("theme"))
            for i in sock_ids]))
    ck("10 条都钉了人数（非特写场景的硬要求）",
       all(next(s for s in scenes if s["id"] == i).get("count_lock")
           for i in sock_ids))
    # 丝袜类判定：socks 字段里"赤足 / 短袜 / 袜套 / 足袋"这类**不是丝袜**，
    # 候选里出现它们就说明写错了键（把鞋袜当丝袜）。
    NOT_STOCKING = {"barefoot", "ankle socks", "no-show socks", "tabi",
                    "leg warmers", "slippers", "loose socks", "ribbed socks",
                    "fishnet socks", "frilled socks", "lace-trimmed socks"}
    bad_cand = []
    for i in sock_ids:
        sc = next(s for s in scenes if s["id"] == i)
        for c in (sc.get("random_fields") or {}).get("socks", []):
            if c in NOT_STOCKING or R.option_level("socks", c) is None:
                bad_cand.append((i, c))
    ck("每条都锁了 socks，且候选里没有「赤足 / 短袜」这类非丝袜",
       not bad_cand, str(bad_cand))
    ck("socks 候选一律 ≤ 条目自身档位（不会把档位顶上去）",
       all(R.option_level("socks", c) <= next(
               s for s in scenes if s["id"] == i).get("level", 0)
           for i in sock_ids
           for c in (next(s for s in scenes if s["id"] == i)
                     .get("random_fields") or {}).get("socks", [])),
       str([(i, c) for i in sock_ids
            for c in (next(s for s in scenes if s["id"] == i)
                      .get("random_fields") or {}).get("socks", [])
            if R.option_level("socks", c) > next(
                s for s in scenes if s["id"] == i).get("level", 0)]))
    ck("腿环（thigh strap）只在 accessory 候选里、不在 tags 里写死",
       all("thigh strap" in (next(s for s in scenes if s["id"] == i)
                             .get("random_fields") or {}).get("accessory", [])
           and "accessory" not in next(s for s in scenes if s["id"] == i)["tags"]
           for i in sock_ids),
       str([i for i in sock_ids
            if "thigh strap" not in (next(s for s in scenes if s["id"] == i)
                                     .get("random_fields") or {}).get("accessory", [])]))
    ck("sock_color 被闭麦（候选已带颜色，再抽一次颜色会自相矛盾）",
       all("sock_color" in (next(s for s in scenes if s["id"] == i)
                            .get("drop_fields") or [])
           for i in sock_ids),
       str([i for i in sock_ids
            if "sock_color" not in (next(s for s in scenes if s["id"] == i)
                                    .get("drop_fields") or [])]))
    _lv = Counter(next(s for s in scenes if s["id"] == i).get("level")
                  for i in sock_ids)
    ck("档位铺开 L0:4 / L1:3 / L2:2 / L3:1",
       (_lv.get(0), _lv.get(1), _lv.get(2), _lv.get(3)) == (4, 3, 2, 1),
       str(sorted(_lv.items())))
    # 真套用：n_canon 顶到 3.0 → apply_preset 写 state → 正文必须含候选之一
    _canon = R.canon()
    _miss = []
    _strap = 0
    _runs = 0
    for i in sock_ids:
        sc = next(s for s in scenes if s["id"] == i)
        lv_i = int(sc.get("level", 0))
        cands = sc["random_fields"]["socks"]
        w = R.empty_weights()
        w["fields"]["n_canon"] = 3.0
        w["options"]["n_canon"] = {k: (3.0 if k == i else 0.0) for k in _canon}
        for seed in (7, 77, 777):
            r = R.draw(level=lv_i, seed=seed, weights=w, tag_cap="自动")
            _runs += 1
            if (r["state"].get("socks") or "").strip() not in cands:
                _miss.append((i, seed, r["state"].get("socks")))
            if (r["state"].get("accessory") or "") == "thigh strap":
                _strap += 1
    ck("真套用 3 个 seed × 10 条：socks 全部命中候选（丝袜必现）",
       not _miss, str(_miss[:5]))
    ck("腿环出现率落在 10%–70%（是「概率」而不是恒有/恒无）",
       0.10 <= _strap / max(1, _runs) <= 0.70,
       f"{_strap}/{_runs}")

    # ── v3.44.2：候选池扩到**全集** + 亮丝星点加权 ─────────────────
    # 用户口径：「丝袜要能随机抽到各种款式」（点名白色亮丝星点过膝袜 / 白色亮丝星点袜 /
    # 淡粉亮丝星点吊带袜）。所以候选不再是每场景 3–4 款，而是**该档可用全集**：
    #   L0 54 款 · L1 58 款 · L2/L3 65 款（丝袜款里剔掉赤足/短袜/袜套等棉袜）。
    # ⚠️ 亮丝星点只有 15 款，全集里占 28%；要 ~1/3 只能**重复占位**
    #    （抽取是等概率取列表元素）—— 重复项是刻意加权，测试要允许并守住比例。
    _LEVEL_MIN = {0: 54, 1: 58, 2: 65, 3: 65}
    _size = {}
    _glit = {}
    _bad_share = []
    for i in sock_ids:
        sc = next(s for s in scenes if s["id"] == i)
        c = sc["random_fields"]["socks"]
        lv_i = int(sc.get("level", 0))
        _size[i] = (len(set(c)), len(c))
        share = sum(1 for x in c if "glittery" in x) / len(c)
        _glit[i] = round(share, 3)
        if len(set(c)) < _LEVEL_MIN[lv_i] or not (0.25 <= share <= 0.40):
            _bad_share.append((i, len(set(c)), round(share, 3)))
    ck("候选池覆盖该档全集（L0≥54 / L1≥58 / L2·L3≥65 款）",
       all(v[0] >= _LEVEL_MIN[next(s for s in scenes if s["id"] == i)["level"]]
           for i, v in _size.items()), str(_size))
    ck("亮丝星点系占候选 25%–40%（缺了就没覆盖到点名的那几款）",
       not _bad_share, str(_bad_share))
    ck("三族齐全：连裤 / 过膝 / 吊带过膝（点名款都在候选里）",
       all(any("glittery pantyhose" in x for x in
               next(s for s in scenes if s["id"] == i)["random_fields"]["socks"])
           and any("glittery thighhighs" in x and "garter" not in x for x in
                   next(s for s in scenes if s["id"] == i)["random_fields"]["socks"])
           and any("glittery thighhighs, garter straps" in x for x in
                   next(s for s in scenes if s["id"] == i)["random_fields"]["socks"])
           for i in sock_ids),
       "有点名款缺失")
    _named = ["white glittery thighhighs", "white glittery pantyhose",
              "pale pink glittery thighhighs, garter straps"]
    ck("用户点名的三款（白亮丝过膝 / 白亮丝连裤 / 淡粉亮丝吊带）都在候选里",
       all(n in next(s for s in scenes if s["id"] == i)["random_fields"]["socks"]
           for i in sock_ids for n in _named))
    # 真抽一轮看**款式多样性**：每场景 60 抽，统计出现过多少种不同款式
    _canon2 = R.canon()
    _variety = {}
    _glit_hit = 0
    _glit_n = 0
    for i in sock_ids:
        sc = next(s for s in scenes if s["id"] == i)
        lv_i = int(sc.get("level", 0))
        w = R.empty_weights()
        w["fields"]["n_canon"] = 3.0
        w["options"]["n_canon"] = {k: (3.0 if k == i else 0.0) for k in _canon2}
        seen = set()
        for seed in range(20000, 20060):
            r = R.draw(level=lv_i, seed=seed, weights=w, tag_cap="自动")
            got = (r["state"].get("socks") or "").strip()
            if got:
                seen.add(got)
                _glit_n += 1
                if "glittery" in got:
                    _glit_hit += 1
        _variety[i] = len(seen)
    ck("60 抽里每场景至少出现 15 种不同丝袜款（真的抽得开）",
       all(v >= 15 for v in _variety.values()), str(_variety))
    ck("实测亮丝星点出现率 15%–50%（加权生效，但没到主导）",
       0.15 <= _glit_hit / max(1, _glit_n) <= 0.50,
       f"{_glit_hit}/{_glit_n} = {_glit_hit / max(1, _glit_n):.1%}")

    print()
    if FAILS:
        print(f"[check_v3_scenes] 失败 {len(FAILS)} 项：{FAILS}")
        return 1
    print(f"[check_v3_scenes] 通过：{len(scenes)} 个场景（"
          + " / ".join(f"{k}={v}" for k, v in sorted(by_group.items()))
          + "）· 合并 / 闸门 / 固定 / 输出 / 载荷 全部符合预期")
    return 0


if __name__ == "__main__":
    sys.exit(main())
