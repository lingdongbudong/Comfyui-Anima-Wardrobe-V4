# -*- coding: utf-8 -*-
"""角色库基线：内容合规 + 结构正确 + （可选）标签在线上真实存在。

角色库是**联网构建**出来的，所以内容质量必须被机器钉死，不能靠"看着差不多"：

  ① 结构：必备字段、tag 形态合法、trigger 带作品名、人气降序
  ② 合规：不含宝可梦、不含男性（与造型台性别字段交叉验证）
  ③ 覆盖：绝区零 / 星穹铁道 / 胜利女神的女性角色数不低于阈值
  ④ 有效：中文名覆盖率、缩略图覆盖率
  ⑤ --net：抽查若干角色 tag，确认它们在 safebooru 上确实是 category=4 的角色
     （这是"标签准确无误"唯一可机器验证的口径 —— 我们自己编的 tag
       模型不认得，只有镜像上真实存在的 tag 才管用）

⚠️ 角色库缺席时本测试 **SKIP 而不是 FAIL**：它是可选的构建产物，
   没跑过 build_characters.py 的干净环境不该因此变红。

跑法：
    python tests/check_v3_chars.py           # 离线全查
    python tests/check_v3_chars.py --net     # 额外抽查线上标签（较慢）
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
CUSTOM_NODES = os.path.dirname(PLUGIN)

sys.path.insert(0, HERE)
import _boot  # noqa: E402  （④b 要借 nodes.characters_payload 验接口契约）

CHARS = os.path.join(PLUGIN, "presets", "anima_v4_characters.json")
THUMBS = os.path.join(PLUGIN, "presets", "thumbs")
WARDROBE_POOL = os.path.join(CUSTOM_NODES, "Comfyui-Anima-Wardrobe",
                             "presets", "character_pool.json")

MIRROR = "https://safebooru.donmai.us"
UA = {"User-Agent": "curl/8.4.0"}     # safebooru 拦浏览器 UA，见 build_characters.py

# 目标作品保底阈值。取实测值的约 8 折 —— 既保证"齐全"，
# 又不会因为镜像上偶发少几个 tag 而误报。
TARGET_MIN = {
    # v3.13.0：绝区零 / 崩铁 / 妮姬 三家改用 **danbooru 官方角色列表页**白名单
    #（`tools/playable_roles.json`，由 `tools/build_playable_roles.py` 重生成）。
    # 实测：绝区零 52 · 崩铁 67 · 妮姬 199（其中 21 条是联动角色，
    # work 字段仍是原作品名，所以按 work 统计是 178）→ 阈值取实测的 ~85%。
    "zenless zone zero": 45,
    "honkai: star rail": 58,
    "goddess of victory: nikke": 150,
    # v3.12.0：鸣潮进保底 + 只收可玩角色（NPC/怪物/BOSS 已剔除）。
    # 实测 65 条（46 可玩 + 19 形态皮肤）。
    "wuthering waves": 55,
}

# 明显属于宝可梦的角色 tag 片段（作品字段之外的第二道防线）
POKEMON_HINTS = ("pokemon", "pikachu", "eevee", "charizard", "gardevoir",
                 "lucario", "greninja", "mewtwo", "sylveon", "lopunny",
                 "zoroark", "absol", "snivy", "oshawott", "tepig")

# tag 形态校验用**结构化判断**而不是单条正则。
# 为什么：danbooru 的角色 tag 可以有 0–3 组括号，而且括号里还有别的东西：
#     hakurei_reimu
#     jane_doe_(zenless_zone_zero)
#     byleth_(female)_(fire_emblem)                      ← 第一组是性别限定
#     artoria_pendragon_(alter_swimsuit_rider)_(second_ascension)_(fate)
# 名字里还可能带 `'` `.` `:` `-` `+`（`la+_darknesss`）。
# 用一条正则去塞这些情况，只会写出既难读又漏判的东西。
TAG_CHARS = re.compile(r"^[a-z0-9][a-z0-9'._:+()\- /!]*$")
TAG_GROUP = re.compile(r"\([^()]+\)")


def tag_shape_ok(tag):
    if not tag or not TAG_CHARS.match(tag):
        return False
    # 括号必须配对、且每组都是 `(非空内容)`
    depth, i, n = 0, 0, len(tag)
    while i < n:
        ch = tag[i]
        if ch == "(":
            depth += 1
            if depth > 1:
                return False
            m = TAG_GROUP.match(tag, i)
            if not m:
                return False
            i = m.end()
            depth -= 1
            continue
        if ch == ")":
            return False
        i += 1
    # 有括号的话必须紧跟在主名之后（不能出现在开头）
    if "(" in tag and tag.index("(") == 0:
        return False
    return True

FAILS = []
NOTES = []


def ck(name, cond, note=""):
    if cond:
        print(f"  [OK] {name}")
    else:
        print(f"  [!!] {name}  {note}")
        FAILS.append(f"{name} {note}")


def load_male_tags():
    """从造型台的性别字段拿一份「确定是男性/其他」的角色名集合。

    这是**最强的男性过滤器校验**：造型台那份 7999 条有明确性别标注，
    凡是它标了 1boy / other 的，角色库里就不该出现。
    """
    if not os.path.exists(WARDROBE_POOL):
        return None
    try:
        with open(WARDROBE_POOL, "r", encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        return None
    out = set()
    for c in d.get("characters", []):
        # ⚠️ 只把 **明确标注 1boy** 的当男性证据。
        #    造型台池里还有 650 条 g 为空（未分类），其中不少是女性
        #    （例：绝区零的凯撒·金），拿空值当男性会误杀真角色。
        if c.get("g") == "1boy":
            out.add(str(c.get("n", "")).replace(" ", "_").lower())
    return out


def net_check(tags):
    """抽查这些 tag 在 safebooru 上是不是 category=4 的角色 tag。

    ⚠️ 必须区分两类失败，否则测试会骗人：
       · **标签不存在**（返回了结果但不是 category 4）→ 真问题，说明我们
         编了一个模型不认的 tag，必须报失败。
       · **请求失败**（超时 / 429 / 连接被掐）→ 网络问题，与数据无关。
         尤其当缩略图抓取正在同时压同一个镜像时，失败率会很高。
         这种情况报"无法判定"，不能算数据错误。
    """
    import time as _t
    ok, not_char, unreachable = 0, [], []
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for t in tags:
        u = (f"{MIRROR}/tags.json?search%5Bname%5D="
             + urllib.parse.quote(t))
        got = None
        for attempt in range(3):
            try:
                got = json.loads(op.open(
                    urllib.request.Request(u, headers=UA), timeout=45).read())
                break
            except Exception:
                _t.sleep(1.5 * (attempt + 1))
        if got is None:
            unreachable.append(t)
            continue
        if got and got[0].get("category") == 4:
            ok += 1
        else:
            not_char.append(t)
    return ok, not_char, unreachable


def main():
    net = "--net" in sys.argv
    if not os.path.exists(CHARS):
        print("[SKIP] 还没有角色库（presets/anima_v4_characters.json）。")
        print("       跑 `python tools/build_characters.py` 生成后再测。")
        return 0

    with open(CHARS, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    chars = data.get("characters", [])
    works = data.get("works", [])
    meta = data.get("_meta", {})
    print(f"角色 {len(chars)} 条 · 作品 {len(works)} 个 · 构建于 {meta.get('built_at','?')}")
    print(f"计数器 {meta.get('counters')}\n")

    # ── ① 结构 ────────────────────────────────────────────────────
    print("── ① 结构 ──")
    ck("角色数 ≥ 2000", len(chars) >= 2000, f"实际 {len(chars)}")
    ck("作品数 ≥ 60", len(works) >= 60, f"实际 {len(works)}")

    need = {"tag", "name", "work", "pop", "thumb"}
    missing = [c.get("tag", "?") for c in chars if not need.issubset(c)]
    ck("每条都有必备字段", not missing, f"缺字段 {missing[:5]}")

    badtag = [c["tag"] for c in chars if not tag_shape_ok(c["tag"] or "")]
    ck("角色 tag 形态合法（小写 + 可选 0-3 组括号消歧义）",
       not badtag, f"{badtag[:5]}")

    # trigger 是规则层写进 role 字段的实际取值，必须带作品名 ——
    # 只写角色名，模型可能把同名角色认错（`saber` / `asuna` 这类同名很多）。
    no_trig = [c["tag"] for c in chars if not (c.get("trigger") or "").strip()]
    ck("每条都有 trigger", not no_trig, f"{no_trig[:5]}")

    bad_trig = [c["trigger"] for c in chars
                if c.get("work") and (c["work"] or "").lower()
                not in (c.get("trigger") or "").lower()
                and c["work"].split(":")[0].lower()
                not in (c.get("trigger") or "").lower()]
    ck("trigger 里带作品名", len(bad_trig) <= len(chars) * 0.05,
       f"{len(bad_trig)} 条缺作品名，例 {bad_trig[:5]}")

    pops = [c.get("pop", 0) for c in chars]
    ck("按人气降序排列", all(pops[i] >= pops[i + 1] for i in range(len(pops) - 1)),
       "存在逆序")

    dupe = len(chars) - len({c["tag"] for c in chars})
    ck("tag 无重复", dupe == 0, f"重复 {dupe} 条")

    # ── ② 合规 ────────────────────────────────────────────────────
    print("\n── ② 合规（用户明确要求的排除项）──")
    exc = set(meta.get("filters", {}).get("excluded_works", [])) | {"pokemon"}
    poke_work = [c["tag"] for c in chars
                 if (c.get("work") or "").lower() in exc]
    ck("不含宝可梦作品", not poke_work, f"{poke_work[:5]}")
    poke_hint = [c["tag"] for c in chars
                 if any(h in (c["tag"] or "").lower() for h in POKEMON_HINTS)]
    ck("不含宝可梦角色 tag", not poke_hint, f"{poke_hint[:5]}")

    male = load_male_tags()
    if male is None:
        print("  [--] 造型台池不在，跳过男性交叉验证")
    else:
        leaked = [c["tag"] for c in chars if (c["tag"] or "").lower() in male]
        ck("不含造型台标注为男性/其他的角色", not leaked,
           f"泄漏 {len(leaked)} 条：{leaked[:6]}")

    # ── ③ 覆盖 ────────────────────────────────────────────────────
    print("\n── ③ 目标作品覆盖 ──")
    by_work = {}
    for c in chars:
        by_work.setdefault(c.get("work", ""), []).append(c)
    for w, minimum in TARGET_MIN.items():
        n = len(by_work.get(w, []))
        ck(f"{w} ≥ {minimum} 位女性角色", n >= minimum, f"实际 {n}")

    # ── ④ 完备度 ──────────────────────────────────────────────────
    print("\n── ④ 完备度 ──")
    zh = sum(1 for c in chars if c.get("zh"))
    ck("中文名覆盖 ≥ 35%", zh >= len(chars) * 0.35,
       f"{zh}/{len(chars)} = {zh / max(1, len(chars)) * 100:.0f}%")
    NOTES.append(f"中文名 {zh}/{len(chars)}（{zh / max(1, len(chars)) * 100:.0f}%）")

    feats = sum(1 for c in chars if c.get("tags"))
    ck("特征 tags 覆盖 ≥ 40%", feats >= len(chars) * 0.40,
       f"{feats}/{len(chars)}")

    if os.path.isdir(THUMBS):
        files = {os.path.splitext(f)[0] for f in os.listdir(THUMBS)}
        have = sum(1 for c in chars if c.get("thumb") in files)
        NOTES.append(f"缩略图 {have}/{len(chars)}"
                     f"（{have / max(1, len(chars)) * 100:.0f}%）")
        print(f"  [--] 缩略图覆盖 {have}/{len(chars)}"
              f"（{have / max(1, len(chars)) * 100:.0f}%）—— 不设阈值，抓不到图的角色用色块兜底")
    else:
        NOTES.append("缩略图目录不存在（尚未抓图）")
        print("  [--] 还没有缩略图目录（跑 tools/fetch_character_thumbs.py）")

    # ── ④b /characters 的作品键映射 ────────────────────────────────
    #
    # ⚠️ 这条是 v3.1.0「点 IP 作品后角色列表空掉」那个 bug 的数据层回归：
    #    characters[].work 存的是**作品英文名**（`zenless zone zero`），
    #    而 works[].id 是 slug（`zenless_zone_zero`）。面板点作品写的是 slug、
    #    筛选时却拿英文名去比 —— 永远不相等，于是点任何 IP 都是空列表。
    #    所以接口层必须补 work_id，而且它得真的落在 works.id 里。
    print("\n── ④b /characters 的作品键映射 ──")
    try:
        _nodes = _boot.load("nodes")
        pay = _nodes.characters_payload()
    except Exception as exc:
        pay = None
        ck("能构造 /characters 响应", False, str(exc))

    if pay:
        from collections import Counter
        ids = {w["id"] for w in pay["works"]}
        pcs = pay["characters"]
        miss = [c["tag"] for c in pcs if not c.get("work_id")]
        ck("每个角色都有 work_id", not miss, f"{len(miss)} 条缺失：{miss[:3]}")
        stray = [c["tag"] for c in pcs if c.get("work_id") not in ids]
        ck("work_id 全都落在 works.id 里", not stray, str(stray[:3]))
        real = Counter(c["work_id"] for c in pcs)
        bad = [w["id"] for w in pay["works"]
               if real.get(w["id"], 0) != w["count"]]
        ck("works.count 与实际条数一致", not bad, str(bad[:3]))
        ck("角色仍保留 work（英文名）供搜索与展示",
           all("work" in c for c in pcs[:50]))

    # ── ⑤ 线上抽查 ────────────────────────────────────────────────
    if net:
        print("\n── ⑤ 线上标签抽查（safebooru）──")
        sample = []
        for w in list(TARGET_MIN):
            sample.extend([c["tag"] for c in by_work.get(w, [])][:6])
        sample.extend([c["tag"] for c in chars[:6]])
        ok, not_char, unreachable = net_check(sample)
        ck(f"抽查 {len(sample)} 个 tag 都是真实角色 tag", not not_char,
           f"{len(not_char)} 个不是角色 tag：{not_char[:5]}")
        if unreachable:
            print(f"  [--] {len(unreachable)} 个因网络问题无法判定（不算失败）："
                  f"{unreachable[:4]}")
        print(f"  [--] 判定成功 {ok} · 非角色 tag {len(not_char)} · 网络不可达 {len(unreachable)}")
    else:
        print("\n  [--] 未加 --net，跳过线上标签抽查")

    print()
    for n in NOTES:
        print("  · " + n)
    if FAILS:
        print(f"\n[check_v3_chars] 失败 {len(FAILS)} 项")
        return 1
    print("\n[check_v3_chars] 通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
