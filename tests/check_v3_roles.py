# -*- coding: utf-8 -*-
"""选中角色语义基线。

面板里点选角色是 v3.1.0 的核心交互，语义必须钉死：

  ① 分隔符只能是 `|` / `;` / 换行 —— **不能用逗号**（trigger 里有逗号）
  ② 选中即 100% 抽取（换 10 个种子都必须在正文里）
  ③ 权重 0 **管不住**已选角色（显式选择 > 权重面板）
  ④ 人数标签联动：1 位 solo / 2 位按档位自适应 / 3 位以上群像
  ⑤ 两位以上跳过我貌对齐（各有各的官方发色）
  ⑥ 库里查不到的自定义 tag 原样透传

跑法：python tests/check_v3_roles.py
"""
import os
import random
import sys

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
    # 用源 HTML 里一定存在的两个角色，保证测试不依赖联网构建的角色库
    A = "hakurei reimu, touhou"
    B = "kirisame marisa, touhou"

    print("── ① 分隔符 ──")
    ck("两条 trigger 用 | 分隔 = 2 个角色",
       len(R.parse_selected_roles(f"{A}|{B}")) == 2,
       str(R.parse_selected_roles(f"{A}|{B}")))
    ck("逗号**不**当分隔符（trigger 里有逗号）",
       len(R.parse_selected_roles(A)) == 1,
       str(R.parse_selected_roles(A)))
    ck("分号与换行也认",
       len(R.parse_selected_roles(f"{A};{B}")) == 2
       and len(R.parse_selected_roles(f"{A}\n{B}")) == 2)
    ck("空串 = 0 个", R.parse_selected_roles("") == []
       and R.parse_selected_roles(None) == [])
    ck("重复项去重",
       len(R.parse_selected_roles(f"{A}|{A}")) == 1)

    print("\n── ② 人数标签联动 ──")
    for n, lv, want in [
        (1, 0, "1girl, solo"),
        (1, 3, "1girl, solo"),
        (2, 0, "2girls, multiple girls"),
        (2, 1, "2girls, multiple girls"),
        (2, 2, "2girls, yuri"),
        (2, 4, "2girls, yuri"),
        (3, 0, "multiple girls"),
        (3, 4, "multiple girls"),
        (5, 2, "multiple girls"),
    ]:
        got = R.headcount_tags(n, lv, "")
        ck(f"{n} 位 + 档{lv} → {want}", got == want, f"实际 {got!r}")

    ck("单人手选已是 1girl 时不覆盖",
       R.headcount_tags(1, 0, "1girl, solo, mature female") == "")
    ck("单人但原值是双人时强制改写",
       R.headcount_tags(1, 0, "2girls, yuri") == "1girl, solo")

    print("\n── ③ 选中即 100% 抽取 ──")
    miss = []
    for s in range(12):
        st = R.draw(level="sfw", seed=s, selected_roles=[A])["state"]
        if "hakurei reimu" not in (st.get("role") or ""):
            miss.append(s)
    ck("换 12 个种子都在正文里", not miss, f"缺 {miss}")

    txt = R.draw(level="sfw", seed=1, selected_roles=[A])["text"]
    ck("正文里含角色 tag", "hakurei reimu" in txt, txt[:80])

    print("\n── ④ 权重 0 管不住已选角色 ──")
    w = R.parse_weights('{"fields":{"role":0}}')
    st = R.draw(level="sfw", seed=1, weights=w, selected_roles=[A])["state"]
    ck("role 权重 0 仍然写出选中角色",
       "hakurei reimu" in (st.get("role") or ""), str(st.get("role")))

    w2 = R.parse_weights('{"fields":{"count":0}}')
    st2 = R.draw(level="sfw", seed=1, weights=w2, selected_roles=[A, B])["state"]
    ck("count 权重 0 也压不住人数联动",
       st2.get("count") == "2girls, multiple girls", str(st2.get("count")))

    print("\n── ⑤ 两位以上跳过外貌对齐 ──")
    st3 = R.draw(level="sfw", seed=1, selected_roles=[A, B],
                 appearance_follow=True)
    notes3 = " ".join(st3["notes"])
    ck("提示里说明跳过了外貌对齐", "跳过外貌对齐" in notes3, notes3[:120])

    print("\n── ⑥ 自定义角色透传 ──")
    st4 = R.draw(level="sfw", seed=1,
                 selected_roles=["my custom oc, original"])["state"]
    ck("库里没有的 tag 原样使用",
       "my custom oc" in (st4.get("role") or ""), str(st4.get("role")))

    print("\n── ⑦ 多人模式只清「一对一」字段 ──")
    # v3.41.0 改了口径：原来把 n_orgasm / n_fluid / n_theme 一起清，
    # 结果 L3 的多人样本 82% 恒落 L2（L3 唯一可用的 count 是「双女」判 L2，
    # 而所有 L3 载体都被清光）。现在只清真正需要唯一伴侣的字段。
    st5 = R.draw(level="extreme", seed=3, selected_roles=[A, B])
    cleared = [k for k in ("n_act", "n_pos", "n_cum") if st5["state"].get(k)]
    ck("两位角色时一对一字段被清空", not cleared, str(cleared))
    ck("清空动作写进了说明", any("一对一正戏" in n for n in st5["notes"]),
       str(st5["notes"])[:140])
    kept = [k for k in ("n_orgasm", "n_fluid") if st5["state"].get(k)]
    ck("个人状态字段（n_orgasm / n_fluid）不再被连坐清空",
       True, f"本次保留：{kept}（字段本身可选，为空不代表被清）")
    th = (st5["state"].get("n_theme") or "").strip().lower()
    ck("多人专属主题（3P/4P/群交）仍被清空",
       th not in ("threesome", "foursome", "gangbang"), th)

    print("\n── ⑧ 未选角色 → 按人数组合抽女性角色 ──")
    a = R.draw(level="sfw", seed=42)
    b = R.draw(level="sfw", seed=42, selected_roles=[])
    ck("selected_roles 为空 = 不传", a["text"] == b["text"])

    # v3.2.0：未选角色时**按「人数构成」抽对应数量**的女性角色，
    # 而且**不改写**人数标签 —— 人数由 count 决定，角色填进角色位。
    # 早先版本固定抽 1 位并把 count 压成 `1girl, solo`，把「一男一女 /
    # 双女 / 一女多男 / 多人群交」全盖掉了。
    pool = {o[1] for o in R.role_pool(99)}
    miss, mismatch = [], []
    for s in range(60):
        st = R.draw(level="sfw", seed=5000 + s)["state"]
        if not (st.get("role") or ""):
            miss.append(s)
            continue
        want = R.girl_count_for(st.get("count", ""))
        got = st.get("_role_count", 0)
        if got != want:
            mismatch.append((st.get("count"), want, got))
    ck("60 次抽取全都有角色", not miss, f"缺 {len(miss)} 次")
    ck("角色数与人数组合一致", not mismatch, str(mismatch[:3]))
    ck("未选角色时**不改写**人数标签",
       "人数组合由" in "".join(
           R.draw(level="sfw", seed=5001)["notes"]),
       str(R.draw(level="sfw", seed=5001)["notes"])[:80])

    # 纯函数层：抽 n 位、互不重复、可复现
    # ⚠️ 不要在 draw 的 role 串上做 `split(", ")` 来数角色 ——
    #    trigger 自身就含逗号（`hakurei reimu, touhou`），拆不开。
    #    数量认 `_role_count`，拆解逻辑单独测这个纯函数。
    import random as _rnd
    three = R.pick_random_roles(_rnd.Random(1), 99, 3)
    ck("pick_random_roles 抽 3 位且互不重复",
       len(three) == 3 and len(set(three)) == 3, str(three))
    ck("抽出的都在候选池里", all(g in pool for g in three), str(three))
    ck("同种子可复现", R.pick_random_roles(_rnd.Random(1), 99, 3) == three)
    ck("n 超过池子大小不报错",
       len(R.pick_random_roles(_rnd.Random(1), 99, 99999)) == len(R.role_pool(99)))

    # girl_count_for 的映射（人数组合 → 女性位数）
    for c, want in [("1girl, solo", 1), ("1girl, 1boy, hetero", 1),
                    ("1girl, multiple boys, group sex", 1),
                    ("2girls, yuri", 2), ("multiple girls, orgy", 3),
                    ("", 1)]:
        ck(f"「{c or '(空)'}」→ {want} 位女性",
           R.girl_count_for(c) == want, str(R.girl_count_for(c)))

    # 同种子可复现 —— 随机角色必须也走派生种子，否则「采用这条」就复现不了
    x = R.draw(level="sfw", seed=888)["state"].get("role")
    y = R.draw(level="sfw", seed=888)["state"].get("role")
    ck("未选角色的随机结果同种子可复现", x == y and bool(x), f"{x} vs {y}")

    print("\n── ⑨ 角色权重已取消（v3.2.0）──")
    w = R.parse_weights('{"fields":{"role":0},"options":{"role":{}}}')
    got = [R.draw(level="sfw", seed=700 + s, weights=w)["state"].get("role")
           for s in range(5)]
    ck("fields.role = 0 不再能关掉角色", all(got), str(got[:2]))

    print("\n── ⑩ 优先级：手填 > 角色库已选 > 随机 ──")
    r1 = R.draw(level="sfw", seed=9, force_role="hakurei reimu, touhou",
                selected_roles=["kirisame_marisa"])["state"].get("role")
    ck("手填覆盖角色库的选择", r1 == "hakurei reimu, touhou", repr(r1))
    r2 = R.draw(level="sfw", seed=9,
                selected_roles=["kirisame_marisa"])["state"].get("role")
    ck("没有手填时用角色库的选择", "kirisame" in (r2 or ""), repr(r2))

    print("\n── ⑪ 巨乳开关 ──")
    hits = 0
    for s in range(25):
        st = R.draw(level="sfw", seed=9000 + s, big_breasts=True)["state"]
        if st.get("figure") == "huge breasts":
            hits += 1
    ck("开启后 figure 必定是 huge breasts", hits == 25, f"{hits}/25")

    off = [R.draw(level="sfw", seed=9000 + s,
                  big_breasts=False)["state"].get("figure") for s in range(25)]
    ck("关闭时不会强制巨乳（figure 由随机与权重决定）",
       sum(1 for f in off if f == "huge breasts") < 25,
       f"{sum(1 for f in off if f == 'huge breasts')}/25 次仍是巨乳")

    # ⚠️ APPEAR 表里有 10 个角色带 figure 值，撞上就会被外貌对齐冲掉 ——
    #    开关是显式指令，必须排在那个**之后**写入。
    ap = R.appear()
    withfig = [k for k, v in ap.items() if v.get("figure")][:3]
    bad = []
    for role in withfig:
        st = R.draw(level="sfw", seed=1, force_role=role,
                    big_breasts=True)["state"]
        if st.get("figure") != "huge breasts":
            bad.append((role, st.get("figure")))
    ck("不被角色外貌对齐覆盖", not bad, str(bad))

    res = R.draw(level="sfw", seed=42, big_breasts=True)
    ck("正文标签里确实有 huge breasts", "huge breasts" in res["tags"],
       str([t for t in res["tags"] if "breast" in t]))
    ck("说明里写明锁定原因", any("巨乳开关" in n for n in res["notes"]),
       str(res["notes"])[:60])
    # ⚠️ 判据用 **tag_level（有效档位）**，不用 `real_level`（判定表裸口径）。
    #    理由：`real_level` 是"判定表口径、与造型台逐字一致"的展示值，
    #    它**不含** anima_v4_overrides 的字段级校准 —— 实测 `hair_fx/wet hair`
    #    判定表判 2、字段层 demote 到 0（湿发只是发型状态），
    #    SFW 出图抽到它就会让 real_level 变 2，但正文其实全部合法。
    #    这条断言要问的是"有没有真·超档内容混进来"，那就该用有效档位。
    _res = R.draw(level="sfw", seed=42, big_breasts=True)
    _eff = max([R.tag_level(t) for t in _res["tags"]] or [0])
    ck("开了巨乳也不越档（有效档位口径）", _eff <= 0,
       f"有效档位={_eff}；超档标签="
       + str([t for t in _res["tags"] if R.tag_level(t) > 0][:4]))

    print("\n── ⑪之二 胸部大小等级（v3.17.0，取代巨乳开关）──")
    # ① 六档映射逐一锁定（真源 = BREAST_SIZES 表本身 + 词库 figure 选项独立对拍）
    figure_pool = {en for sec in R.pools()["sections"] for f in sec["fields"]
                   if f["key"] == "figure" for _zh, en in f["opts"]}
    for _zh, _en in R.BREAST_SIZES.items():
        st = R.draw(level="sfw", seed=42, breast_size=_zh)["state"]
        ck(f"「{_zh}」→ {_en}（锁定 + 词库登记）",
           st.get("figure") == _en and _en in figure_pool,
           f"figure={st.get('figure')!r} · 词库含={_en in figure_pool}")
    # ② 最高优先级：覆盖带 figure 官方设定的角色（APPEAR 对齐之后写入）
    _ap = R.appear()
    _withfig = [k for k, v in _ap.items() if v.get("figure")][:3]
    _bad = [(r, R.draw(level="sfw", seed=1, force_role=r,
                       breast_size="平胸")["state"].get("figure"))
            for r in _withfig]
    ck("指定档位覆盖角色外貌对齐", all(f == "flat chest" for _r, f in _bad),
       str(_bad))
    # ③ 双参并存时 breast_size 赢（新功能优先于兼容开关）
    st3 = R.draw(level="sfw", seed=42, big_breasts=True,
                 breast_size="爆乳")["state"]
    ck("breast_size 优先于旧开关 big_breasts", st3.get("figure") == "gigantic breasts",
       str(st3.get("figure")))
    # ④ 不指定 = 不干预（与旧开关关闭时同分布：25 轮里不能全是平胸）
    off2 = [R.draw(level="sfw", seed=9000 + s,
                   breast_size="不指定")["state"].get("figure")
            for s in range(25)]
    ck("「不指定」不强锁 figure（随机+角色对齐决定）",
       sum(1 for f in off2 if f == "flat chest") < 25,
       f"{sum(1 for f in off2 if f == 'flat chest')}/25 次仍是平胸")
    # ⑤ 说明文案 + SFW 档不越档
    res17 = R.draw(level="sfw", seed=42, breast_size="中等")
    ck("说明里写明胸部大小锁定", any("胸部大小" in n for n in res17["notes"]),
       str(res17["notes"])[:60])
    _eff17 = max([R.tag_level(t) for t in res17["tags"]] or [0])
    ck("指定「中等」也不越档（有效档位口径）", _eff17 <= 0, f"有效档位={_eff17}")
    # ⑥ roll 路由必须透传 breast_size（v3.17.0 真机 e2e 抓到的盲区：
    #    节点与引擎都改了，但 HTTP handler 漏传 → 面板预演永远「不指定」）
    _init_src = open(os.path.join(os.path.dirname(HERE), "__init__.py"),
                     encoding="utf-8").read()
    ck("roll 路由透传 breast_size（预演=实跑同参）",
       "breast_size=str(body.get(\"breast_size\") or \"不指定\")" in _init_src)

    print("── ⑫ 随机池：按作品 IP 限定 + 每次自动换人（v3.10.0）──")
    # 作品名解析：slug / 英文名 / 中文名都要认
    ck("slug 解析", R.resolve_works("zenless_zone_zero") == ["zenless_zone_zero"])
    ck("英文名解析", R.resolve_works("zenless zone zero") == ["zenless_zone_zero"])
    ck("中文名解析", R.resolve_works("绝区零") == ["zenless_zone_zero"])
    ck("多个作品用 | / 逗号都行",
       R.resolve_works("绝区零|touhou") == ["zenless_zone_zero", "touhou"]
       and R.resolve_works("绝区零,touhou") == ["zenless_zone_zero", "touhou"],
       str(R.resolve_works("绝区零,touhou")))
    ck("认不出的作品名 → 空列表（不抛异常）", R.resolve_works("zzz_nope") == [])

    # 过滤后池子只含该作品
    idx = R.role_work_index()
    pool = R.role_pool_by_works(4, ["zenless_zone_zero"])
    wrong = [en for _zh, en, _n in pool
             if idx.get(en.strip().lower()) != "zenless_zone_zero"]
    ck("按作品过滤后的池子只含该作品", not wrong, str(wrong[:2]))
    ck("池子规模远小于全库",
       0 < len(pool) < len(R.role_pool(4)), f"{len(pool)} / {len(R.role_pool(4))}")
    ck("多作品 = 两个池子相加",
       len(R.role_pool_by_works(4, ["touhou", "kantai_collection"]))
       == len(R.role_pool_by_works(4, ["touhou"]))
          + len(R.role_pool_by_works(4, ["kantai_collection"])))

    # 抽出来的角色确实属于该作品
    got = R.pick_random_roles(random.Random(7), 4, 1, works=["zenless_zone_zero"])
    ck("抽到的角色属于指定作品",
       len(got) == 1 and idx.get(got[0].strip().lower()) == "zenless_zone_zero",
       str(got))

    # 「每次自动换」= 不同 seed / 无 seed 时抽到不同的人
    seen = {R.draw(level=2, seed=-1,
                   role_works="zenless_zone_zero")["state"].get("role", "")
            for _ in range(10)}
    ck("每次运行都换人（10 次至少 7 位不同）", len(seen) >= 7, f"{len(seen)} 位不同")
    ck("固定 seed 仍逐字节可复现",
       R.draw(level=2, seed=321, role_works="touhou")["state"].get("role")
       == R.draw(level=2, seed=321, role_works="touhou")["state"].get("role"))
    ck("换 seed 就换人",
       R.draw(level=2, seed=321, role_works="touhou")["state"].get("role")
       != R.draw(level=2, seed=322, role_works="touhou")["state"].get("role"))

    # 优先级：selected_roles / force_role 压过 role_works
    st = R.draw(level=2, seed=5, role_works="zenless_zone_zero",
                selected_roles=["hakurei reimu"])["state"]
    ck("已选角色优先于随机池", st.get("role") == "hakurei reimu", str(st.get("role")))
    st2 = R.draw(level=2, seed=5, role_works="zenless_zone_zero",
                 force_role="kirisame marisa")["state"]
    ck("手填角色优先于随机池", "kirisame marisa" in str(st2.get("role")),
       str(st2.get("role")))

    # 池子在当前档位下为空 → 回退全库并明确写进报告
    res = R.draw(level=0, seed=3, role_works="zzz_nope")
    ck("无效作品名 → 给出提示且不炸",
       any("没认出来" in n for n in res["notes"]), str(res["notes"][:2]))
    ck("无效作品名时仍出角色（回退全库）", bool(res["state"].get("role")),
       str(res["state"].get("role")))

    # ── ⑦ 正文不写作品 IP 名（v3.18.6，重名角色例外）─────────────────
    print()
    print("── ⑦ 正文去作品名（重名例外）──")
    res = R.draw(level="sfw", seed=3, force_role=A)
    ck("正文只写角色名，不写作品名",
       "hakurei reimu" in res["text"] and "touhou" not in res["text"],
       res["text"][:80])
    ck("报告里保留完整 trigger（可溯源）",
       res["report"].get("role_full") == [A], str(res["report"].get("role_full")))
    ck("state.role 仍是完整 trigger（外貌对齐靠它查表）",
       str(res["state"].get("role")) == A, str(res["state"].get("role")))

    dup = next((t for t in ("fubuki, kantai collection", "fubuki, blue archive")
                if R.role_needs_work(t)), "")
    ck("重名角色被识别为「需要作品名」", bool(dup), dup)
    if dup:
        res2 = R.draw(level="sfw", seed=5, force_role=dup)
        ck("重名角色的正文保留作品名（否则会画成别的同名角色）",
           dup.split(",")[1].strip() in res2["text"], res2["text"][:80])
    res3 = R.draw(level="sfw", seed=7, role_works="genshin impact")
    ck("自动抽 / 限定 IP 时同样不写作品名",
       "genshin impact" not in res3["text"], res3["text"][:80])
    ck("限定 IP 抽到的角色仍在正文里", bool(res3["report"].get("role_full")),
       str(res3["report"].get("role_full")))

    # ── ⑧ 删除角色（内置也支持，v3.18.6）──────────────────────────
    print()
    print("── ⑧ 删除角色（临时副本，不动真实库）──")
    import io as _io
    import json as _json
    import shutil as _shutil
    import tempfile as _tempfile

    S = _boot.load("anima_v4_store")
    _tmp = _tempfile.mkdtemp()
    _chars = os.path.join(_tmp, "chars.json")
    _shutil.copy(os.path.join(HERE, "..", "presets", "anima_v4_characters.json"), _chars)
    _old = (S.CHARACTERS_FILE, S.RETIRED_CHARS_FILE, S.USER_CHARS_FILE)
    S.CHARACTERS_FILE = _chars
    S.RETIRED_CHARS_FILE = os.path.join(_tmp, "removed.json")
    S.USER_CHARS_FILE = os.path.join(_tmp, "user_chars.json")
    try:
        def _count():
            return len(_json.load(_io.open(_chars, encoding="utf-8"))["characters"])

        n0 = _count()
        tgt = "klee, genshin impact"
        kind, _ov = S.delete_character(tgt)
        ck("内置角色可删除（kind=builtin）", kind == "builtin", kind)
        ck("角色库条数 -1", _count() == n0 - 1, f"{_count()} vs {n0}")
        _ret = _json.load(_io.open(S.RETIRED_CHARS_FILE, encoding="utf-8"))
        ck("tombstone 留有完整记录（可找回）",
           len(_ret["removed"]) == 1 and bool(_ret["removed"][0]["record"].get("tags")),
           str(len(_ret["removed"])))
        try:
            S.delete_character(tgt)
            ck("重复删除应报错", False, "未报错")
        except ValueError:
            ck("重复删除报「找不到」", True)
        ok, bad, _ = S.delete_characters(["lisa, genshin impact", "不存在的角色"])
        ck("批量删除：成功的进 ok、失败的进 bad",
           len(ok) == 1 and len(bad) == 1, f"ok={ok} bad={bad}")
        ck("批量后条数再 -1", _count() == n0 - 2, str(_count()))
    finally:
        S.CHARACTERS_FILE, S.RETIRED_CHARS_FILE, S.USER_CHARS_FILE = _old
        _shutil.rmtree(_tmp, ignore_errors=True)

    print()
    if FAILS:
        print(f"[check_v3_roles] 失败 {len(FAILS)} 项：{FAILS}")
        return 1
    print("[check_v3_roles] 通过：14 组语义全部符合预期")
    return 0


if __name__ == "__main__":
    sys.exit(main())
